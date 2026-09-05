"""Sheet Sources master: CRUD, inspect/map, preview, sync, run history."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import COMPANY_ID, audit, db, new_id, now_iso, require
from lead_constants import LEAD_SOURCES
from sheet_sync import (
    DEFAULT_POLL_SECONDS,
    MIN_POLL_SECONDS,
    SheetAccessError,
    SheetParseError,
    default_column_map,
    inspect_sheet,
    parse_sheet_url,
    preview_draft,
    preview_source,
    sync_source,
    validate_column_map,
)

router = APIRouter(prefix="/api")


class SheetSourceIn(BaseModel):
    name: str
    sheet_url: str
    enabled: bool = True
    auto_assign: bool = False
    source: str = "Facebook Ads"
    preset: str = "meta_lead_ads"
    column_map: Optional[dict] = None
    poll_seconds: int = DEFAULT_POLL_SECONDS


class SyncIn(BaseModel):
    """Optional inline CSV for tests / offline sync without hitting Google."""
    csv_text: Optional[str] = None


class InspectIn(BaseModel):
    sheet_url: str
    preset: str = "meta_lead_ads"
    csv_text: Optional[str] = None


class PreviewDraftIn(BaseModel):
    sheet_url: str
    preset: str = "meta_lead_ads"
    column_map: Optional[dict] = None
    csv_text: Optional[str] = None


def _validate_body(body: SheetSourceIn) -> dict:
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    try:
        spreadsheet_id, gid = parse_sheet_url(body.sheet_url)
    except SheetParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    preset = (body.preset or "generic").strip()
    if preset not in ("meta_lead_ads", "generic"):
        raise HTTPException(status_code=400, detail="Invalid preset")
    lead_source = (body.source or "Facebook Ads").strip()
    if lead_source not in LEAD_SOURCES:
        raise HTTPException(status_code=400, detail="Invalid source")
    poll = int(body.poll_seconds or DEFAULT_POLL_SECONDS)
    if poll < MIN_POLL_SECONDS:
        poll = MIN_POLL_SECONDS
    try:
        if body.column_map is not None:
            cmap = validate_column_map(body.column_map)
        else:
            cmap = validate_column_map(default_column_map(preset))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "name": name,
        "sheet_url": body.sheet_url.strip(),
        "spreadsheet_id": spreadsheet_id,
        "gid": gid,
        "enabled": bool(body.enabled),
        "auto_assign": bool(body.auto_assign),
        "source": lead_source,
        "preset": preset,
        "column_map": cmap,
        "poll_seconds": poll,
    }


@router.get("/sheet-sources")
async def list_sheet_sources(principal: dict = Depends(require("sheet_sources:view"))):
    items = await db.sheet_sources.find(
        {"companyId": COMPANY_ID}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    return {"sheet_sources": items}


@router.post("/sheet-sources")
async def create_sheet_source(
    body: SheetSourceIn,
    principal: dict = Depends(require("sheet_sources:create")),
):
    data = _validate_body(body)
    sid = new_id()
    doc = {
        "id": sid,
        "companyId": COMPANY_ID,
        **data,
        "last_synced_at": None,
        "last_status": "never",
        "last_error": None,
        "last_result": None,
        "syncing": False,
        "sync_lock_until": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.sheet_sources.insert_one(dict(doc))
    await audit(principal, "create", "sheet_source", sid, {"name": data["name"]})
    return {"sheet_source": {k: v for k, v in doc.items() if k != "_id"}}


@router.post("/sheet-sources/inspect")
async def inspect_sheet_source(
    body: InspectIn,
    principal: dict = Depends(require("sheet_sources:view")),
):
    preset = (body.preset or "meta_lead_ads").strip()
    if preset not in ("meta_lead_ads", "generic"):
        raise HTTPException(status_code=400, detail="Invalid preset")
    try:
        return await inspect_sheet(
            body.sheet_url,
            preset=preset,
            csv_text=body.csv_text,
        )
    except SheetParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except SheetAccessError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sheet-sources/preview-draft")
async def preview_draft_sheet(
    body: PreviewDraftIn,
    principal: dict = Depends(require("sheet_sources:view")),
):
    preset = (body.preset or "meta_lead_ads").strip()
    if preset not in ("meta_lead_ads", "generic"):
        raise HTTPException(status_code=400, detail="Invalid preset")
    try:
        cmap = None
        if body.column_map is not None:
            cmap = validate_column_map(body.column_map)
        return await preview_draft(
            sheet_url=body.sheet_url,
            preset=preset,
            column_map=cmap,
            csv_text=body.csv_text,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except SheetParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except SheetAccessError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/sheet-sources/{sid}")
async def update_sheet_source(
    sid: str,
    body: SheetSourceIn,
    principal: dict = Depends(require("sheet_sources:edit")),
):
    existing = await db.sheet_sources.find_one(
        {"id": sid, "companyId": COMPANY_ID}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Sheet source not found")
    data = _validate_body(body)
    data["updated_at"] = now_iso()
    await db.sheet_sources.update_one(
        {"id": sid, "companyId": COMPANY_ID}, {"$set": data}
    )
    await audit(principal, "update", "sheet_source", sid, {"name": data["name"]})
    updated = await db.sheet_sources.find_one(
        {"id": sid, "companyId": COMPANY_ID}, {"_id": 0}
    )
    return {"sheet_source": updated}


@router.delete("/sheet-sources/{sid}")
async def delete_sheet_source(
    sid: str,
    principal: dict = Depends(require("sheet_sources:delete")),
):
    existing = await db.sheet_sources.find_one(
        {"id": sid, "companyId": COMPANY_ID}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Sheet source not found")
    await db.sheet_sources.delete_one({"id": sid, "companyId": COMPANY_ID})
    await audit(principal, "delete", "sheet_source", sid, {"name": existing.get("name")})
    return {"ok": True}


@router.post("/sheet-sources/{sid}/sync")
async def sync_sheet_source(
    sid: str,
    body: Optional[SyncIn] = None,
    principal: dict = Depends(require("sheet_sources:sync")),
):
    source = await db.sheet_sources.find_one(
        {"id": sid, "companyId": COMPANY_ID}, {"_id": 0}
    )
    if not source:
        raise HTTPException(status_code=404, detail="Sheet source not found")
    csv_text = body.csv_text if body else None
    result = await sync_source(source, csv_text=csv_text, acquire_lock=True)
    await audit(principal, "sync", "sheet_source", sid, {
        "created": result.get("created"),
        "duplicates": result.get("duplicates"),
        "assigned": result.get("assigned"),
        "status": result.get("status"),
    })
    return result


@router.get("/sheet-sources/{sid}/preview")
async def preview_sheet_source(
    sid: str,
    principal: dict = Depends(require("sheet_sources:view")),
):
    source = await db.sheet_sources.find_one(
        {"id": sid, "companyId": COMPANY_ID}, {"_id": 0}
    )
    if not source:
        raise HTTPException(status_code=404, detail="Sheet source not found")
    try:
        return await preview_source(source)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sheet-sources/{sid}/runs")
async def list_sheet_sync_runs(
    sid: str,
    principal: dict = Depends(require("sheet_sources:view")),
):
    source = await db.sheet_sources.find_one(
        {"id": sid, "companyId": COMPANY_ID}, {"_id": 0, "id": 1}
    )
    if not source:
        raise HTTPException(status_code=404, detail="Sheet source not found")
    runs = await db.sheet_sync_runs.find(
        {"companyId": COMPANY_ID, "sheet_source_id": sid},
        {"_id": 0},
    ).sort("created_at", -1).to_list(50)
    return {"runs": runs}
