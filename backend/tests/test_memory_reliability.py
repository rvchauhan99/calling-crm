"""Regression: page_size clamp, dashboard aging_sla shape, sheet sync batch counters."""
import uuid

from conftest import BASE_URL


class TestPageSizeClamp:
    def test_leads_page_size_clamped(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads?page_size=5000", timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["page_size"] == 100
        assert len(body["leads"]) <= 100

    def test_clients_page_size_clamped(self, admin):
        r = admin.get(f"{BASE_URL}/api/clients?page_size=9999", timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["page_size"] == 100
        assert len(body["clients"]) <= 100

    def test_call_history_page_size_clamped(self, admin):
        r = admin.get(f"{BASE_URL}/api/call-history?page_size=500", timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["page_size"] == 100
        assert len(body["calls"]) <= 100

    def test_ledger_page_size_clamped(self, admin):
        r = admin.get(f"{BASE_URL}/api/ledger?page_size=500", timeout=120)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["page_size"] == 100
        assert len(body["entries"]) <= 100

    def test_agent_denied_ledger_unchanged(self, agent):
        assert agent.get(f"{BASE_URL}/api/ledger?page_size=1", timeout=30).status_code == 403


class TestDashboardAgingShape:
    def test_aging_sla_buckets(self, admin):
        r = admin.get(f"{BASE_URL}/api/dashboard", timeout=120)
        assert r.status_code == 200, r.text
        aging = r.json().get("aging_sla")
        assert isinstance(aging, list)
        labels = [row["bucket"] for row in aging]
        assert labels == [
            "Overdue follow-ups",
            "No call 3–6 days",
            "No call 7–13 days",
            "No call 14+ days",
        ]
        for row in aging:
            assert isinstance(row["count"], int)
            assert row["count"] >= 0

    def test_pipeline_board_fields(self, admin):
        r = admin.get(f"{BASE_URL}/api/pipeline", timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "stages" in body and "board" in body and "counts" in body
        for stage in body["stages"]:
            for lead in (body["board"].get(stage) or [])[:3]:
                assert "id" in lead and "name" in lead and "phone" in lead


class TestSheetSyncBatch:
    def test_batch_sync_dedupe_via_api(self, admin):
        """Batched sync: existing phone + in-CSV external_id collision → same counters."""
        tag = f"TEST_BatchSync_{uuid.uuid4().hex[:8]}"
        # Create a lead with a known phone first
        phone_raw = "9123456780"
        create_lead = admin.post(
            f"{BASE_URL}/api/leads",
            json={"name": f"{tag}_Existing", "phone": phone_raw},
            timeout=30,
        )
        assert create_lead.status_code == 200, create_lead.text
        existing_id = create_lead.json()["lead"]["id"]

        create = admin.post(
            f"{BASE_URL}/api/sheet-sources",
            json={
                "name": tag,
                "sheet_url": (
                    "https://docs.google.com/spreadsheets/d/"
                    "1aLEV8ZK1RkMaPzsaahfUZQ-zXKHFDSQLirF4Jbx-u0A/edit?gid=0#gid=0"
                ),
                "enabled": False,
                "auto_assign": False,
                "source": "Import",
                "preset": "generic",
                "column_map": {
                    "name": "name",
                    "phone": "phone",
                    "email": "email",
                    "city": "city",
                    "external_id": "id",
                },
                "poll_seconds": 120,
            },
            timeout=30,
        )
        assert create.status_code == 200, create.text
        src_id = create.json()["sheet_source"]["id"]

        # Unique phone for the new row
        phone_b = "9" + "".join(str((uuid.uuid4().int >> (4 * i)) % 10) for i in range(9))
        csv_text = (
            "id,name,phone,email,city\n"
            f"ext1,{tag}_A,{phone_raw},a@x.com,Mumbai\n"
            f"ext2,{tag}_B,{phone_b},b@x.com,Delhi\n"
            f"ext2,{tag}_B2,{phone_b},b2@x.com,Delhi\n"
        )
        sync = admin.post(
            f"{BASE_URL}/api/sheet-sources/{src_id}/sync",
            json={"csv_text": csv_text},
            timeout=60,
        )
        assert sync.status_code == 200, sync.text
        result = sync.json()
        assert result["status"] == "ok", result
        assert result["created"] == 1, result
        assert result["duplicates"] == 2, result

        # Cleanup tagged leads + source
        leads = admin.get(f"{BASE_URL}/api/leads?search={tag}&page_size=100", timeout=30).json()["leads"]
        for l in leads:
            admin.delete(f"{BASE_URL}/api/leads/{l['id']}", timeout=30)
        admin.delete(f"{BASE_URL}/api/leads/{existing_id}", timeout=30)
        admin.delete(f"{BASE_URL}/api/sheet-sources/{src_id}", timeout=30)
