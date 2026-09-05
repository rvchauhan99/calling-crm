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
