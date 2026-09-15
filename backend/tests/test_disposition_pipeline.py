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
    LEAD_BACKFILL_FLAG,
    apply_lead_pipeline_from_disposition,
    collect_lead_pipeline_mismatches,
    ensure_disposition_pipeline_links,
    ensure_lead_pipeline_from_disposition,
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

    def test_ensure_lead_backfill_oneshot_and_skips(self):
        """ensure_lead_pipeline_from_disposition fixes CB/Busy + Ringing; skips clients; flag skip."""
        mongo, dbname, _company = _env()
        assert mongo and dbname
        company = f"test-co-{uuid.uuid4().hex[:10]}"

        async def go():
            client = AsyncIOMotorClient(mongo)
            try:
                import disposition_pipeline as dp
                import core as core_mod

                prev_db = core_mod.db
                prev_dp_db = dp.db
                prev_co = core_mod.COMPANY_ID
                prev_dp_co = dp.COMPANY_ID
                core_mod.db = client[dbname]
                dp.db = client[dbname]
                core_mod.COMPANY_ID = company
                dp.COMPANY_ID = company
                try:
                    suffix = uuid.uuid4().hex[:8]
                    now = datetime.now(timezone.utc).isoformat()
                    cb_id = f"test-disp-cb-{suffix}"
                    ring_id = f"test-disp-ring-{suffix}"
                    unknown_id = f"test-disp-unk-{suffix}"
                    lids = {
                        "cb": f"test-lead-cb-{suffix}",
                        "ring": f"test-lead-ring-{suffix}",
                        "client": f"test-lead-cli-{suffix}",
                        "converted": f"test-lead-cnv-{suffix}",
                        "unknown": f"test-lead-unk-{suffix}",
                    }
                    cb_name = f"Call Back / Busy {suffix}"
                    ring_name = f"Ringing / No Answer {suffix}"
                    unk_name = f"Unknown Disp {suffix}"

                    await client[dbname].dispositions.insert_many([
                        {
                            "id": cb_id, "companyId": company, "name": cb_name,
                            "type": "carry_forward", "requires_acw": False, "color": "#38BDF8",
                            "order": 91, "active": True,
                            "default_pipeline_stage": "Contacted", "converts_to_client": False,
                            "created_at": now,
                        },
                        {
                            "id": ring_id, "companyId": company, "name": ring_name,
                            "type": "carry_forward", "requires_acw": False, "color": "#7DD3FC",
                            "order": 92, "active": True,
                            "default_pipeline_stage": "Contacted", "converts_to_client": False,
                            "created_at": now,
                        },
                        {
                            "id": unknown_id, "companyId": company, "name": unk_name,
                            "type": "non_carry", "requires_acw": False, "color": "#999",
                            "order": 93, "active": True,
                            "default_pipeline_stage": None, "converts_to_client": False,
                            "created_at": now,
                        },
                    ])
                    await client[dbname].leads.insert_many([
                        {
                            "id": lids["cb"], "companyId": company, "name": "TEST_Ensure_CB",
                            "phone": "81" + suffix[:8], "status": "active", "is_client": False,
                            "pipeline_stage": "New",
                            "disposition_id": cb_id, "disposition_name": cb_name,
                            "created_at": now, "updated_at": now,
                        },
                        {
                            "id": lids["ring"], "companyId": company, "name": "TEST_Ensure_Ring",
                            "phone": "82" + suffix[:8], "status": "active", "is_client": False,
                            "pipeline_stage": "New",
                            "disposition_id": ring_id, "disposition_name": ring_name,
                            "created_at": now, "updated_at": now,
                        },
                        {
                            "id": lids["client"], "companyId": company, "name": "TEST_Ensure_Client",
                            "phone": "83" + suffix[:8], "status": "active", "is_client": True,
                            "pipeline_stage": "New",
                            "disposition_id": cb_id, "disposition_name": cb_name,
                            "created_at": now, "updated_at": now,
                        },
                        {
                            "id": lids["converted"], "companyId": company, "name": "TEST_Ensure_Cnv",
                            "phone": "84" + suffix[:8], "status": "converted", "is_client": False,
                            "pipeline_stage": "New",
                            "disposition_id": cb_id, "disposition_name": cb_name,
                            "created_at": now, "updated_at": now,
                        },
                        {
                            "id": lids["unknown"], "companyId": company, "name": "TEST_Ensure_Unk",
                            "phone": "85" + suffix[:8], "status": "active", "is_client": False,
                            "pipeline_stage": "New",
                            "disposition_id": unknown_id, "disposition_name": unk_name,
                            "created_at": now, "updated_at": now,
                        },
                    ])
                    try:
                        result = await ensure_lead_pipeline_from_disposition()
                        assert result.get("skipped") is not True
                        assert result["updated"] >= 2

                        cb = await client[dbname].leads.find_one(
                            {"id": lids["cb"]}, {"_id": 0, "pipeline_stage": 1},
                        )
                        ring = await client[dbname].leads.find_one(
                            {"id": lids["ring"]}, {"_id": 0, "pipeline_stage": 1},
                        )
                        client_lead = await client[dbname].leads.find_one(
                            {"id": lids["client"]}, {"_id": 0, "pipeline_stage": 1},
                        )
                        cnv = await client[dbname].leads.find_one(
                            {"id": lids["converted"]}, {"_id": 0, "pipeline_stage": 1},
                        )
                        unk = await client[dbname].leads.find_one(
                            {"id": lids["unknown"]}, {"_id": 0, "pipeline_stage": 1},
                        )
                        assert cb["pipeline_stage"] == "Contacted"
                        assert ring["pipeline_stage"] == "Contacted"
                        assert client_lead["pipeline_stage"] == "New"
                        assert cnv["pipeline_stage"] == "New"
                        assert unk["pipeline_stage"] == "New"

                        flag = await client[dbname].system_flags.find_one(
                            {"companyId": company, "id": LEAD_BACKFILL_FLAG},
                            {"_id": 0, "done": 1},
                        )
                        assert flag and flag.get("done") is True

                        second = await ensure_lead_pipeline_from_disposition()
                        assert second.get("skipped") is True
                        assert second.get("updated", 0) == 0
                    finally:
                        await client[dbname].leads.delete_many({"companyId": company})
                        await client[dbname].dispositions.delete_many({"companyId": company})
                        await client[dbname].system_flags.delete_many({"companyId": company})
                finally:
                    core_mod.db = prev_db
                    dp.db = prev_dp_db
                    core_mod.COMPANY_ID = prev_co
                    dp.COMPANY_ID = prev_dp_co
            finally:
                client.close()

        asyncio.run(go())
