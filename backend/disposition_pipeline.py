"""Disposition ↔ pipeline_stage mapping, lifespan ensure, and lead backfill helpers."""
from __future__ import annotations

import logging
from typing import Optional

from core import COMPANY_ID, db, now_iso

logger = logging.getLogger(__name__)

PIPELINE_STAGES = ["New", "Contacted", "Qualified", "Proposal", "Won", "Lost"]

# Production / custom names not in the core seed list
DISPOSITION_PIPELINE_ALIASES = {
    "Call Back / Busy": ("Contacted", False),
    "Busy": ("Contacted", False),
}

MIGRATION_FLAG = "disposition_pipeline_links_v2"


def disposition_pipeline_defaults() -> dict:
    """Seed defaults + production aliases: name → (stage, converts_to_client)."""
    from seed import DISPOSITION_PIPELINE_DEFAULTS
    merged = dict(DISPOSITION_PIPELINE_DEFAULTS)
    merged.update(DISPOSITION_PIPELINE_ALIASES)
    return merged


def mapped_stage_for_disposition(disp: Optional[dict]) -> Optional[str]:
    if not disp:
        return None
    if disp.get("converts_to_client") or disp.get("name") == "Converted":
        return "Won"
    stage = disp.get("default_pipeline_stage")
    if stage and stage in PIPELINE_STAGES:
        return stage
    return None


def is_call_back_disposition(disp: Optional[dict]) -> bool:
    """True for Call Back and production aliases like Call Back / Busy."""
    if not disp:
        return False
    name = (disp.get("name") or "").strip()
    if not name:
        return False
    if name == "Call Back" or name.startswith("Call Back"):
        return True
    return False


async def ensure_disposition_pipeline_links() -> dict:
    """Idempotent: set default_pipeline_stage on known disposition names."""
    defaults = disposition_pipeline_defaults()
    modified = 0
    matched = 0
    for name, (stage, converts) in defaults.items():
        res = await db.dispositions.update_many(
            {"companyId": COMPANY_ID, "name": name},
            {"$set": {
                "default_pipeline_stage": stage,
                "converts_to_client": converts,
            }},
        )
        matched += res.matched_count
        modified += res.modified_count

    await db.dispositions.update_many(
        {"companyId": COMPANY_ID, "default_pipeline_stage": {"$exists": False}},
        {"$set": {"default_pipeline_stage": None}},
    )
    await db.dispositions.update_many(
        {"companyId": COMPANY_ID, "converts_to_client": {"$exists": False}},
        {"$set": {"converts_to_client": False}},
    )
    await db.dispositions.update_many(
        {"companyId": COMPANY_ID, "name": "Converted"},
        {"$set": {"default_pipeline_stage": "Won", "converts_to_client": True}},
    )
    # Call Back family: no ACW — follow-up is the next work
    for name in defaults:
        if name == "Call Back" or name.startswith("Call Back"):
            await db.dispositions.update_many(
                {"companyId": COMPANY_ID, "name": name},
                {"$set": {"requires_acw": False}},
            )

    await db.system_flags.update_one(
        {"companyId": COMPANY_ID, "id": MIGRATION_FLAG},
        {"$set": {
            "companyId": COMPANY_ID,
            "id": MIGRATION_FLAG,
            "done": True,
            "completed_at": now_iso(),
            "matched": matched,
            "modified": modified,
        }},
        upsert=True,
    )
    logger.info(
        "Disposition pipeline links ensured: matched=%s modified=%s",
        matched, modified,
    )
    return {"matched": matched, "modified": modified}


async def collect_lead_pipeline_mismatches(limit_samples: int = 5) -> dict:
    """Find non-client leads whose pipeline_stage ≠ disposition mapped stage."""
    disps = await db.dispositions.find(
        {"companyId": COMPANY_ID},
        {"_id": 0, "id": 1, "name": 1, "default_pipeline_stage": 1, "converts_to_client": 1},
    ).to_list(500)
    by_id = {d["id"]: d for d in disps if d.get("id")}
    by_name = {d["name"]: d for d in disps if d.get("name")}

    buckets: dict = {}
    total = 0
    samples: list = []

    cursor = db.leads.find(
        {
            "companyId": COMPANY_ID,
            "is_client": {"$ne": True},
            "status": {"$ne": "converted"},
            "$or": [
                {"disposition_id": {"$ne": None}},
                {"disposition_name": {"$nin": [None, ""]}},
            ],
        },
        {
            "_id": 0, "id": 1, "name": 1, "pipeline_stage": 1,
            "disposition_id": 1, "disposition_name": 1,
        },
    )
    async for lead in cursor:
        disp = None
        if lead.get("disposition_id"):
            disp = by_id.get(lead["disposition_id"])
        if not disp and lead.get("disposition_name"):
            disp = by_name.get(lead["disposition_name"])
        mapped = mapped_stage_for_disposition(disp) if disp else None
        if not mapped:
            continue
        current = lead.get("pipeline_stage") or "New"
        if current == mapped:
            continue
        key = f"{disp.get('name')}|{current}->{mapped}"
        buckets[key] = buckets.get(key, 0) + 1
        total += 1
        if len(samples) < limit_samples:
            samples.append({
                "id": lead["id"],
                "name": lead.get("name"),
                "disposition": disp.get("name"),
                "from": current,
                "to": mapped,
            })

    return {"total": total, "buckets": buckets, "samples": samples}


async def apply_lead_pipeline_from_disposition() -> dict:
    """Set lead.pipeline_stage from disposition mapping for mismatched non-client leads."""
    disps = await db.dispositions.find(
        {"companyId": COMPANY_ID},
        {"_id": 0, "id": 1, "name": 1, "default_pipeline_stage": 1, "converts_to_client": 1},
    ).to_list(500)
    by_id = {d["id"]: d for d in disps if d.get("id")}
    by_name = {d["name"]: d for d in disps if d.get("name")}

    updated = 0
    by_disp: dict = {}
    now = now_iso()

    cursor = db.leads.find(
        {
            "companyId": COMPANY_ID,
            "is_client": {"$ne": True},
            "status": {"$ne": "converted"},
            "$or": [
                {"disposition_id": {"$ne": None}},
                {"disposition_name": {"$nin": [None, ""]}},
            ],
        },
        {
            "_id": 0, "id": 1, "pipeline_stage": 1,
            "disposition_id": 1, "disposition_name": 1,
        },
    )
    async for lead in cursor:
        disp = None
        if lead.get("disposition_id"):
            disp = by_id.get(lead["disposition_id"])
        if not disp and lead.get("disposition_name"):
            disp = by_name.get(lead["disposition_name"])
        mapped = mapped_stage_for_disposition(disp) if disp else None
        if not mapped:
            continue
        current = lead.get("pipeline_stage") or "New"
        if current == mapped:
            continue
        res = await db.leads.update_one(
            {"id": lead["id"], "companyId": COMPANY_ID},
            {"$set": {"pipeline_stage": mapped, "updated_at": now}},
        )
        if res.modified_count:
            updated += 1
            dname = disp.get("name") or "?"
            by_disp[dname] = by_disp.get(dname, 0) + 1

    return {"updated": updated, "by_disposition": by_disp}
