"""Idempotent boot migration: void convert calls for soft-deleted (undone) clients."""
import logging

from core import COMPANY_ID, db, now_iso
from routes_clients import _convert_disposition_names, _is_convert_disposition_name

logger = logging.getLogger(__name__)

MIGRATION_REASON = "migration:undone_client_backfill"
MIGRATION_FLAG = "undone_convert_reports_cleanup_v1"


async def _flag_done() -> bool:
    doc = await db.system_flags.find_one(
        {"companyId": COMPANY_ID, "id": MIGRATION_FLAG},
        {"_id": 0, "done": 1},
    )
    return bool(doc and doc.get("done"))


async def _mark_done() -> None:
    await db.system_flags.update_one(
        {"companyId": COMPANY_ID, "id": MIGRATION_FLAG},
        {"$set": {
            "companyId": COMPANY_ID,
            "id": MIGRATION_FLAG,
            "done": True,
            "completed_at": now_iso(),
        }},
        upsert=True,
    )


async def ensure_exclude_undone_convert_calls() -> dict:
    """Mark Converted/Deposit calls for soft-deleted clients as excluded_from_reports.

    Also clears leftover convert dispositions on those leads when they are no longer clients.
    Idempotent: second run finds nothing left to void (or skips via flag).
    """
    soft_q = {
        "companyId": COMPANY_ID,
        "deleted_at": {"$ne": None},
        "lead_id": {"$exists": True, "$nin": [None, ""]},
    }
    if await _flag_done():
        remaining = await db.clients.count_documents(soft_q)
        if remaining == 0:
            logger.info("Undone-convert reports cleanup: already done, skipping")
            return {"clients_scanned": 0, "calls_excluded": 0, "leads_cleared": 0, "skipped": True}

    convert_names = await _convert_disposition_names()
    soft_clients = []
    async for c in db.clients.find(soft_q, {"_id": 0, "id": 1, "lead_id": 1}):
        soft_clients.append(c)
        if len(soft_clients) >= 100000:
            break

    lead_ids = sorted({c["lead_id"] for c in soft_clients if c.get("lead_id")})
    if not lead_ids:
        await _mark_done()
        logger.info("Undone-convert reports cleanup: nothing to do (no soft-deleted clients)")
        return {"clients_scanned": 0, "calls_excluded": 0, "leads_cleared": 0}

    now = now_iso()
    call_ids = []
    async for c in db.calls.find(
        {
            "companyId": COMPANY_ID,
            "lead_id": {"$in": lead_ids},
            "excluded_from_reports": {"$ne": True},
        },
        {"_id": 0, "id": 1, "disposition_name": 1},
    ):
        if _is_convert_disposition_name(c.get("disposition_name"), convert_names):
            call_ids.append(c["id"])

    calls_excluded = 0
    if call_ids:
        res = await db.calls.update_many(
            {"id": {"$in": call_ids}, "companyId": COMPANY_ID},
            {"$set": {
                "excluded_from_reports": True,
                "excluded_at": now,
                "excluded_reason": MIGRATION_REASON,
            }},
        )
        calls_excluded = res.modified_count

    leads_cleared = 0
    for lid in lead_ids:
        lead = await db.leads.find_one({"id": lid, "companyId": COMPANY_ID}, {"_id": 0})
        if not lead:
            continue
        if lead.get("is_client"):
            continue
        lead_set = {"updated_at": now}
        changed = False
        if _is_convert_disposition_name(lead.get("disposition_name"), convert_names):
            lead_set["disposition_id"] = None
            lead_set["disposition_name"] = None
            lead_set["carry_forward"] = True
            changed = True
        if lead.get("pipeline_stage") == "Won":
            lead_set["pipeline_stage"] = "Contacted"
            changed = True
        if lead.get("client_id"):
            lead_set["client_id"] = None
            changed = True
        if changed:
            await db.leads.update_one(
                {"id": lid, "companyId": COMPANY_ID},
                {"$set": lead_set},
            )
            leads_cleared += 1

    await _mark_done()
    out = {
        "clients_scanned": len(soft_clients),
        "calls_excluded": calls_excluded,
        "leads_cleared": leads_cleared,
    }
    logger.info(
        "Undone-convert reports cleanup: scanned %s clients, excluded %s calls, cleared %s leads",
        out["clients_scanned"], out["calls_excluded"], out["leads_cleared"],
    )
    return out
