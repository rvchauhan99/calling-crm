"""Lead import jobs: Mongo persistence, SSE hub, and in-process worker."""
import asyncio
import json
import logging
import os
from datetime import timedelta
from typing import Optional

from bson.binary import Binary
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pymongo import ReturnDocument

from core import COMPANY_ID, db, new_id, now_iso, now_utc
from lead_import import (
    ImportProgress,
    ImportResult,
    ImportValidationError,
    MAX_FILE_BYTES,
    build_error_csv,
    count_csv_data_rows,
    decode_import_bytes,
    run_lead_import,
)

logger = logging.getLogger(__name__)

WORKER_ID = f"pid-{os.getpid()}"
LOCK_STALE_SECONDS = 60
POLL_SECONDS = 2
MAX_ERROR_SAMPLE = 20

_clients = {}
_wake = None
_worker_task = None


def _get_wake() -> asyncio.Event:
    global _wake
    if _wake is None:
        _wake = asyncio.Event()
    return _wake


def notify_new_job():
    wake = _get_wake()
    wake.set()


def subscribe_events(job_id: str) -> asyncio.Queue:
    queue = asyncio.Queue()
    group = _clients.get(job_id)
    if group is None:
        group = set()
        _clients[job_id] = group
    group.add(queue)
    return queue


def unsubscribe_events(job_id: str, queue: asyncio.Queue):
    group = _clients.get(job_id)
    if not group:
        return
    group.discard(queue)
    if not group:
        _clients.pop(job_id, None)


def emit_job_event(payload: dict):
    group = _clients.get(payload.get("jobId"))
    if not group:
        return
    for queue in list(group):
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass


def close_job_event_stream(job_id: str):
    group = _clients.pop(job_id, None)
    if not group:
        return
    for queue in list(group):
        try:
            queue.put_nowait(None)
        except asyncio.QueueFull:
            pass


def _progress_payload(job_id: str, status: str, progress: dict, message: Optional[str] = None) -> dict:
    created = int(progress.get("created") or 0)
    duplicates = int(progress.get("duplicates") or 0)
    invalid = int(progress.get("invalid") or 0)
    skipped = int(progress.get("skipped") or 0)
    payload = {
        "jobId": job_id,
        "status": status,
        "totalRows": int(progress.get("total") or 0),
        "processedRows": int(progress.get("processed") or 0),
        "successRows": created,
        "failedRows": duplicates + invalid,
        "skippedRows": skipped,
        "created": created,
        "duplicates": duplicates,
        "invalid": invalid,
    }
    if message:
        payload["message"] = message
    return payload


def _empty_progress() -> dict:
    return {"total": 0, "processed": 0, "created": 0, "duplicates": 0, "invalid": 0, "skipped": 0}


def job_status_dto(job: dict) -> dict:
    progress = job.get("progress") or _empty_progress()
    error_rows = job.get("error_rows") or []
    created = int(progress.get("created") or 0)
    duplicates = int(progress.get("duplicates") or 0)
    invalid = int(progress.get("invalid") or 0)
    skipped = int(progress.get("skipped") or 0)
    sample = []
    for err in error_rows[:MAX_ERROR_SAMPLE]:
        sample.append({
            "row": err.get("row"),
            "reason": err.get("reason"),
            "rowData": err.get("row_data") or {},
        })
    return {
        "id": job["id"],
        "status": job.get("status"),
        "fileName": job.get("file_name") or "",
        "createdBy": job.get("created_by"),
        "failureReason": job.get("failure_reason"),
        "progress": {
            "totalRows": int(progress.get("total") or 0),
            "processedRows": int(progress.get("processed") or 0),
            "successRows": created,
            "failedRows": duplicates + invalid,
            "skippedRows": skipped,
            "created": created,
            "duplicates": duplicates,
            "invalid": invalid,
        },
        "errorSample": sample,
        "errorCsvAvailable": len(error_rows) > 0,
    }


async def create_lead_import_job(raw: bytes, file_name: str, actor_id: str) -> dict:
    text = decode_import_bytes(raw)
    count_csv_data_rows(text)
    job_id = new_id()
    doc = {
        "id": job_id,
        "companyId": COMPANY_ID,
        "created_by": actor_id,
        "status": "queued",
        "file_name": file_name or "leads.csv",
        "file_buffer": Binary(raw),
        "original_headers": [],
        "progress": _empty_progress(),
        "error_rows": [],
        "failure_reason": None,
        "locked_at": None,
        "locked_by": None,
        "created_at": now_iso(),
        "started_at": None,
        "finished_at": None,
    }
    await db.lead_import_jobs.insert_one(doc)
    notify_new_job()
    return {"jobId": job_id, "status": "queued"}


async def get_job_for_actor(job_id: str, actor_id: str, *, include_buffer: bool = False) -> dict:
    projection = None if include_buffer else {"file_buffer": 0, "_id": 0}
    job = await db.lead_import_jobs.find_one(
        {"id": job_id, "companyId": COMPANY_ID},
        projection,
    )
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    if job.get("created_by") != actor_id:
        raise HTTPException(status_code=403, detail="You do not have access to this import job")
    job.pop("_id", None)
    return job


async def get_job_error_csv(job_id: str, actor_id: str) -> tuple:
    job = await get_job_for_actor(job_id, actor_id)
    error_rows = job.get("error_rows") or []
    if not error_rows:
        raise HTTPException(status_code=404, detail="No row-level errors found for this import job")
    headers = job.get("original_headers") or []
    from lead_import import ImportErrorRow
    rows = [
        ImportErrorRow(row=e.get("row") or 0, reason=e.get("reason") or "", row_data=e.get("row_data") or {})
        for e in error_rows
    ]
    csv_text = build_error_csv(headers, rows)
    file_name = f"lead-import-errors-{job_id}.csv"
    return file_name, csv_text


async def event_stream(job_id: str):
    queue = subscribe_events(job_id)
    try:
        yield f"event: connected\ndata: {json.dumps({'jobId': job_id})}\n\n"
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            if payload is None:
                break
            yield f"event: progress\ndata: {json.dumps(payload)}\n\n"
    finally:
        unsubscribe_events(job_id, queue)


def sse_response(job_id: str) -> StreamingResponse:
    return StreamingResponse(
        event_stream(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _error_docs(result: ImportResult) -> list:
    return [
        {"row": err.row, "reason": err.reason, "row_data": err.row_data}
        for err in result.error_rows
    ]


async def _claim_next_job() -> Optional[dict]:
    stale_iso = (now_utc() - timedelta(seconds=LOCK_STALE_SECONDS)).isoformat()
    return await db.lead_import_jobs.find_one_and_update(
        {
            "companyId": COMPANY_ID,
            "$or": [
                {"status": "queued"},
                {"status": "processing", "locked_at": {"$lt": stale_iso}},
            ],
        },
        {"$set": {
            "status": "processing",
            "locked_by": WORKER_ID,
            "locked_at": now_iso(),
            "started_at": now_iso(),
        }},
        sort=[("created_at", 1)],
        return_document=ReturnDocument.AFTER,
    )


async def _heartbeat(job_id: str, status: str, result_progress: ImportProgress):
    progress = {
        "total": result_progress.total,
        "processed": result_progress.processed,
        "created": result_progress.created,
        "duplicates": result_progress.duplicates,
        "invalid": result_progress.invalid,
        "skipped": result_progress.skipped,
    }
    await db.lead_import_jobs.update_one(
        {"id": job_id, "companyId": COMPANY_ID},
        {"$set": {
            "locked_at": now_iso(),
            "progress": progress,
        }},
    )
    emit_job_event(_progress_payload(job_id, status, progress))


async def process_job(job: dict):
    job_id = job["id"]
    raw = bytes(job.get("file_buffer") or b"")

    async def on_progress(progress: ImportProgress):
        await _heartbeat(job_id, "processing", progress)

    try:
        result = await run_lead_import(raw, on_progress=on_progress)
        progress = {
            "total": result.total,
            "processed": result.total,
            "created": result.created,
            "duplicates": result.duplicates,
            "invalid": result.invalid,
            "skipped": result.skipped,
        }
        await db.lead_import_jobs.update_one(
            {"id": job_id, "companyId": COMPANY_ID},
            {
                "$set": {
                    "status": "completed",
                    "progress": progress,
                    "error_rows": _error_docs(result),
                    "original_headers": result.original_headers,
                    "failure_reason": None,
                    "finished_at": now_iso(),
                    "locked_at": None,
                    "locked_by": None,
                },
                "$unset": {"file_buffer": ""},
            },
        )
        emit_job_event(_progress_payload(job_id, "completed", progress))
    except ImportValidationError as exc:
        progress = _empty_progress()
        await db.lead_import_jobs.update_one(
            {"id": job_id, "companyId": COMPANY_ID},
            {
                "$set": {
                    "status": "failed",
                    "failure_reason": str(exc),
                    "progress": progress,
                    "finished_at": now_iso(),
                    "locked_at": None,
                    "locked_by": None,
                },
                "$unset": {"file_buffer": ""},
            },
        )
        emit_job_event(_progress_payload(job_id, "failed", progress, str(exc)))
    except Exception:
        logger.exception("Lead import job %s failed", job_id)
        message = "Import failed"
        progress = job.get("progress") or _empty_progress()
        await db.lead_import_jobs.update_one(
            {"id": job_id, "companyId": COMPANY_ID},
            {
                "$set": {
                    "status": "failed",
                    "failure_reason": message,
                    "finished_at": now_iso(),
                    "locked_at": None,
                    "locked_by": None,
                },
                "$unset": {"file_buffer": ""},
            },
        )
        emit_job_event(_progress_payload(job_id, "failed", progress, message))
    finally:
        close_job_event_stream(job_id)


async def lead_import_worker_loop():
    wake = _get_wake()
    logger.info("Lead import worker started (%s)", WORKER_ID)
    while True:
        try:
            job = await _claim_next_job()
            if job:
                await process_job(job)
                continue
            wake.clear()
            try:
                await asyncio.wait_for(wake.wait(), timeout=POLL_SECONDS)
            except asyncio.TimeoutError:
                pass
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Lead import worker loop error")
            await asyncio.sleep(POLL_SECONDS)


def start_lead_import_worker():
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(lead_import_worker_loop())
    return _worker_task


async def stop_lead_import_worker():
    global _worker_task
    if not _worker_task:
        return
    _worker_task.cancel()
    try:
        await _worker_task
    except asyncio.CancelledError:
        pass
    _worker_task = None
