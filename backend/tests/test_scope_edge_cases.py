"""Iteration-2 regression probes: affiliate scope, assignable-callers, seed correctness, ledger description."""
import time
from datetime import datetime, timezone

import requests
from conftest import BASE_URL, CREDS


class TestAffiliateScope:
    def test_affiliate_sees_referred_clients(self, affiliate, admin):
        r = affiliate.get(f"{BASE_URL}/api/clients", timeout=60)
        assert r.status_code == 200, r.text
        aff_total = r.json()["total"]
        adm = admin.get(f"{BASE_URL}/api/clients?page_size=500", timeout=60).json()
        referred = [c for c in adm["clients"] if c.get("affiliate_id") == affiliate.user["id"]]
        assert aff_total > 0, "Affiliate sees 0 clients"
        assert aff_total == len(referred), (
            f"Affiliate scope mismatch: sees {aff_total} of {len(referred)} referred clients")

    def test_affiliate_dashboard_non_zero(self, affiliate):
        r = affiliate.get(f"{BASE_URL}/api/dashboard", timeout=60)
        assert r.status_code == 200, r.text
        d = r.json().get("kpis", r.json())
        assert d.get("total_clients", 0) > 0, f"affiliate dashboard total_clients=0: {d}"

    def test_affiliate_report_scoped(self, affiliate):
        r = affiliate.get(f"{BASE_URL}/api/reports/affiliate", timeout=60)
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert len(rows) == 1, f"affiliate should see only own row, got {len(rows)}"
        assert all(x["affiliate_id"] == affiliate.user["id"] for x in rows)

    def test_supervisor_affiliate_report_scope(self, supervisor):
        """Non-admin non-affiliate roles must not see other affiliates' data (403 or empty/own-only)."""
        r = supervisor.get(f"{BASE_URL}/api/reports/affiliate", timeout=60)
        assert r.status_code in (200, 403), r.text
        if r.status_code == 200:
            assert r.json()["rows"] == [], f"supervisor sees affiliate rows: {r.json()['rows']}"

    def test_affiliate_denied_leads_and_ledger(self, affiliate):
        assert affiliate.get(f"{BASE_URL}/api/leads", timeout=30).status_code == 403
        assert affiliate.get(f"{BASE_URL}/api/ledger", timeout=30).status_code == 403
        assert affiliate.get(f"{BASE_URL}/api/today-calls", timeout=30).status_code == 403


class TestAssignableCallers:
    def test_supervisor_assignable_callers(self, supervisor):
        r = supervisor.get(f"{BASE_URL}/api/leads/assignable-callers", timeout=30)
        assert r.status_code == 200, f"supervisor cannot list assignable callers: {r.status_code} {r.text[:200]}"
        data = r.json()
        callers = data if isinstance(data, list) else data.get("callers", data.get("users", []))
        assert len(callers) > 0, f"assignable-callers empty: {data}"
        for c in callers:
            assert "id" in c and ("name" in c or "full_name" in c), c

    def test_admin_assignable_callers(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads/assignable-callers", timeout=30)
        assert r.status_code == 200, r.text

    def test_agent_denied_assignable_callers(self, agent):
        r = agent.get(f"{BASE_URL}/api/leads/assignable-callers", timeout=30)
        assert r.status_code == 403, f"agent (no leads:assign) got {r.status_code}"

    def test_supervisor_assign_flow(self, supervisor):
        callers = supervisor.get(f"{BASE_URL}/api/leads/assignable-callers", timeout=30).json()
        callers = callers if isinstance(callers, list) else callers.get("users", [])
        leads = supervisor.get(f"{BASE_URL}/api/leads?limit=1", timeout=30).json()["leads"]
        assert leads, "supervisor sees no leads"
        lid = leads[0]["id"]
        target = callers[0]["id"]
        r = supervisor.post(f"{BASE_URL}/api/leads/assign",
                            json={"lead_ids": [lid], "agent_id": target}, timeout=30)
        assert r.status_code == 200, f"assign failed: {r.status_code} {r.text[:300]}"
        got = supervisor.get(f"{BASE_URL}/api/leads/{lid}", timeout=30).json()["lead"]
        assert got.get("assigned_to") == target


class TestSeedCorrectness:
    def test_no_future_or_zero_ledger_entries(self, admin):
        r = admin.get(f"{BASE_URL}/api/ledger?limit=1000", timeout=60)
        assert r.status_code == 200, r.text
        entries = r.json().get("entries", r.json().get("items", []))
        assert entries, "no ledger entries returned"
        now = datetime.now(timezone.utc)
        future = []
        zero = []
        for e in entries:
            ts = e.get("created_at") or e.get("entry_date") or e.get("date")
            if ts:
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt > now:
                        future.append(ts)
                except ValueError:
                    pass
            if float(e.get("amount") or 0) == 0:
                zero.append(e.get("id"))
        assert not future, f"future-dated ledger entries: {future[:5]}"
        assert not zero, f"zero-amount ledger entries: {zero[:5]}"

    def test_ledger_entries_have_description(self, admin):
        r = admin.get(f"{BASE_URL}/api/ledger?limit=50", timeout=60)
        entries = r.json().get("entries", r.json().get("items", []))
        assert entries
        assert all("description" in e for e in entries), "ledger entries missing description field"
        assert any((e.get("description") or "").strip() for e in entries), "all descriptions empty"

    def test_converted_leads_are_won(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads?limit=500", timeout=60)
        leads = r.json()["leads"]
        bad = [l["id"] for l in leads
               if l.get("status") == "Converted" and l.get("pipeline_stage") != "Won"]
        assert not bad, f"converted leads not in Won stage: {bad[:5]}"

    def test_clients_have_ftd(self, admin):
        r = admin.get(f"{BASE_URL}/api/clients?limit=100", timeout=60)
        clients = r.json()["clients"]
        assert clients
        missing = [c["id"] for c in clients
                   if not c.get("ftd_at") and not str(c.get("name", "")).startswith("TEST_")]
        assert not missing, f"clients without FTD: {missing[:5]}"


class TestLoginLockout:
    def test_lockout_keyed_on_email_and_resets(self, anon):
        """Bad logins on a throwaway email must not lock a real account."""
        bogus = "TEST_lockout_probe@example.com"
        for _ in range(6):
            anon.post(f"{BASE_URL}/api/auth/login", json={"email": bogus, "password": "wrong"}, timeout=30)
        r = anon.post(f"{BASE_URL}/api/auth/login", json={"email": bogus, "password": "wrong"}, timeout=30)
        assert r.status_code in (423, 429, 401), r.status_code
        # a different (valid) account must still authenticate -> lockout is per-email
        ok = requests.post(f"{BASE_URL}/api/auth/login",
                           json={"email": CREDS["agent"][0], "password": CREDS["agent"][1]}, timeout=30)
        assert ok.status_code == 200, f"lockout leaked across emails: {ok.status_code} {ok.text[:200]}"

    def test_wrong_password_then_correct_after_reset_window(self, anon):
        """Fewer than threshold failures must not block the real login."""
        email = "sneha@callingcrm.com"
        for _ in range(2):
            anon.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": "nope"}, timeout=30)
        time.sleep(0.5)
        r = anon.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": CREDS["agent"][1]}, timeout=30)
        assert r.status_code == 200, f"valid login blocked after 2 failures: {r.status_code} {r.text[:200]}"
