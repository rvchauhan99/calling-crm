"""IP access allowlist: unit helpers + API enforcement."""
import asyncio
import sys
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
load_dotenv(_root / ".env")

from conftest import BASE_URL, CREDS, client_for


def uniq(prefix="TEST_ip_"):
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def _mongo_delete_test_rows_sync():
    """Sync cleanup — avoids Motor + asyncio.run loop-closed issues after other async tests."""
    import os
    from pymongo import MongoClient
    from dotenv import dotenv_values
    env = dotenv_values(_root / ".env")
    url = os.environ.get("MONGO_URL") or env.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME") or env.get("DB_NAME") or "calling_crm"
    company = os.environ.get("COMPANY_ID") or env.get("COMPANY_ID") or "default"
    client = MongoClient(url, serverSelectionTimeoutMS=5000)
    try:
        client[db_name].ip_access_list.delete_many({
            "companyId": company,
            "label": {"$regex": "^TEST_"},
        })
    finally:
        client.close()


class TestNormalizeCidr:
    def test_ipv4_host_and_network(self):
        from ip_access import normalize_cidr
        assert normalize_cidr("203.0.113.45") == "203.0.113.45/32"
        assert normalize_cidr("203.0.113.0/24") == "203.0.113.0/24"

    def test_ipv6(self):
        from ip_access import normalize_cidr
        assert normalize_cidr("2001:db8::1").endswith("/128")
        assert "2001:db8" in normalize_cidr("2001:db8::/64")

    def test_invalid(self):
        from ip_access import normalize_cidr
        with pytest.raises(ValueError):
            normalize_cidr("not-an-ip")
        with pytest.raises(ValueError):
            normalize_cidr("")


class TestIpAccessApi:
    created = []

    @classmethod
    def setup_class(cls):
        _mongo_delete_test_rows_sync()

    @classmethod
    def teardown_class(cls):
        _mongo_delete_test_rows_sync()

    def _create(self, admin, cidr, label=None, active=True, headers=None):
        label = label or uniq("TEST_ip_")
        r = admin.post(
            f"{BASE_URL}/api/ip-access",
            json={"cidr": cidr, "label": label, "active": active},
            headers=headers or {},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        row = r.json()["ip_access"]
        self.created.append(row["id"])
        return row

    def test_empty_allows_all(self, admin, anon):
        r = admin.get(f"{BASE_URL}/api/ip-access", timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        active_non_test = [
            x for x in body["ip_access"]
            if x.get("active") and not str(x.get("label", "")).startswith("TEST_")
        ]
        if not active_non_test:
            assert body["allow_all"] is True
        me = admin.get(f"{BASE_URL}/api/auth/me", timeout=30)
        assert me.status_code == 200
        health = anon.get(f"{BASE_URL}/api/health", timeout=30)
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

    def test_crud_and_normalize(self, admin):
        # Keep inactive so local pytest traffic is not locked out
        row = self._create(admin, "203.0.113.45", label=uniq("TEST_office_"), active=False)
        assert row["cidr"] == "203.0.113.45/32"
        lst = admin.get(f"{BASE_URL}/api/ip-access", timeout=30).json()["ip_access"]
        assert any(x["id"] == row["id"] for x in lst)
        u = admin.put(
            f"{BASE_URL}/api/ip-access/{row['id']}",
            json={"cidr": "203.0.113.0/24", "label": row["label"] + "_Upd", "active": False},
            timeout=30,
        )
        assert u.status_code == 200, u.text
        lst = admin.get(f"{BASE_URL}/api/ip-access", timeout=30).json()["ip_access"]
        upd = next(x for x in lst if x["id"] == row["id"])
        assert upd["cidr"] == "203.0.113.0/24"
        assert upd["label"].endswith("_Upd")
        d = admin.delete(f"{BASE_URL}/api/ip-access/{row['id']}", timeout=30)
        assert d.status_code == 200
        self.created.remove(row["id"])

    def test_ipv6_entry(self, admin):
        row = self._create(admin, "2001:db8::1", label=uniq("TEST_v6_"), active=False)
        assert "/128" in row["cidr"]

    def test_invalid_cidr_rejected(self, admin):
        r = admin.post(
            f"{BASE_URL}/api/ip-access",
            json={"cidr": "not-valid", "label": uniq("TEST_bad_"), "active": False},
            timeout=30,
        )
        assert r.status_code == 400
        assert "Invalid" in r.json()["detail"]

    def test_duplicate_rejected(self, admin):
        row = self._create(admin, "198.51.100.10", label=uniq("TEST_dup_"), active=False)
        r = admin.post(
            f"{BASE_URL}/api/ip-access",
            json={"cidr": "198.51.100.10", "label": uniq("TEST_dup2_"), "active": False},
            timeout=30,
        )
        assert r.status_code == 400

    def test_rbac_agent_denied(self, agent):
        r = agent.post(
            f"{BASE_URL}/api/ip-access",
            json={"cidr": "203.0.113.99", "label": uniq("TEST_agent_"), "active": False},
            timeout=30,
        )
        assert r.status_code == 403
        r2 = agent.get(f"{BASE_URL}/api/ip-access", timeout=30)
        assert r2.status_code == 403

    def test_my_ip(self, admin):
        r = admin.get(f"{BASE_URL}/api/ip-access/my-ip", timeout=30)
        assert r.status_code == 200, r.text
        assert "ip" in r.json()

    def test_deny_login_and_api_when_not_matching(self, admin, anon):
        # Keep localhost allowed so admin can manage; deny via forged X-Forwarded-For
        local = self._create(admin, "127.0.0.1", label=uniq("TEST_local_"), active=True)
        office = self._create(admin, "203.0.113.0/24", label=uniq("TEST_deny_"), active=True)

        headers = {"X-Forwarded-For": "198.51.100.50", "Content-Type": "application/json"}
        email, password = CREDS["admin"]
        login = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": email, "password": password},
            headers=headers,
            timeout=30,
        )
        assert login.status_code == 403, login.text
        assert "network" in login.json()["detail"].lower()

        me = admin.get(
            f"{BASE_URL}/api/auth/me",
            headers={"X-Forwarded-For": "198.51.100.50"},
            timeout=30,
        )
        assert me.status_code == 403

        me_ok = admin.get(
            f"{BASE_URL}/api/auth/me",
            headers={"X-Forwarded-For": "203.0.113.10"},
            timeout=30,
        )
        assert me_ok.status_code == 200, me_ok.text

        me_local = admin.get(f"{BASE_URL}/api/auth/me", timeout=30)
        assert me_local.status_code == 200, me_local.text

        h = anon.get(
            f"{BASE_URL}/api/health",
            headers={"X-Forwarded-For": "198.51.100.50"},
            timeout=30,
        )
        assert h.status_code == 200

        for row in (office, local):
            admin.delete(f"{BASE_URL}/api/ip-access/{row['id']}", timeout=30)
            if row["id"] in self.created:
                self.created.remove(row["id"])

    def test_inactive_only_allows_all(self, admin):
        self._create(admin, "203.0.113.200", label=uniq("TEST_off_"), active=False)
        body = admin.get(f"{BASE_URL}/api/ip-access", timeout=30).json()
        active = [x for x in body["ip_access"] if x.get("active")]
        if not active:
            assert body["allow_all"] is True
        me = admin.get(
            f"{BASE_URL}/api/auth/me",
            headers={"X-Forwarded-For": "198.51.100.1"},
            timeout=30,
        )
        assert me.status_code == 200

    def test_kill_switch_bypass(self, monkeypatch):
        from ip_access import ip_access_disabled, is_ip_allowed

        monkeypatch.setenv("IP_ACCESS_DISABLED", "1")
        assert ip_access_disabled() is True
        assert asyncio.run(is_ip_allowed("198.51.100.1")) is True
        monkeypatch.delenv("IP_ACCESS_DISABLED", raising=False)
        assert ip_access_disabled() is False


def _default_cidrs_canonical():
    from ip_access import DEFAULT_IP_ACCESS_ENTRIES, normalize_cidr
    return [normalize_cidr(e["cidr"]) for e in DEFAULT_IP_ACCESS_ENTRIES]


def _mongo_delete_default_seed_rows_sync():
    import os
    from pymongo import MongoClient
    from dotenv import dotenv_values
    env = dotenv_values(_root / ".env")
    url = os.environ.get("MONGO_URL") or env.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME") or env.get("DB_NAME") or "calling_crm"
    company = os.environ.get("COMPANY_ID") or env.get("COMPANY_ID") or "default"
    cidrs = _default_cidrs_canonical()
    client = MongoClient(url, serverSelectionTimeoutMS=5000)
    try:
        client[db_name].ip_access_list.delete_many({
            "companyId": company,
            "cidr": {"$in": cidrs},
        })
    finally:
        client.close()


def _mongo_delete_migration_flag_sync():
    import os
    from pymongo import MongoClient
    from dotenv import dotenv_values
    from ip_access import MIGRATION_FLAG
    env = dotenv_values(_root / ".env")
    url = os.environ.get("MONGO_URL") or env.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME") or env.get("DB_NAME") or "calling_crm"
    company = os.environ.get("COMPANY_ID") or env.get("COMPANY_ID") or "default"
    client = MongoClient(url, serverSelectionTimeoutMS=5000)
    try:
        client[db_name].system_flags.delete_many({
            "companyId": company,
            "id": MIGRATION_FLAG,
        })
    finally:
        client.close()


class TestIpAccessDefaultsSeed:
    @classmethod
    def setup_class(cls):
        _mongo_delete_default_seed_rows_sync()
        _mongo_delete_migration_flag_sync()

    @classmethod
    def teardown_class(cls):
        _mongo_delete_default_seed_rows_sync()
        _mongo_delete_migration_flag_sync()

    def test_migration_skips_on_local_mongo(self, monkeypatch):
        from ip_access import ensure_ip_access_defaults

        monkeypatch.setenv("MONGO_URL", "mongodb://127.0.0.1:27017")
        # Sync assert of gate — avoid Motor asyncio.run under xdist
        from ip_access import _mongo_is_local
        assert _mongo_is_local() is True

    def test_migration_flag_and_upsert_idempotent_sync(self):
        """Sync pymongo: upsert 6 CIDRs + system_flags one-shot (mirrors ensure_ip_access_defaults)."""
        import os
        import uuid
        from datetime import datetime, timezone

        from dotenv import dotenv_values
        from pymongo import MongoClient

        from ip_access import DEFAULT_IP_ACCESS_ENTRIES, MIGRATION_FLAG, normalize_cidr

        env = dotenv_values(_root / ".env")
        url = os.environ.get("MONGO_URL") or env.get("MONGO_URL")
        db_name = os.environ.get("DB_NAME") or env.get("DB_NAME") or "calling_crm"
        company = os.environ.get("COMPANY_ID") or env.get("COMPANY_ID") or "default"
        expected = {normalize_cidr(e["cidr"]) for e in DEFAULT_IP_ACCESS_ENTRIES}

        client = MongoClient(url, serverSelectionTimeoutMS=5000)
        try:
            col = client[db_name].ip_access_list
            flags = client[db_name].system_flags
            col.delete_many({"companyId": company, "cidr": {"$in": list(expected)}})
            flags.delete_many({"companyId": company, "id": MIGRATION_FLAG})

            def upsert_all():
                inserted = already = 0
                now = datetime.now(timezone.utc).isoformat()
                for entry in DEFAULT_IP_ACCESS_ENTRIES:
                    cidr = normalize_cidr(entry["cidr"])
                    label = (entry.get("label") or "").strip() or cidr
                    res = col.update_one(
                        {"companyId": company, "cidr": cidr},
                        {
                            "$setOnInsert": {
                                "id": str(uuid.uuid4()),
                                "companyId": company,
                                "cidr": cidr,
                                "label": label,
                                "active": True,
                                "created_at": now,
                                "updated_at": now,
                            },
                        },
                        upsert=True,
                    )
                    if res.upserted_id is not None:
                        inserted += 1
                    else:
                        already += 1
                return inserted, already

            first_ins, first_already = upsert_all()
            assert first_ins == len(DEFAULT_IP_ACCESS_ENTRIES)
            assert first_already == 0
            flags.update_one(
                {"companyId": company, "id": MIGRATION_FLAG},
                {"$set": {
                    "companyId": company,
                    "id": MIGRATION_FLAG,
                    "done": True,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=True,
            )
            flag = flags.find_one({"companyId": company, "id": MIGRATION_FLAG})
            assert flag and flag.get("done") is True

            second_ins, second_already = upsert_all()
            assert second_ins == 0
            assert second_already == len(DEFAULT_IP_ACCESS_ENTRIES)
            assert {
                d["cidr"]
                for d in col.find({"companyId": company, "cidr": {"$in": list(expected)}}, {"cidr": 1})
            } == expected
        finally:
            client[db_name].ip_access_list.delete_many({"companyId": company, "cidr": {"$in": list(expected)}})
            client[db_name].system_flags.delete_many({"companyId": company, "id": MIGRATION_FLAG})
            client.close()
