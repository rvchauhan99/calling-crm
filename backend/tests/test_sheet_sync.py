"""Sheet Sources: inspect, column map, sync with fixtures."""
import uuid

import pytest

from conftest import BASE_URL, client_for

SAMPLE_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1aLEV8ZK1RkMaPzsaahfUZQ-zXKHFDSQLirF4Jbx-u0A/edit?gid=0#gid=0"
)

META_CSV = """id,full_name,phone_number,email,campaign_name
l:maptest001,Map Meta One,p:+919876543201,one@example.com,bax
l:maptest002,Map Meta Two,p:+919876543202,two@example.com,bax
"""

CUSTOM_CSV = """lead_key,Customer Name,WhatsApp,mail
ext-c1,Custom Lead A,9876543210,a@example.com
ext-c2,Custom Lead B,9876543211,b@example.com
"""

EMPTY_NAME_CSV = """id,full_name,phone_number
l:x,,p:+919876543299
"""


def uniq(p="TEST_Sheet_"):
    return f"{p}{uuid.uuid4().hex[:8]}"


class TestSheetColumnMapping:
    sources = []
    leads = []

    def test_parse_and_suggest_unit(self):
        import sys
        from pathlib import Path
        from dotenv import load_dotenv
        root = Path(__file__).resolve().parents[1]
        load_dotenv(root / ".env")
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from sheet_sync import parse_sheet_url, suggest_column_map, validate_column_map

        sid, gid = parse_sheet_url(SAMPLE_URL)
        assert sid == "1aLEV8ZK1RkMaPzsaahfUZQ-zXKHFDSQLirF4Jbx-u0A"
        assert gid == "0"

        suggested = suggest_column_map(
            ["id", "full_name", "phone_number", "email"], "meta_lead_ads"
        )
        assert suggested["name"] == "full_name"
        assert suggested["phone"] == "phone_number"
        assert suggested["external_id"] == "id"

        custom = suggest_column_map(
            ["customer name", "whatsapp", "mail", "lead_key"], "generic"
        )
        assert custom["name"] == "customer name"
        assert custom["phone"] == "whatsapp"
        assert custom["email"] == "mail"
        assert custom["external_id"] == "lead_key"

        with pytest.raises(ValueError):
            validate_column_map({"name": "", "phone": "phone"})

    def test_sheet_csv_row_cap(self):
        import sys
        from pathlib import Path
        from dotenv import load_dotenv
        root = Path(__file__).resolve().parents[1]
        load_dotenv(root / ".env")
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from sheet_sync import parse_csv_rows, SheetParseError

        header = "name,phone\n"
        # 6 data rows with max_rows=5 must fail
        body = header + "".join(f"Lead {i},900000000{i}\n" for i in range(6))
        with pytest.raises(SheetParseError, match="more than 5"):
            parse_csv_rows(body, max_rows=5)
        ok_headers, ok_rows = parse_csv_rows(header + "A,9111111111\nB,9222222222\n", max_rows=5)
        assert ok_headers == ["name", "phone"]
        assert len(ok_rows) == 2

    def test_inspect_with_inline_csv(self, admin):
        r = admin.post(
            f"{BASE_URL}/api/sheet-sources/inspect",
            json={
                "sheet_url": SAMPLE_URL,
                "preset": "meta_lead_ads",
                "csv_text": META_CSV,
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "full_name" in body["headers"]
        assert body["suggested_map"]["name"] == "full_name"
        assert body["suggested_map"]["phone"] == "phone_number"

    def test_inspect_invalid_url(self, admin):
        r = admin.post(
            f"{BASE_URL}/api/sheet-sources/inspect",
            json={"sheet_url": "https://example.com/not-a-sheet", "csv_text": "a,b\n1,2"},
            timeout=30,
        )
        assert r.status_code == 400

    def test_inspect_rbac_agent_denied(self, agent):
        r = agent.post(
            f"{BASE_URL}/api/sheet-sources/inspect",
            json={"sheet_url": SAMPLE_URL, "csv_text": META_CSV},
            timeout=30,
        )
        assert r.status_code == 403

    def test_create_requires_name_phone_map(self, admin):
        r = admin.post(
            f"{BASE_URL}/api/sheet-sources",
            json={
                "name": uniq(),
                "sheet_url": SAMPLE_URL,
                "column_map": {"name": "", "phone": "phone_number", "email": "", "city": "", "external_id": ""},
            },
            timeout=30,
        )
        assert r.status_code == 400
        assert "Name" in (r.json().get("detail") or "")

    def test_custom_map_sync_creates_leads(self, admin):
        name = uniq()
        create = admin.post(
            f"{BASE_URL}/api/sheet-sources",
            json={
                "name": name,
                "sheet_url": SAMPLE_URL,
                "enabled": False,
                "auto_assign": False,
                "source": "Import",
                "preset": "generic",
                "column_map": {
                    "name": "Customer Name",
                    "phone": "WhatsApp",
                    "email": "mail",
                    "city": "",
                    "external_id": "lead_key",
                },
                "poll_seconds": 120,
            },
            timeout=30,
        )
        assert create.status_code == 200, create.text
        src = create.json()["sheet_source"]
        TestSheetColumnMapping.sources.append(src["id"])
        assert src["column_map"]["name"] == "customer name"
        assert src["column_map"]["phone"] == "whatsapp"

        sync = admin.post(
            f"{BASE_URL}/api/sheet-sources/{src['id']}/sync",
            json={"csv_text": CUSTOM_CSV},
            timeout=60,
        )
        assert sync.status_code == 200, sync.text
        result = sync.json()
        assert result["status"] == "ok"
        assert result["created"] == 2
        assert result["assigned"] == 0

        leads = admin.get(
            f"{BASE_URL}/api/leads?search=Custom+Lead&page_size=50",
            timeout=30,
        ).json()["leads"]
        matched = [l for l in leads if l.get("sheet_source_id") == src["id"]]
        assert len(matched) >= 2
        for l in matched:
            TestSheetColumnMapping.leads.append(l["id"])
            assert l["assigned_to"] is None
            assert l["source"] == "Import"
            assert l.get("external_id") in ("ext-c1", "ext-c2")

        # Dedup second sync
        sync2 = admin.post(
            f"{BASE_URL}/api/sheet-sources/{src['id']}/sync",
            json={"csv_text": CUSTOM_CSV},
            timeout=60,
        )
        assert sync2.status_code == 200
        assert sync2.json()["duplicates"] == 2
        assert sync2.json()["created"] == 0

    def test_preview_draft_custom_map(self, admin):
        r = admin.post(
            f"{BASE_URL}/api/sheet-sources/preview-draft",
            json={
                "sheet_url": SAMPLE_URL,
                "preset": "generic",
                "column_map": {
                    "name": "Customer Name",
                    "phone": "WhatsApp",
                    "email": "mail",
                    "city": "",
                    "external_id": "lead_key",
                },
                "csv_text": CUSTOM_CSV,
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text
        rows = r.json()["rows"]
        assert len(rows) >= 1
        assert rows[0]["name"] == "Custom Lead A"
        assert rows[0]["phone"].startswith("+91")

    def test_meta_sync_unassigned(self, admin):
        name = uniq("TEST_MetaMap_")
        create = admin.post(
            f"{BASE_URL}/api/sheet-sources",
            json={
                "name": name,
                "sheet_url": SAMPLE_URL,
                "enabled": False,
                "auto_assign": False,
                "source": "Facebook Ads",
                "preset": "meta_lead_ads",
                "poll_seconds": 120,
            },
            timeout=30,
        )
        assert create.status_code == 200, create.text
        src = create.json()["sheet_source"]
        TestSheetColumnMapping.sources.append(src["id"])
        assert src["column_map"]["name"] == "full_name"

        sync = admin.post(
            f"{BASE_URL}/api/sheet-sources/{src['id']}/sync",
            json={"csv_text": META_CSV},
            timeout=60,
        )
        assert sync.status_code == 200, sync.text
        assert sync.json()["created"] == 2
        leads = admin.get(
            f"{BASE_URL}/api/leads?search=Map+Meta&page_size=50",
            timeout=30,
        ).json()["leads"]
        matched = [l for l in leads if l.get("sheet_source_id") == src["id"]]
        assert len(matched) == 2
        for l in matched:
            TestSheetColumnMapping.leads.append(l["id"])
            assert l["assigned_to"] is None
            assert l["source"] == "Facebook Ads"
            assert l.get("external_id", "").startswith("l:maptest")

    def test_agent_cannot_create_sheet_source(self, agent):
        r = agent.post(
            f"{BASE_URL}/api/sheet-sources",
            json={"name": "x", "sheet_url": SAMPLE_URL},
            timeout=30,
        )
        assert r.status_code == 403

    @classmethod
    def teardown_class(cls):
        c = client_for("admin")
        for lid in cls.leads:
            c.delete(f"{BASE_URL}/api/leads/{lid}", timeout=30)
        for sid in cls.sources:
            c.delete(f"{BASE_URL}/api/sheet-sources/{sid}", timeout=30)


class TestSheetSyncSingleFlight:
    """Company-wide lock, fair pick, and manual 409 while busy."""

    source_ids = []

    def _mongo_env(self):
        import os
        import sys
        from pathlib import Path
        from dotenv import dotenv_values, load_dotenv

        backend_dir = Path(__file__).resolve().parents[1]
        load_dotenv(backend_dir / ".env")
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))
        env = dotenv_values(backend_dir / ".env")
        mongo = os.environ.get("MONGO_URL") or env.get("MONGO_URL")
        dbname = os.environ.get("DB_NAME") or env.get("DB_NAME")
        company = os.environ.get("COMPANY_ID") or env.get("COMPANY_ID") or "default"
        assert "localhost" in (mongo or "") or "127.0.0.1" in (mongo or "")
        return mongo, dbname, company

    def test_pick_next_due_oldest_first(self):
        import asyncio
        import uuid
        from datetime import datetime, timedelta, timezone
        from motor.motor_asyncio import AsyncIOMotorClient

        mongo, dbname, company = self._mongo_env()
        tag = uuid.uuid4().hex[:8]
        ids = [f"TEST_pick_{tag}_{i}" for i in range(3)]
        now = datetime.now(timezone.utc)

        async def go():
            import sheet_sync
            mc = AsyncIOMotorClient(mongo)
            test_db = mc[dbname]
            sheet_sync.db = test_db
            # Disable other enabled sources so pick only sees our fixtures
            await test_db.sheet_sources.update_many(
                {"companyId": company, "enabled": True},
                {"$set": {"_test_was_enabled": True, "enabled": False}},
            )
            try:
                docs = [
                    {
                        "id": ids[0],
                        "companyId": company,
                        "name": f"TEST_pick_old_{tag}",
                        "enabled": True,
                        "poll_seconds": 60,
                        "last_synced_at": (now - timedelta(hours=3)).isoformat(),
                        "syncing": False,
                        "spreadsheet_id": "x",
                        "gid": "0",
                    },
                    {
                        "id": ids[1],
                        "companyId": company,
                        "name": f"TEST_pick_never_{tag}",
                        "enabled": True,
                        "poll_seconds": 60,
                        "last_synced_at": None,
                        "syncing": False,
                        "spreadsheet_id": "x",
                        "gid": "0",
                    },
                    {
                        "id": ids[2],
                        "companyId": company,
                        "name": f"TEST_pick_recent_{tag}",
                        "enabled": True,
                        "poll_seconds": 60,
                        "last_synced_at": (now - timedelta(hours=1)).isoformat(),
                        "syncing": False,
                        "spreadsheet_id": "x",
                        "gid": "0",
                    },
                ]
                await test_db.sheet_sources.insert_many(docs)
                TestSheetSyncSingleFlight.source_ids.extend(ids)

                first = await sheet_sync.pick_next_due_source()
                assert first is not None
                assert first["id"] == ids[1], "never-synced should win (nulls first)"

                await test_db.sheet_sources.update_one(
                    {"id": ids[1]},
                    {"$set": {"last_synced_at": now.isoformat()}},
                )
                second = await sheet_sync.pick_next_due_source()
                assert second is not None
                assert second["id"] == ids[0], "oldest last_synced_at next"

                await test_db.sheet_sources.update_one(
                    {"id": ids[0]},
                    {"$set": {"last_synced_at": now.isoformat()}},
                )
                await test_db.sheet_sources.update_one(
                    {"id": ids[2]},
                    {"$set": {
                        "last_synced_at": (now - timedelta(seconds=30)).isoformat(),
                        "poll_seconds": 3600,
                    }},
                )
                none_due = await sheet_sync.pick_next_due_source()
                assert none_due is None
            finally:
                await test_db.sheet_sources.delete_many({"id": {"$in": ids}})
                await test_db.sheet_sources.update_many(
                    {"companyId": company, "_test_was_enabled": True},
                    {"$set": {"enabled": True}, "$unset": {"_test_was_enabled": ""}},
                )
                mc.close()

        asyncio.run(go())

    def test_company_lock_single_flight(self):
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient

        mongo, dbname, company = self._mongo_env()

        async def go():
            import sheet_sync
            mc = AsyncIOMotorClient(mongo)
            sheet_sync.db = mc[dbname]
            await sheet_sync.db.sheet_sync_locks.delete_one({"companyId": company})
            try:
                ok1 = await sheet_sync.acquire_company_sync_lock(holder="test-a", source_id="s1")
                assert ok1 is True
                assert await sheet_sync.company_sync_is_busy() is True
                ok2 = await sheet_sync.acquire_company_sync_lock(holder="test-b", source_id="s2")
                assert ok2 is False
                await sheet_sync.release_company_sync_lock(holder="test-a")
                assert await sheet_sync.company_sync_is_busy() is False
                ok3 = await sheet_sync.acquire_company_sync_lock(holder="test-b", source_id="s2")
                assert ok3 is True
                await sheet_sync.release_company_sync_lock(holder="test-b")
            finally:
                await sheet_sync.db.sheet_sync_locks.delete_one({"companyId": company})
                mc.close()

        asyncio.run(go())

    def test_manual_sync_409_when_company_busy(self, admin):
        from datetime import datetime, timedelta, timezone
        from pymongo import MongoClient

        name = uniq("TEST_Busy_")
        create = admin.post(
            f"{BASE_URL}/api/sheet-sources",
            json={
                "name": name,
                "sheet_url": SAMPLE_URL,
                "enabled": False,
                "auto_assign": False,
                "source": "Import",
                "preset": "generic",
                "column_map": {
                    "name": "Customer Name",
                    "phone": "WhatsApp",
                    "email": "mail",
                    "city": "",
                    "external_id": "lead_key",
                },
                "poll_seconds": 120,
            },
            timeout=30,
        )
        assert create.status_code == 200, create.text
        src = create.json()["sheet_source"]
        TestSheetSyncSingleFlight.source_ids.append(src["id"])

        mongo, dbname, company = self._mongo_env()
        until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        mc = MongoClient(mongo)
        try:
            mc[dbname].sheet_sync_locks.update_one(
                {"companyId": company},
                {"$set": {
                    "companyId": company,
                    "locked": True,
                    "locked_until": until,
                    "holder": "test-hold-409",
                    "source_id": "other",
                }},
                upsert=True,
            )
            sync = admin.post(
                f"{BASE_URL}/api/sheet-sources/{src['id']}/sync",
                json={"csv_text": CUSTOM_CSV},
                timeout=30,
            )
            assert sync.status_code == 409, sync.text
            detail = sync.json().get("detail") or ""
            assert "sync" in detail.lower() or "running" in detail.lower()
        finally:
            mc[dbname].sheet_sync_locks.delete_one({"companyId": company})
            mc.close()
            admin.delete(f"{BASE_URL}/api/sheet-sources/{src['id']}", timeout=30)
            if src["id"] in TestSheetSyncSingleFlight.source_ids:
                TestSheetSyncSingleFlight.source_ids.remove(src["id"])

    def test_run_sync_busy_status_without_second_fetch(self):
        """Second concurrent run_sync_with_company_lock returns busy (no double sync)."""
        import asyncio
        import uuid
        from unittest.mock import AsyncMock, patch
        from motor.motor_asyncio import AsyncIOMotorClient

        mongo, dbname, company = self._mongo_env()
        sid = f"TEST_sf_{uuid.uuid4().hex[:8]}"

        async def go():
            import sheet_sync
            mc = AsyncIOMotorClient(mongo)
            sheet_sync.db = mc[dbname]
            await sheet_sync.db.sheet_sync_locks.delete_one({"companyId": company})
            source = {
                "id": sid,
                "companyId": company,
                "name": "TEST_single_flight",
                "spreadsheet_id": "x",
                "gid": "0",
                "enabled": False,
                "column_map": {"name": "name", "phone": "phone"},
            }
            try:
                ok = await sheet_sync.acquire_company_sync_lock(holder="holder-1", source_id=sid)
                assert ok is True
                with patch(
                    "sheet_sync.sync_source",
                    new_callable=AsyncMock,
                ) as mock_sync:
                    result = await sheet_sync.run_sync_with_company_lock(
                        source, holder="holder-2", csv_text="name,phone\nA,1\n",
                    )
                    assert result["status"] == "busy"
                    mock_sync.assert_not_called()
            finally:
                await sheet_sync.release_company_sync_lock(holder="holder-1")
                await sheet_sync.db.sheet_sync_locks.delete_one({"companyId": company})
                mc.close()

        asyncio.run(go())

    @classmethod
    def teardown_class(cls):
        c = client_for("admin")
        for sid in list(cls.source_ids):
            c.delete(f"{BASE_URL}/api/sheet-sources/{sid}", timeout=30)
        try:
            from pathlib import Path
            import os
            from dotenv import dotenv_values, load_dotenv
            from pymongo import MongoClient

            backend_dir = Path(__file__).resolve().parents[1]
            load_dotenv(backend_dir / ".env")
            env = dotenv_values(backend_dir / ".env")
            mongo = os.environ.get("MONGO_URL") or env.get("MONGO_URL")
            dbname = os.environ.get("DB_NAME") or env.get("DB_NAME")
            company = os.environ.get("COMPANY_ID") or env.get("COMPANY_ID") or "default"
            mc = MongoClient(mongo)
            mc[dbname].sheet_sources.delete_many({"id": {"$in": cls.source_ids}})
            mc[dbname].sheet_sync_locks.delete_one({"companyId": company})
            # Restore any sources left disabled by a failed pick test
            mc[dbname].sheet_sources.update_many(
                {"companyId": company, "_test_was_enabled": True},
                {"$set": {"enabled": True}, "$unset": {"_test_was_enabled": ""}},
            )
            mc.close()
        except Exception:
            pass
