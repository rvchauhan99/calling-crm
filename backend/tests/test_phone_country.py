"""International phone parsing, country filters, and India backfill."""
import asyncio
import uuid

import pytest

from conftest import BASE_URL


def _uid(prefix="TEST_Phone_"):
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def _load_backend():
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def test_parse_india_meta_and_us():
    _load_backend()
    from core import parse_phone

    e164, country = parse_phone("9876543210")
    assert e164 == "+919876543210"
    assert country == "IN"

    e164, country = parse_phone("p:+918847490594")
    assert e164 == "+918847490594"
    assert country == "IN"

    e164, country = parse_phone("+14155552671")
    assert e164 == "+14155552671"
    assert country == "US"

    with pytest.raises(ValueError, match="Invalid phone number"):
        parse_phone("+1")


@pytest.fixture(scope="module", autouse=True)
def _cleanup_phone_leads(admin):
    yield
    for lid in list(TestPhoneCountryFilters.created):
        admin.delete(f"{BASE_URL}/api/leads/{lid}", timeout=30)


class TestPhoneCountryFilters:
    created = []

    def test_create_india_and_us_and_reject_short(self, admin):
        india = admin.post(f"{BASE_URL}/api/leads", json={
            "name": _uid("TEST_IN_"),
            "phone": "9988776655",
            "source": "Manual",
            "email": "",
            "city": "",
        }, timeout=30)
        assert india.status_code == 200, india.text
        lead_in = india.json()["lead"]
        assert lead_in["phone"] == "+919988776655"
        assert lead_in["phone_country"] == "IN"
        self.created.append(lead_in["id"])

        us = admin.post(f"{BASE_URL}/api/leads", json={
            "name": _uid("TEST_US_"),
            "phone": "+14155552671",
            "source": "Manual",
            "email": "",
            "city": "",
        }, timeout=30)
        assert us.status_code == 200, us.text
        lead_us = us.json()["lead"]
        assert lead_us["phone_country"] == "US"
        self.created.append(lead_us["id"])
        TestPhoneCountryFilters.lead_in = lead_in
        TestPhoneCountryFilters.lead_us = lead_us

        bad = admin.post(f"{BASE_URL}/api/leads", json={
            "name": _uid("TEST_BAD_"),
            "phone": "+1",
            "source": "Manual",
        }, timeout=30)
        assert bad.status_code == 400
        assert bad.json()["detail"] == "Invalid phone number."

    def test_leads_filter_and_omit(self, admin):
        us_name = TestPhoneCountryFilters.lead_us["name"]
        only_us = admin.get(
            f"{BASE_URL}/api/leads",
            params={"country": "US", "search": us_name, "page_size": 20},
            timeout=30,
        )
        assert only_us.status_code == 200, only_us.text
        phones = [row["phone_country"] for row in only_us.json()["leads"]]
        assert phones == ["US"]

        both = admin.get(
            f"{BASE_URL}/api/leads",
            params={"search": "TEST_", "page_size": 50},
            timeout=30,
        )
        countries = {row["phone_country"] for row in both.json()["leads"] if row["id"] in (
            TestPhoneCountryFilters.lead_in["id"], TestPhoneCountryFilters.lead_us["id"],
        )}
        assert countries == {"IN", "US"}

        counts = admin.get(f"{BASE_URL}/api/leads/tab-counts", params={"country": "US"}, timeout=30)
        assert counts.status_code == 200
        assert counts.json()["assigned"] + counts.json()["unassigned"] >= 1

    def test_dashboard_caller_affiliate_and_call_history(self, admin):
        dash = admin.get(f"{BASE_URL}/api/dashboard", params={"country": "US"}, timeout=60)
        assert dash.status_code == 200, dash.text
        assert dash.json()["kpis"]["total_leads"] >= 1

        caller = admin.get(f"{BASE_URL}/api/reports/caller", params={"country": "US"}, timeout=60)
        assert caller.status_code == 200, caller.text

        affiliate = admin.get(f"{BASE_URL}/api/reports/affiliate", params={"country": "US"}, timeout=60)
        assert affiliate.status_code == 200, affiliate.text

        logged = admin.post(f"{BASE_URL}/api/calls/log", json={
            "lead_id": TestPhoneCountryFilters.lead_us["id"],
            "disposition_id": _disposition_id(admin),
            "notes": "country filter",
            "duration": 1,
        }, timeout=30)
        assert logged.status_code in (200, 400), logged.text
        if logged.status_code == 200:
            call = logged.json()["call"]
            assert call["lead_phone_country"] == "US"
            hist = admin.get(
                f"{BASE_URL}/api/call-history",
                params={"country": "US", "search": TestPhoneCountryFilters.lead_us["name"]},
                timeout=30,
            )
            assert hist.status_code == 200
            assert any(c["id"] == call["id"] for c in hist.json()["calls"])
            export = admin.get(
                f"{BASE_URL}/api/call-history/export",
                params={"country": "US", "search": TestPhoneCountryFilters.lead_us["name"]},
                timeout=30,
            )
            assert export.status_code == 200
            assert TestPhoneCountryFilters.lead_us["phone"] in export.text

    def test_deny_without_auth(self, anon):
        r = anon.get(f"{BASE_URL}/api/leads", params={"country": "US"}, timeout=30)
        assert r.status_code == 401

    def test_invalid_country_query(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads", params={"country": "USA"}, timeout=30)
        assert r.status_code == 400


def _disposition_id(admin):
    rows = admin.get(f"{BASE_URL}/api/dispositions", timeout=30).json().get("dispositions") or []
    active = [d for d in rows if d.get("active") and not d.get("converts_to_client")]
    return (active or rows)[0]["id"]


def test_backfill_sets_missing_only():
    _load_backend()
    import os
    from dotenv import load_dotenv
    from pathlib import Path
    from motor.motor_asyncio import AsyncIOMotorClient
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    from core import COMPANY_ID, new_id
    import phone_country
    from phone_country import FLAG_ID, ensure_phone_country_india

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    phone_country.db = client[os.environ["DB_NAME"]]

    db = phone_country.db

    async def run():
        await db.system_flags.delete_one({"companyId": COMPANY_ID, "id": FLAG_ID})
        missing_id = new_id()
        us_id = new_id()
        await db.leads.insert_one({
            "id": missing_id, "companyId": COMPANY_ID, "name": "TEST_BF_MISS",
            "phone": "+919876543210", "status": "active",
        })
        await db.leads.insert_one({
            "id": us_id, "companyId": COMPANY_ID, "name": "TEST_BF_US",
            "phone": "+14155552671", "phone_country": "US", "status": "active",
        })
        result = await ensure_phone_country_india()
        assert result["skipped"] is False
        miss = await db.leads.find_one({"id": missing_id}, {"_id": 0, "phone_country": 1})
        kept = await db.leads.find_one({"id": us_id}, {"_id": 0, "phone_country": 1})
        await db.leads.delete_many({"id": {"$in": [missing_id, us_id]}})
        again = await ensure_phone_country_india()
        return miss, kept, again

    try:
        miss, kept, again = asyncio.run(run())
    finally:
        client.close()
    assert miss["phone_country"] == "IN"
    assert kept["phone_country"] == "US"
    assert again["skipped"] is True
