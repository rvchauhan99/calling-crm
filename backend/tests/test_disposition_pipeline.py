"""Disposition pipeline mapping + lead backfill helpers."""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from dotenv import dotenv_values, load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(_root / ".env")

from disposition_pipeline import (
    apply_lead_pipeline_from_disposition,
    collect_lead_pipeline_mismatches,
    ensure_disposition_pipeline_links,
    is_call_back_disposition,
    mapped_stage_for_disposition,
)


def _env():
    env = dotenv_values(_root / ".env")
    mongo = os.environ.get("MONGO_URL") or env.get("MONGO_URL")
    dbname = os.environ.get("DB_NAME") or env.get("DB_NAME")
    company = os.environ.get("COMPANY_ID") or env.get("COMPANY_ID") or "default"
    return mongo, dbname, company


class TestDispositionPipelineHelpers:
    def test_mapped_stage_and_call_back_alias(self):
        assert mapped_stage_for_disposition({
            "name": "Call Back / Busy",
            "default_pipeline_stage": "Contacted",
        }) == "Contacted"
        assert is_call_back_disposition({"name": "Call Back"})
        assert is_call_back_disposition({"name": "Call Back / Busy"})
        assert not is_call_back_disposition({"name": "Interested"})

    def test_ensure_and_backfill_lead_stage(self):
        mongo, dbname, company = _env()
        assert mongo and dbname

        async def go():
            client = AsyncIOMotorClient(mongo)
            try:
                import disposition_pipeline as dp
                import core as core_mod

                prev_db = core_mod.db
                prev_dp_db = dp.db
                core_mod.db = client[dbname]
                dp.db = client[dbname]
                try:
                    await ensure_disposition_pipeline_links()
                    # Unique name so parallel tests never wipe shared masters
                    dname = f"Call Back / Busy {uuid.uuid4().hex[:8]}"
                    did = f"test-disp-{uuid.uuid4().hex[:10]}"
                    lid = f"test-lead-{uuid.uuid4().hex[:10]}"
                    phone = "87" + str(uuid.uuid4().int)[:8]
                    now = datetime.now(timezone.utc).isoformat()
                    await client[dbname].dispositions.insert_one({
                        "id": did, "companyId": company, "name": dname,
                        "type": "carry_forward", "requires_acw": False, "color": "#38BDF8",
                        "order": 99, "active": True,
                        "default_pipeline_stage": "Contacted", "converts_to_client": False,
                        "created_at": now,
                    })
                    await client[dbname].leads.insert_one({
                        "id": lid, "companyId": company, "name": "TEST_Backfill_CBBusy",
                        "phone": phone, "status": "active", "is_client": False,
                        "pipeline_stage": "New",
                        "disposition_id": did, "disposition_name": dname,
                        "created_at": now, "updated_at": now,
                    })
                    try:
                        report = await collect_lead_pipeline_mismatches(limit_samples=50)
                        assert report["total"] >= 1
                        assert any(s["id"] == lid for s in report["samples"]) or any(
                            dname in k and "New->Contacted" in k for k in report["buckets"]
                        )
                        result = await apply_lead_pipeline_from_disposition()
                        assert result["updated"] >= 1
                        lead = await client[dbname].leads.find_one(
                            {"id": lid}, {"_id": 0, "pipeline_stage": 1},
                        )
                        assert lead["pipeline_stage"] == "Contacted"
                    finally:
                        await client[dbname].leads.delete_one({"id": lid})
                        await client[dbname].dispositions.delete_one(
                            {"id": did, "companyId": company},
                        )
                finally:
                    core_mod.db = prev_db
                    dp.db = prev_dp_db
            finally:
                client.close()

        asyncio.run(go())
