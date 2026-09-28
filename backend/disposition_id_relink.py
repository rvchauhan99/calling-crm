"""Relink lead/call disposition_id from stored disposition_name.

Master edits can leave leads pointing at the wrong dispositions row while
disposition_name (the display/filter source of truth) still matches a current
master. This module rewrites only disposition_id.
"""
from __future__ import annotations

import logging

from core import COMPANY_ID, db, now_iso

logger = logging.getLogger(__name__)

RELINK_FLAG = "disposition_lead_id_relink_v1"
_EMPTY_NAMES = (None, "")


def _disposition_rank(doc: dict) -> tuple:
    """Prefer active, then lowest order/slot, then id."""
    active = bool(doc.get("active", True))
    order = doc.get("order")
    if order is None:
        order = doc.get("slot")
    if not isinstance(order, (int, float)):
        order = 10**9
    return (0 if active else 1, order, doc.get("id") or "")


async def canonical_disposition_ids_by_name() -> dict:
    """Trimmed master name → canonical disposition id for COMPANY_ID."""
    docs = await db.dispositions.find(
        {"companyId": COMPANY_ID},
        {"_id": 0, "id": 1, "name": 1, "active": 1, "order": 1, "slot": 1},
    ).to_list(500)
    grouped: dict[str, list] = {}
    for doc in docs:
        name = (doc.get("name") or "").strip()
        if not name or not doc.get("id"):
            continue
        grouped.setdefault(name, []).append(doc)
    result = {}
    for name, rows in grouped.items():
        rows.sort(key=_disposition_rank)
        result[name] = rows[0]["id"]
    return result


def _mismatch_filter(name: str, canonical_id: str) -> dict:
    return {
        "companyId": COMPANY_ID,
        "disposition_name": name,
        "disposition_id": {"$ne": canonical_id},
    }


async def _count_relinkable(by_name: dict) -> dict:
    leads = 0
    calls = 0
    by_disp: dict = {}
    for name, did in by_name.items():
        filt = _mismatch_filter(name, did)
        n_leads = await db.leads.count_documents(filt)
        n_calls = await db.calls.count_documents(filt)
        if n_leads or n_calls:
            by_disp[name] = n_leads + n_calls
        leads += n_leads
        calls += n_calls
    return {"leads": leads, "calls": calls, "by_disposition": by_disp}


async def _count_remaining_mismatches(by_name: dict) -> int:
    counts = await _count_relinkable(by_name)
    return counts["leads"] + counts["calls"]


async def _unmatched_name_counts(known_names: set) -> dict:
    """Non-empty stored names that have no current master."""
    unmatched: dict = {}
    known = list(known_names)
    exclude = list(_EMPTY_NAMES) + known
    for coll in (db.leads, db.calls):
        async for row in coll.aggregate([
            {
                "$match": {
                    "companyId": COMPANY_ID,
                    "disposition_name": {"$nin": exclude},
                },
            },
            {"$group": {"_id": "$disposition_name", "n": {"$sum": 1}}},
        ]):
            name = row.get("_id")
            if name in _EMPTY_NAMES:
                continue
            unmatched[name] = unmatched.get(name, 0) + int(row.get("n") or 0)
    return unmatched


async def collect_disposition_id_mismatches(limit_samples: int = 10) -> dict:
    """Dry-run: leads/calls whose disposition_id does not match the name's master."""
    by_name = await canonical_disposition_ids_by_name()
    counts = await _count_relinkable(by_name)
    unmatched = await _unmatched_name_counts(set(by_name.keys()))
    samples: list = []

    if limit_samples > 0:
        for name, did in by_name.items():
            if len(samples) >= limit_samples:
                break
            cursor = db.leads.find(
                _mismatch_filter(name, did),
                {"_id": 0, "id": 1, "name": 1, "disposition_id": 1, "disposition_name": 1},
            )
            async for lead in cursor:
                samples.append({
                    "lead_id": lead.get("id"),
                    "name": lead.get("name"),
                    "stored_name": lead.get("disposition_name"),
                    "old_id": lead.get("disposition_id"),
                    "new_id": did,
                })
                if len(samples) >= limit_samples:
                    break

    updated = counts["leads"] + counts["calls"]
    return {
        "updated": updated,
        "leads": counts["leads"],
        "calls": counts["calls"],
        "by_disposition": counts["by_disposition"],
        "unmatched": unmatched,
        "unmatched_count": sum(unmatched.values()),
        "samples": samples,
    }


async def apply_disposition_id_relink() -> dict:
    """Bulk-set disposition_id from the current master matching disposition_name."""
    by_name = await canonical_disposition_ids_by_name()
    now = now_iso()
    leads_updated = 0
    calls_updated = 0
    by_disp: dict = {}

    for name, did in by_name.items():
        filt = _mismatch_filter(name, did)
        lead_res = await db.leads.update_many(
            filt,
            {"$set": {"disposition_id": did, "updated_at": now}},
        )
        call_res = await db.calls.update_many(
            filt,
            {"$set": {"disposition_id": did}},
        )
        n = lead_res.modified_count + call_res.modified_count
        leads_updated += lead_res.modified_count
        calls_updated += call_res.modified_count
        if n:
            by_disp[name] = n

    unmatched = await _unmatched_name_counts(set(by_name.keys()))
    return {
        "leads_updated": leads_updated,
        "calls_updated": calls_updated,
        "updated": leads_updated + calls_updated,
        "by_disposition": by_disp,
        "unmatched": unmatched,
        "unmatched_count": sum(unmatched.values()),
    }


async def _relink_flag_done() -> bool:
    doc = await db.system_flags.find_one(
        {"companyId": COMPANY_ID, "id": RELINK_FLAG},
        {"_id": 0, "done": 1},
    )
    return bool(doc and doc.get("done"))


async def _mark_relink_done(result: dict) -> None:
    await db.system_flags.update_one(
        {"companyId": COMPANY_ID, "id": RELINK_FLAG},
        {"$set": {
            "companyId": COMPANY_ID,
            "id": RELINK_FLAG,
            "done": True,
            "completed_at": now_iso(),
            "updated": result.get("updated", 0),
            "leads_updated": result.get("leads_updated", 0),
            "calls_updated": result.get("calls_updated", 0),
            "by_disposition": result.get("by_disposition") or {},
            "unmatched_count": result.get("unmatched_count", 0),
        }},
        upsert=True,
    )


async def ensure_disposition_id_relink() -> dict:
    """One-shot boot migration: set lead/call disposition_id from stored name.

    Idempotent via disposition_lead_id_relink_v1. If flagged done and no
    remaining relinkable mismatches, skips. Unmatched names are left as-is.
    """
    by_name = await canonical_disposition_ids_by_name()

    if await _relink_flag_done():
        remaining = await _count_remaining_mismatches(by_name)
        if remaining == 0:
            logger.info("Disposition id relink: already done, skipping")
            return {
                "updated": 0,
                "leads_updated": 0,
                "calls_updated": 0,
                "by_disposition": {},
                "unmatched": {},
                "unmatched_count": 0,
                "skipped": True,
            }

    result = await apply_disposition_id_relink()
    await _mark_relink_done(result)
    logger.info(
        "Disposition id relink: updated=%s leads=%s calls=%s unmatched=%s by_disposition=%s",
        result.get("updated"),
        result.get("leads_updated"),
        result.get("calls_updated"),
        result.get("unmatched_count"),
        result.get("by_disposition"),
    )
    return result
