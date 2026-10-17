"""Optional disposition on assign / auto-assign, and leads page size up to 1000."""
import uuid

import pytest
from pymongo import MongoClient

from conftest import BASE_URL


def _uid(prefix="TEST_Asg_"):
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def _mongo():
    from dotenv import dotenv_values
    from pathlib import Path

    env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    client = MongoClient(env["MONGO_URL"])
    return client, client[env["DB_NAME"]]


def _lead(admin, name, phone):
    r = admin.post(
        f"{BASE_URL}/api/leads",
        json={"name": name, "phone": phone, "source": "Manual"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["lead"]


def _disposition(admin, *, converts=False):
    r = admin.post(
        f"{BASE_URL}/api/dispositions",
        json={
            "name": _uid("TEST_AsgDisp_"),
            "slot": 9,
            "type": "non_carry_forward",
            "requires_acw": False,
            "color": "#0EA5E9",
            "default_pipeline_stage": "Contacted",
            "converts_to_client": converts,
        },
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["disposition"]


def _caller_id(admin):
    r = admin.get(f"{BASE_URL}/api/leads/assignable-callers", timeout=30)
    assert r.status_code == 200, r.text
    users = r.json().get("users") or []
    assert users, "no assignable callers"
    return users[0]["id"]


def _stamp(lead_id, disp):
    client, db = _mongo()
    try:
        db.leads.update_one(
            {"id": lead_id},
            {"$set": {
                "disposition_id": disp["id"],
                "disposition_name": disp["name"],
                "follow_up_at": "2099-06-01T10:00:00+00:00",
                "pipeline_stage": "Contacted",
            }},
        )
    finally:
        client.close()


def _hold_other_unassigned(keep_id):
    client, db = _mongo()
    company = db.leads.find_one({"id": keep_id}, {"companyId": 1})["companyId"]
    q = {
        "companyId": company,
        "status": "active",
        "is_client": False,
        "assigned_to": None,
        "id": {"$ne": keep_id},
    }
    ids = [row["id"] for row in db.leads.find(q, {"id": 1})]
    if ids:
        db.leads.update_many({"id": {"$in": ids}}, {"$set": {"assigned_to": "TEST_HOLD_ASSIGN"}})
    return client, db, ids


def _release_hold(client, db, ids):
    try:
        if ids:
            db.leads.update_many(
                {"id": {"$in": ids}, "assigned_to": "TEST_HOLD_ASSIGN"},
                {"$set": {"assigned_to": None}},
            )
    finally:
        client.close()


@pytest.fixture
def created(admin):
    ids = {"leads": [], "dispositions": [], "clients": []}
    yield ids
    for cid in ids["clients"]:
        admin.post(f"{BASE_URL}/api/clients/{cid}/unconvert", timeout=30)
    for lid in ids["leads"]:
        admin.delete(f"{BASE_URL}/api/leads/{lid}", timeout=30)
    for did in ids["dispositions"]:
        admin.delete(f"{BASE_URL}/api/dispositions/{did}", timeout=30)


class TestAssignDisposition:
    def test_assign_without_disposition_keeps_name(self, admin, created):
        disp = _disposition(admin)
        created["dispositions"].append(disp["id"])
        lead = _lead(admin, _uid(), "+12025550191")
        created["leads"].append(lead["id"])
        _stamp(lead["id"], disp)
        agent_id = _caller_id(admin)
        r = admin.post(
            f"{BASE_URL}/api/leads/assign",
            json={"lead_ids": [lead["id"]], "agent_id": agent_id},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        got = admin.get(f"{BASE_URL}/api/leads/{lead['id']}", timeout=30).json()["lead"]
        assert got["disposition_name"] == disp["name"]
        assert got["disposition_id"] == disp["id"]
        assert got["assigned_to"] == agent_id

    def test_assign_fresh_clears_non_client(self, admin, created):
        disp = _disposition(admin)
        created["dispositions"].append(disp["id"])
        lead = _lead(admin, _uid(), "+12025550192")
        created["leads"].append(lead["id"])
        _stamp(lead["id"], disp)
        r = admin.post(
            f"{BASE_URL}/api/leads/assign",
            json={"lead_ids": [lead["id"]], "agent_id": _caller_id(admin), "disposition": "fresh"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        got = admin.get(f"{BASE_URL}/api/leads/{lead['id']}", timeout=30).json()["lead"]
        assert got.get("disposition_name") in (None, "")
        assert got.get("disposition_id") in (None, "")
        assert got.get("follow_up_at") in (None, "")
        assert got["pipeline_stage"] == "New"

    def test_assign_fresh_skips_client(self, admin, created):
        disp = _disposition(admin)
        created["dispositions"].append(disp["id"])
        lead = _lead(admin, _uid(), "+12025550193")
        created["leads"].append(lead["id"])
        _stamp(lead["id"], disp)
        conv = admin.post(f"{BASE_URL}/api/clients/convert", json={"lead_id": lead["id"]}, timeout=30)
        assert conv.status_code == 200, conv.text
        client_id = conv.json().get("client", {}).get("id") or conv.json().get("id")
        if client_id:
            created["clients"].append(client_id)
        before = admin.get(f"{BASE_URL}/api/leads/{lead['id']}", timeout=30).json()["lead"]
        r = admin.post(
            f"{BASE_URL}/api/leads/assign",
            json={"lead_ids": [lead["id"]], "agent_id": _caller_id(admin), "disposition": "fresh"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        got = admin.get(f"{BASE_URL}/api/leads/{lead['id']}", timeout=30).json()["lead"]
        assert got.get("is_client") is True
        assert got.get("pipeline_stage") == before.get("pipeline_stage")
        assert got.get("disposition_name") == before.get("disposition_name")
        assert got.get("disposition_id") == before.get("disposition_id")

    def test_assign_disposition_id_sets_name(self, admin, created):
        keep = _disposition(admin)
        target = _disposition(admin)
        created["dispositions"].extend([keep["id"], target["id"]])
        lead = _lead(admin, _uid(), "+12025550194")
        created["leads"].append(lead["id"])
        _stamp(lead["id"], keep)
        r = admin.post(
            f"{BASE_URL}/api/leads/assign",
            json={
                "lead_ids": [lead["id"]],
                "agent_id": _caller_id(admin),
                "disposition": target["id"],
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text
        got = admin.get(f"{BASE_URL}/api/leads/{lead['id']}", timeout=30).json()["lead"]
        assert got["disposition_id"] == target["id"]
        assert got["disposition_name"] == target["name"]
        assert got["pipeline_stage"] == "Contacted"

    def test_converting_disposition_rejected(self, admin, created):
        disp = _disposition(admin, converts=True)
        created["dispositions"].append(disp["id"])
        lead = _lead(admin, _uid(), "+12025550195")
        created["leads"].append(lead["id"])
        body = {"lead_ids": [lead["id"]], "agent_id": _caller_id(admin), "disposition": disp["id"]}
        r = admin.post(f"{BASE_URL}/api/leads/assign", json=body, timeout=30)
        assert r.status_code == 400, r.text
        assert "converting" in r.text.lower()
        auto = admin.post(
            f"{BASE_URL}/api/leads/auto-assign",
            json={"max_leads": 0, "disposition": disp["id"]},
            timeout=30,
        )
        assert auto.status_code == 400, auto.text

    def test_unknown_disposition_rejected(self, admin, created):
        lead = _lead(admin, _uid(), "+12025550196")
        created["leads"].append(lead["id"])
        r = admin.post(
            f"{BASE_URL}/api/leads/assign",
            json={"lead_ids": [lead["id"]], "agent_id": _caller_id(admin), "disposition": "missing-id"},
            timeout=30,
        )
        assert r.status_code == 400, r.text

    def test_auto_assign_writes_disposition_name(self, admin, created):
        disp = _disposition(admin)
        created["dispositions"].append(disp["id"])
        lead = _lead(admin, _uid(), "+12025550197")
        created["leads"].append(lead["id"])
        agent_id = _caller_id(admin)
        client, db, held = _hold_other_unassigned(lead["id"])
        from datetime import datetime, timezone
        user = db.users.find_one({"id": agent_id}, {"daily_quota": 1})
        previous_quota = (user or {}).get("daily_quota")
        today = datetime.now(timezone.utc).date().isoformat()
        assigned_today = db.leads.count_documents({"assigned_to": agent_id, "assigned_date": today})
        db.users.update_one({"id": agent_id}, {"$set": {"daily_quota": assigned_today + 5}})
        try:
            r = admin.post(
                f"{BASE_URL}/api/leads/auto-assign",
                json={
                    "allocations": [{"agent_id": agent_id, "count": 1}],
                    "disposition": disp["id"],
                },
                timeout=60,
            )
            assert r.status_code == 200, r.text
            assert r.json()["assigned"] == 1
            got = admin.get(f"{BASE_URL}/api/leads/{lead['id']}", timeout=30).json()["lead"]
            assert got["disposition_name"] == disp["name"]
            assert got["disposition_id"] == disp["id"]
            assert got["assigned_to"] == agent_id
        finally:
            if previous_quota is None:
                db.users.update_one({"id": agent_id}, {"$unset": {"daily_quota": ""}})
            else:
                db.users.update_one({"id": agent_id}, {"$set": {"daily_quota": previous_quota}})
            _release_hold(client, db, held)

    def test_anon_assign_is_401(self, admin, created):
        import requests
        lead = _lead(admin, _uid(), "+12025550198")
        created["leads"].append(lead["id"])
        r = requests.post(
            f"{BASE_URL}/api/leads/assign",
            json={"lead_ids": [lead["id"]], "agent_id": "x"},
            timeout=30,
        )
        assert r.status_code == 401

    def test_leads_page_size_500_and_clamp_1000(self, admin):
        mid = admin.get(f"{BASE_URL}/api/leads", params={"page_size": 500, "page": 1}, timeout=60)
        assert mid.status_code == 200, mid.text
        assert mid.json()["page_size"] == 500
        assert len(mid.json()["leads"]) <= 500
        high = admin.get(f"{BASE_URL}/api/leads", params={"page_size": 2000, "page": 1}, timeout=60)
        assert high.status_code == 200, high.text
        assert high.json()["page_size"] == 1000
        assert len(high.json()["leads"]) <= 1000

    def test_assign_batch_over_1000_rejected(self, admin):
        r = admin.post(
            f"{BASE_URL}/api/leads/assign",
            json={"lead_ids": [f"id-{i}" for i in range(1001)], "agent_id": "x"},
            timeout=30,
        )
        assert r.status_code == 422
