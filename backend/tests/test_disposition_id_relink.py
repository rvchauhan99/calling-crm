"""Relink lead/call disposition_id from stored disposition_name."""
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

from disposition_id_relink import (
    RELINK_FLAG,
    apply_disposition_id_relink,
    canonical_disposition_ids_by_name,
    collect_disposition_id_mismatches,
    ensure_disposition_id_relink,
)


def _env():
    env = dotenv_values(_root / ".env")
    mongo = os.environ.get("MONGO_URL") or env.get("MONGO_URL")
    dbname = os.environ.get("DB_NAME") or env.get("DB_NAME")
    return mongo, dbname


async def _with_isolated_company(fn):
    mongo, dbname = _env()
    assert mongo and dbname
    company = f"test-co-{uuid.uuid4().hex[:10]}"
    client = AsyncIOMotorClient(mongo)
    try:
        import core as core_mod
        import disposition_id_relink as relink_mod

        prev_db = core_mod.db
        prev_relink_db = relink_mod.db
        prev_co = core_mod.COMPANY_ID
        prev_relink_co = relink_mod.COMPANY_ID
        core_mod.db = client[dbname]
        relink_mod.db = client[dbname]
        core_mod.COMPANY_ID = company
        relink_mod.COMPANY_ID = company
        try:
            return await fn(client[dbname], company)
        finally:
            await client[dbname].leads.delete_many({"companyId": company})
            await client[dbname].calls.delete_many({"companyId": company})
            await client[dbname].dispositions.delete_many({"companyId": company})
            await client[dbname].system_flags.delete_many({"companyId": company})
            core_mod.db = prev_db
            relink_mod.db = prev_relink_db
            core_mod.COMPANY_ID = prev_co
            relink_mod.COMPANY_ID = prev_relink_co
    finally:
        client.close()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _disp(company, did, name, *, active=True, order=1):
    return {
        "id": did,
        "companyId": company,
        "name": name,
        "type": "carry_forward",
        "requires_acw": False,
        "color": "#38BDF8",
        "order": order,
        "active": active,
        "created_at": _now(),
    }


def _lead(company, lid, *, disp_id, disp_name, phone):
    return {
        "id": lid,
        "companyId": company,
        "name": "TEST_Relink_Lead",
        "phone": phone,
        "status": "active",
        "disposition_id": disp_id,
        "disposition_name": disp_name,
        "created_at": _now(),
        "updated_at": "2020-01-01T00:00:00+00:00",
    }


def _call(company, cid, lid, *, disp_id, disp_name):
    return {
        "id": cid,
        "companyId": company,
        "lead_id": lid,
        "disposition_id": disp_id,
        "disposition_name": disp_name,
        "created_at": _now(),
    }


class TestDispositionIdRelink:
    def test_happy_path_relinks_stale_id_from_name(self):
        async def go(coll, company):
            suffix = uuid.uuid4().hex[:8]
            cb_id = f"test-disp-cb-{suffix}"
            ni_id = f"test-disp-ni-{suffix}"
            lid = f"test-lead-{suffix}"
            cid = f"test-call-{suffix}"
            await coll.dispositions.insert_many([
                _disp(company, cb_id, "Call Back", order=1),
                _disp(company, ni_id, "Not Interested", order=2),
            ])
            await coll.leads.insert_one(_lead(
                company, lid, disp_id=ni_id, disp_name="Call Back",
                phone="81" + suffix[:8],
            ))
            await coll.calls.insert_one(_call(
                company, cid, lid, disp_id=ni_id, disp_name="Call Back",
            ))

            report = await collect_disposition_id_mismatches(limit_samples=10)
            assert report["updated"] >= 2
            assert report["leads"] >= 1
            assert report["calls"] >= 1
            assert any(s["lead_id"] == lid for s in report["samples"])

            result = await apply_disposition_id_relink()
            assert result["leads_updated"] >= 1
            assert result["calls_updated"] >= 1
            assert result["by_disposition"].get("Call Back", 0) >= 2

            lead = await coll.leads.find_one(
                {"id": lid}, {"_id": 0, "disposition_id": 1, "disposition_name": 1},
            )
            call = await coll.calls.find_one(
                {"id": cid}, {"_id": 0, "disposition_id": 1, "disposition_name": 1},
            )
            assert lead["disposition_id"] == cb_id
            assert lead["disposition_name"] == "Call Back"
            assert call["disposition_id"] == cb_id
            assert call["disposition_name"] == "Call Back"

        asyncio.run(_with_isolated_company(go))

    def test_ensure_oneshot_and_skips(self):
        async def go(coll, company):
            suffix = uuid.uuid4().hex[:8]
            cb_id = f"test-disp-cb-{suffix}"
            stale_id = f"test-disp-stale-{suffix}"
            lid = f"test-lead-{suffix}"
            await coll.dispositions.insert_one(_disp(company, cb_id, "Call Back"))
            await coll.leads.insert_one(_lead(
                company, lid, disp_id=stale_id, disp_name="Call Back",
                phone="82" + suffix[:8],
            ))

            first = await ensure_disposition_id_relink()
            assert first.get("skipped") is not True
            assert first["leads_updated"] >= 1
            flag = await coll.system_flags.find_one(
                {"companyId": company, "id": RELINK_FLAG},
                {"_id": 0, "done": 1},
            )
            assert flag and flag.get("done") is True

            lead = await coll.leads.find_one(
                {"id": lid}, {"_id": 0, "disposition_id": 1},
            )
            assert lead["disposition_id"] == cb_id

            second = await ensure_disposition_id_relink()
            assert second.get("skipped") is True
            assert second.get("updated", 0) == 0

        asyncio.run(_with_isolated_company(go))

    def test_unmatched_empty_and_duplicate_masters(self):
        async def go(coll, company):
            suffix = uuid.uuid4().hex[:8]
            inactive_id = f"test-disp-inact-{suffix}"
            active_id = f"test-disp-act-{suffix}"
            lid_dup = f"test-lead-dup-{suffix}"
            lid_unmatched = f"test-lead-unk-{suffix}"
            lid_empty = f"test-lead-empty-{suffix}"
            fake_id = f"test-fake-{suffix}"
            empty_keep_id = f"test-empty-keep-{suffix}"

            await coll.dispositions.insert_many([
                _disp(company, inactive_id, "Call Back", active=False, order=1),
                _disp(company, active_id, "Call Back", active=True, order=5),
            ])
            by_name = await canonical_disposition_ids_by_name()
            assert by_name["Call Back"] == active_id

            await coll.leads.insert_many([
                _lead(
                    company, lid_dup, disp_id=inactive_id, disp_name="Call Back",
                    phone="83" + suffix[:8],
                ),
                _lead(
                    company, lid_unmatched, disp_id=fake_id, disp_name="No Such Disp",
                    phone="84" + suffix[:8],
                ),
                _lead(
                    company, lid_empty, disp_id=empty_keep_id, disp_name=None,
                    phone="85" + suffix[:8],
                ),
            ])

            result = await apply_disposition_id_relink()
            assert result["unmatched_count"] >= 1
            assert result["unmatched"].get("No Such Disp", 0) >= 1

            dup = await coll.leads.find_one(
                {"id": lid_dup}, {"_id": 0, "disposition_id": 1},
            )
            unmatched = await coll.leads.find_one(
                {"id": lid_unmatched},
                {"_id": 0, "disposition_id": 1, "disposition_name": 1},
            )
            empty = await coll.leads.find_one(
                {"id": lid_empty}, {"_id": 0, "disposition_id": 1, "disposition_name": 1},
            )
            assert dup["disposition_id"] == active_id
            assert unmatched["disposition_id"] == fake_id
            assert unmatched["disposition_name"] == "No Such Disp"
            assert empty["disposition_id"] == empty_keep_id
            assert empty.get("disposition_name") is None

        asyncio.run(_with_isolated_company(go))

    def test_already_correct_id_not_rewritten(self):
        async def go(coll, company):
            suffix = uuid.uuid4().hex[:8]
            cb_id = f"test-disp-cb-{suffix}"
            lid_ok = f"test-lead-ok-{suffix}"
            lid_stale = f"test-lead-stale-{suffix}"
            cid_stale = f"test-call-stale-{suffix}"
            stale_id = f"test-stale-{suffix}"
            await coll.dispositions.insert_one(_disp(company, cb_id, "Call Back"))
            await coll.leads.insert_many([
                _lead(
                    company, lid_ok, disp_id=cb_id, disp_name="Call Back",
                    phone="86" + suffix[:8],
                ),
                _lead(
                    company, lid_stale, disp_id=stale_id, disp_name="Call Back",
                    phone="87" + suffix[:8],
                ),
            ])
            await coll.calls.insert_one(_call(
                company, cid_stale, lid_stale, disp_id=stale_id, disp_name="Call Back",
            ))

            before = await coll.leads.find_one(
                {"id": lid_ok}, {"_id": 0, "updated_at": 1, "disposition_id": 1},
            )
            result = await apply_disposition_id_relink()
            assert result["leads_updated"] == 1
            assert result["calls_updated"] == 1

            after = await coll.leads.find_one(
                {"id": lid_ok}, {"_id": 0, "updated_at": 1, "disposition_id": 1},
            )
            stale = await coll.leads.find_one(
                {"id": lid_stale}, {"_id": 0, "disposition_id": 1},
            )
            call = await coll.calls.find_one(
                {"id": cid_stale}, {"_id": 0, "disposition_id": 1},
            )
            assert after["disposition_id"] == cb_id
            assert after["updated_at"] == before["updated_at"]
            assert stale["disposition_id"] == cb_id
            assert call["disposition_id"] == cb_id

        asyncio.run(_with_isolated_company(go))
