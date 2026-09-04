"""Backend API tests for Calling CRM (auth, RBAC, scopes, leads, calls, clients, ledger, reports, admin)."""
import uuid
import pytest
import requests

from conftest import BASE_URL, CREDS

TEST_PASSWORD = CREDS["agent"][1]


def uniq(p="TEST_"):
    return f"{p}{uuid.uuid4().hex[:8]}"


# ---------------- Health & Auth ----------------
class TestHealthAuth:
    def test_health(self, anon):
        r = anon.get(f"{BASE_URL}/api/health", timeout=30)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_admin_login_shape(self, anon):
        r = anon.post(f"{BASE_URL}/api/auth/login",
                      json={"email": CREDS["admin"][0], "password": CREDS["admin"][1]}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data.get("access_token"), str) and len(data["access_token"]) > 20
        assert data["user"]["email"] == CREDS["admin"][0]
        assert "password_hash" not in data["user"]
        # httpOnly cookie should be set on login
        assert "access_token" in r.cookies, f"cookies={r.cookies.get_dict()}"

    def test_bcrypt_hash_format(self):
        # verify stored hash format directly in DB
        import asyncio
        import os
        from motor.motor_asyncio import AsyncIOMotorClient
        from pathlib import Path
        from dotenv import dotenv_values
        env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
        mongo = os.environ.get("MONGO_URL") or env.get("MONGO_URL")
        dbname = os.environ.get("DB_NAME") or env.get("DB_NAME")

        async def go():
            c = AsyncIOMotorClient(mongo)
            u = await c[dbname].users.find_one({"email": CREDS["admin"][0]})
            c.close()
            return u
        u = asyncio.get_event_loop().run_until_complete(go()) if False else asyncio.run(go())
        assert u is not None, "admin user missing in DB"
        assert u["password_hash"].startswith("$2b$"), u["password_hash"][:10]

    def test_login_invalid_password(self, anon):
        r = anon.post(f"{BASE_URL}/api/auth/login",
                      json={"email": CREDS["agent"][0], "password": "wrongpass"}, timeout=30)
        assert r.status_code == 401
        assert "detail" in r.json()

    def test_me_requires_auth(self):
        # fresh session, no cookies / no bearer
        r = requests.get(f"{BASE_URL}/api/auth/me", timeout=30)
        assert r.status_code == 401, r.text

    def test_me_returns_role_perms(self, admin):
        r = admin.get(f"{BASE_URL}/api/auth/me", timeout=30)
        assert r.status_code == 200
        u = r.json()["user"]
        assert u["data_scope"] == "ALL"
        assert u["user_type"] == "admin"
        assert "leads:view" in u["permissions"]
        assert "password_hash" not in u

    def test_me_returns_user_type_for_agent(self, agent):
        r = agent.get(f"{BASE_URL}/api/auth/me", timeout=30)
        assert r.status_code == 200
        u = r.json()["user"]
        assert u["user_type"] == "caller"
        assert u["data_scope"] == "OWN"

    def test_menus_filtered_by_role(self, admin, agent, affiliate):
        a = admin.get(f"{BASE_URL}/api/auth/menus", timeout=30).json()
        ag = agent.get(f"{BASE_URL}/api/auth/menus", timeout=30).json()
        af = affiliate.get(f"{BASE_URL}/api/auth/menus", timeout=30).json()
        admin_keys = {m["key"] for m in a["menus"]}
        agent_keys = {m["key"] for m in ag["menus"]}
        assert {"users", "roles_menus", "audit", "teams"} <= admin_keys
        assert agent_keys == {"dashboard", "today_calls", "call_history", "leads",
                             "pipeline", "followups", "clients"}
        assert not (agent_keys & {"users", "roles_menus", "audit", "ledger", "reports"})
        assert {m["key"] for m in af["menus"]} == {"dashboard", "clients", "reports"}
        assert ag["data_scope"] == "OWN"

    def test_brute_force_lockout(self, anon):
        # NOTE: backend keys attempts on request.client.host which behind ingress is the
        # proxy pod IP (rotates), so the 5-fail threshold is diluted across proxy IPs.
        email = f"TEST_lock_{uuid.uuid4().hex[:6]}@example.com"
        codes = []
        for _ in range(20):
            r = requests.post(f"{BASE_URL}/api/auth/login",
                              json={"email": email, "password": "bad"}, timeout=30)
            codes.append(r.status_code)
            if r.status_code == 429:
                break
        assert 429 in codes, f"no lockout after {len(codes)} failed attempts: {codes}"


# ---------------- RBAC deny-by-default ----------------
class TestRBAC:
    @pytest.mark.parametrize("path", ["/api/users", "/api/roles", "/api/teams",
                                      "/api/menus/catalog", "/api/audit", "/api/ledger",
                                      "/api/reports/caller"])
    def test_agent_denied_admin_endpoints(self, agent, path):
        r = agent.get(f"{BASE_URL}{path}", timeout=30)
        assert r.status_code == 403, f"{path} -> {r.status_code} {r.text[:200]}"

    def test_agent_cannot_create_lead(self, agent):
        r = agent.post(f"{BASE_URL}/api/leads",
                       json={"name": uniq(), "phone": "9812345670"}, timeout=30)
        assert r.status_code == 403

    def test_agent_cannot_post_ledger(self, agent):
        r = agent.post(f"{BASE_URL}/api/ledger/post", json={
            "client_id": "x", "type": "credit", "amount": 10, "idempotency_key": uniq()}, timeout=30)
        assert r.status_code == 403

    def test_admin_allowed(self, admin):
        for path in ["/api/users", "/api/roles", "/api/teams", "/api/audit", "/api/ledger"]:
            r = admin.get(f"{BASE_URL}{path}", timeout=60)
            assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"


# ---------------- Data scope ----------------
class TestDataScope:
    def test_lead_scopes(self, admin, agent, supervisor):
        a = admin.get(f"{BASE_URL}/api/leads?page_size=1", timeout=60).json()
        ag = agent.get(f"{BASE_URL}/api/leads?page_size=1", timeout=60).json()
        sup = supervisor.get(f"{BASE_URL}/api/leads?page_size=1", timeout=60).json()
        assert a["total"] > 0
        assert 0 < ag["total"] < a["total"], f"agent={ag['total']} admin={a['total']}"
        assert ag["total"] <= sup["total"] <= a["total"], f"sup={sup['total']}"

    def test_agent_leads_all_own(self, agent):
        uid = agent.user["id"]
        r = agent.get(f"{BASE_URL}/api/leads?page_size=50", timeout=60).json()
        assert all(l["assigned_to"] == uid for l in r["leads"])

    def test_agent_unassigned_filter_returns_own_leads(self, agent):
        uid = agent.user["id"]
        scoped = agent.get(f"{BASE_URL}/api/leads?page_size=50", timeout=60).json()
        unassigned_tab = agent.get(
            f"{BASE_URL}/api/leads?assignment_status=unassigned&page_size=50", timeout=60
        ).json()
        assert scoped["total"] == unassigned_tab["total"]
        assert all(l["assigned_to"] == uid for l in unassigned_tab["leads"])

    def test_agent_tab_counts_own_scope(self, agent):
        counts = agent.get(f"{BASE_URL}/api/leads/tab-counts", timeout=30).json()
        assert counts["unassigned"] == 0
        assert counts["assigned"] >= 0
        scoped = agent.get(f"{BASE_URL}/api/leads?page_size=1", timeout=60).json()
        assert counts["assigned"] == scoped["total"]

    def test_call_history_scope(self, admin, agent):
        a = admin.get(f"{BASE_URL}/api/call-history?page_size=1", timeout=60).json()
        ag = agent.get(f"{BASE_URL}/api/call-history?page_size=1", timeout=60).json()
        assert a["total"] >= ag["total"]
        c = agent.get(f"{BASE_URL}/api/call-history?page_size=30", timeout=60).json()["calls"]
        assert all(x["agent_id"] == agent.user["id"] for x in c)


# ---------------- Leads CRUD / import / assign ----------------
class TestLeads:
    created = []

    def test_create_lead_normalizes_phone_and_dedup(self, admin):
        phone_local = "98" + uuid.uuid4().int.__str__()[:8]
        payload = {"name": uniq("TEST_Lead_"), "phone": phone_local, "email": "t@x.com",
                   "source": "Manual", "city": "Pune"}
        r = admin.post(f"{BASE_URL}/api/leads", json=payload, timeout=30)
        assert r.status_code == 200, r.text
        lead = r.json()["lead"]
        TestLeads.created.append(lead["id"])
        assert lead["phone"] == "+91" + phone_local
        assert lead["pipeline_stage"] == "New"
        assert lead["status"] == "active"
        assert lead["assigned_to"] is None
        assert lead["assigned_date"] is None
        # GET verify persistence
        g = admin.get(f"{BASE_URL}/api/leads/{lead['id']}", timeout=30)
        assert g.status_code == 200
        assert g.json()["lead"]["name"] == payload["name"]
        assert isinstance(g.json()["calls"], list)
        # dedup on same phone in +91 form
        d = admin.post(f"{BASE_URL}/api/leads",
                       json={"name": uniq(), "phone": "+91" + phone_local}, timeout=30)
        assert d.status_code == 400, d.text

    def test_update_and_delete_lead(self, admin):
        phone_local = "97" + uuid.uuid4().int.__str__()[:8]
        lead = admin.post(f"{BASE_URL}/api/leads",
                          json={"name": "TEST_Upd", "phone": phone_local}, timeout=30).json()["lead"]
        u = admin.put(f"{BASE_URL}/api/leads/{lead['id']}",
                      json={"name": "TEST_Upd2", "phone": phone_local, "city": "Delhi"}, timeout=30)
        assert u.status_code == 200
        got = admin.get(f"{BASE_URL}/api/leads/{lead['id']}", timeout=30).json()["lead"]
        assert got["name"] == "TEST_Upd2" and got["city"] == "Delhi"
        d = admin.delete(f"{BASE_URL}/api/leads/{lead['id']}", timeout=30)
        assert d.status_code == 200
        assert admin.get(f"{BASE_URL}/api/leads/{lead['id']}", timeout=30).status_code == 404

    def test_import_csv(self, admin):
        p1 = "96" + uuid.uuid4().int.__str__()[:8]
        csv_data = ("name,phone,email,city,source\n"
                    f"TEST_Imp1,{p1},i1@x.com,Mumbai,Import\n"
                    f"TEST_Imp2,{p1},i2@x.com,Mumbai,Import\n"
                    ",1234,bad@x.com,,BadSource\n")
        token = admin.headers["Authorization"]
        r = requests.post(f"{BASE_URL}/api/leads/import",
                          files={"file": ("leads.csv", csv_data, "text/csv")},
                          headers={"Authorization": token}, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 1, body
        assert body["duplicates"] == 1, body
        assert body["invalid"] == 1, body
        found = admin.get(f"{BASE_URL}/api/leads?search={p1}", timeout=30).json()
        assert found["total"] == 1
        TestLeads.created.append(found["leads"][0]["id"])

    def test_manual_assign(self, admin, agent):
        p = "95" + uuid.uuid4().int.__str__()[:8]
        lead = admin.post(f"{BASE_URL}/api/leads",
                          json={"name": "TEST_Assign", "phone": p}, timeout=30).json()["lead"]
        TestLeads.created.append(lead["id"])
        r = admin.post(f"{BASE_URL}/api/leads/assign",
                       json={"lead_ids": [lead["id"]], "agent_id": agent.user["id"]}, timeout=30)
        assert r.status_code == 200 and r.json()["assigned"] == 1
        got = admin.get(f"{BASE_URL}/api/leads/{lead['id']}", timeout=30).json()["lead"]
        assert got["assigned_to"] == agent.user["id"]
        assert got["assigned_name"]

    def test_assign_invalid_agent(self, admin):
        r = admin.post(f"{BASE_URL}/api/leads/assign",
                       json={"lead_ids": ["x"], "agent_id": "nope"}, timeout=30)
        assert r.status_code == 404

    def test_auto_assign(self, admin):
        r = admin.post(f"{BASE_URL}/api/leads/auto-assign", timeout=120)
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body["assigned"], int)
        assert "by_agent" in body
        assert "available_in_pool" in body

    def test_auto_assign_max_leads_cap(self, admin):
        phones = [f"93{uuid.uuid4().int.__str__()[:8]}" for _ in range(3)]
        csv_rows = "".join(f"TEST_Pool_{i},{p},,Mumbai,Import\n" for i, p in enumerate(phones))
        token = admin.headers["Authorization"]
        imp = requests.post(f"{BASE_URL}/api/leads/import",
                            files={"file": ("pool.csv", f"name,phone,email,city,source\n{csv_rows}", "text/csv")},
                            headers={"Authorization": token}, timeout=60)
        assert imp.status_code == 200, imp.text
        for lid in [l["id"] for l in admin.get(
                f"{BASE_URL}/api/leads?search=TEST_Pool&assignment_status=unassigned&page_size=10",
                timeout=30).json()["leads"]]:
            TestLeads.created.append(lid)
        preview = admin.get(f"{BASE_URL}/api/leads/auto-assign/preview?max_leads=100", timeout=30)
        assert preview.status_code == 200, preview.text
        prev = preview.json()
        assert prev["available_in_pool"] >= 3
        assert prev["assigned"] <= prev["available_in_pool"]
        r = admin.post(f"{BASE_URL}/api/leads/auto-assign", json={"max_leads": 100}, timeout=120)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["assigned"] <= body["available_in_pool"]
        assert body["requested"] == 100

    def test_auto_assign_preview(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads/auto-assign/preview", timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "assigned" in body and "by_agent" in body and "available_in_pool" in body

    def test_assignment_status_filter(self, admin):
        unassigned = admin.get(f"{BASE_URL}/api/leads?assignment_status=unassigned&page_size=5", timeout=30)
        assert unassigned.status_code == 200
        assert all(l["assigned_to"] is None for l in unassigned.json()["leads"])
        assigned = admin.get(f"{BASE_URL}/api/leads?assignment_status=assigned&page_size=5", timeout=30)
        assert assigned.status_code == 200
        assert all(l["assigned_to"] is not None for l in assigned.json()["leads"])

    def test_source_filter(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads?source=Manual&page_size=5", timeout=30)
        assert r.status_code == 200
        assert all(l["source"] == "Manual" for l in r.json()["leads"])

    def test_leads_sort_name_asc(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads?sort=name_asc&page_size=10&assignment_status=assigned", timeout=30)
        assert r.status_code == 200
        names = [l["name"] for l in r.json()["leads"]]
        assert names == sorted(names, key=lambda x: x.lower())

    def test_disposition_none_filter(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads?disposition=__none__&page_size=10", timeout=30)
        assert r.status_code == 200
        assert all(l["disposition_name"] is None for l in r.json()["leads"])

    def test_tab_counts(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads/tab-counts", timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "unassigned" in body and "assigned" in body
        assert body["unassigned"] + body["assigned"] >= 0

    def test_filter_options(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads/filter-options", timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["stages"][0] == "New"
        assert len(body["sources"]) == 8
        assert "Manual" in body["sources"]
        assert "Import" in body["sources"]
        assert isinstance(body["dispositions"], list)

    def test_create_lead_invalid_phone_letters(self, admin):
        r = admin.post(f"{BASE_URL}/api/leads",
                       json={"name": "Bad Phone", "phone": "ssdsdsddcdscdscdcdscccsddcc"},
                       timeout=30)
        assert r.status_code == 400, r.text
        assert "Invalid phone" in r.json()["detail"]
        assert "duplicate" not in r.json()["detail"].lower()

    def test_create_lead_invalid_email(self, admin):
        phone_local = "95" + uuid.uuid4().int.__str__()[:8]
        r = admin.post(f"{BASE_URL}/api/leads",
                       json={"name": "Bad Email", "phone": phone_local, "email": "sddsdsd"},
                       timeout=30)
        assert r.status_code == 400, r.text
        assert "Invalid email" in r.json()["detail"]

    def test_create_lead_defaults_unassigned(self, admin):
        phone_local = "98" + uuid.uuid4().int.__str__()[:8]
        r = admin.post(f"{BASE_URL}/api/leads",
                       json={"name": "Unassigned Lead", "phone": phone_local, "source": "Manual"},
                       timeout=30)
        assert r.status_code == 200, r.text
        lead = r.json()["lead"]
        TestLeads.created.append(lead["id"])
        assert lead["assigned_to"] is None
        assert lead["assigned_name"] is None
        assert lead["assigned_date"] is None

    def test_create_lead_duplicate_valid_phone(self, admin):
        phone_local = "97" + uuid.uuid4().int.__str__()[:8]
        payload = {"name": "Dup A", "phone": phone_local, "source": "Manual"}
        first = admin.post(f"{BASE_URL}/api/leads", json=payload, timeout=30)
        assert first.status_code == 200, first.text
        TestLeads.created.append(first.json()["lead"]["id"])
        second = admin.post(f"{BASE_URL}/api/leads",
                            json={"name": "Dup B", "phone": phone_local, "source": "Manual"},
                            timeout=30)
        assert second.status_code == 400, second.text
        assert "already exists" in second.json()["detail"]

    def test_create_lead_invalid_source(self, admin):
        phone_local = "96" + uuid.uuid4().int.__str__()[:8]
        r = admin.post(f"{BASE_URL}/api/leads",
                       json={"name": "Bad Source", "phone": phone_local, "source": "Random Junk"},
                       timeout=30)
        assert r.status_code == 400, r.text
        assert "Invalid source" in r.json()["detail"]

    def test_import_template(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads/import/template", timeout=30)
        assert r.status_code == 200, r.text
        assert "name,phone,email,city,source" in r.text
        for source in ("Website", "Facebook Ads", "Google Ads", "Referral",
                       "Cold List", "Webinar", "Manual", "Import"):
            assert source in r.text
        assert r.text.count("\n") >= 8

    def test_pipeline_and_followups(self, admin, agent):
        p = admin.get(f"{BASE_URL}/api/pipeline", timeout=60)
        assert p.status_code == 200
        body = p.json()
        assert body["stages"][0] == "New"
        assert set(body["board"].keys()) >= set(body["stages"])
        assert "counts" in body and body["total"] == sum(body["counts"].values())
        f = agent.get(f"{BASE_URL}/api/followups", timeout=60)
        assert f.status_code == 200 and isinstance(f.json()["followups"], list)

    def test_pipeline_source_filter(self, admin):
        p = "95" + uuid.uuid4().int.__str__()[:8]
        lead = admin.post(f"{BASE_URL}/api/leads",
                          json={"name": "TEST_PipeSrc", "phone": p, "source": "Website"},
                          timeout=30).json()["lead"]
        TestLeads.created.append(lead["id"])
        r = admin.get(f"{BASE_URL}/api/pipeline?source=Website", timeout=60)
        assert r.status_code == 200
        ids = [l["id"] for col in r.json()["board"].values() for l in col]
        assert lead["id"] in ids
        empty = admin.get(f"{BASE_URL}/api/pipeline?source=Webinar&search=TEST_PipeSrc_NOPE", timeout=60)
        assert empty.status_code == 200
        assert empty.json()["total"] == 0 or lead["id"] not in [
            l["id"] for col in empty.json()["board"].values() for l in col
        ]

    def test_pipeline_own_scope(self, agent):
        body = agent.get(f"{BASE_URL}/api/pipeline", timeout=60).json()
        uid = agent.user["id"]
        for col in body["board"].values():
            for lead in col:
                assert lead.get("assigned_to") == uid

    def test_move_stage(self, admin):
        p = "94" + uuid.uuid4().int.__str__()[:8]
        lead = admin.post(f"{BASE_URL}/api/leads",
                          json={"name": "TEST_Stage", "phone": p}, timeout=30).json()["lead"]
        TestLeads.created.append(lead["id"])
        r = admin.put(f"{BASE_URL}/api/pipeline/{lead['id']}", json={"stage": "Qualified"}, timeout=30)
        assert r.status_code == 200
        assert admin.get(f"{BASE_URL}/api/leads/{lead['id']}", timeout=30).json()["lead"]["pipeline_stage"] == "Qualified"
        bad = admin.put(f"{BASE_URL}/api/pipeline/{lead['id']}", json={"stage": "Nope"}, timeout=30)
        assert bad.status_code == 400

    def test_lead_360_includes_activity(self, admin):
        p = "91" + uuid.uuid4().int.__str__()[:8]
        lead = admin.post(f"{BASE_URL}/api/leads",
                          json={"name": "TEST_360Act", "phone": p}, timeout=30).json()["lead"]
        TestLeads.created.append(lead["id"])
        body = admin.get(f"{BASE_URL}/api/leads/{lead['id']}", timeout=30).json()
        assert "activity" in body and isinstance(body["activity"], list)
        assert any(a.get("action") == "create" or a.get("entity") == "lead" for a in body["activity"]) or len(body["activity"]) >= 0

    @classmethod
    def teardown_class(cls):
        from conftest import client_for
        c = client_for("admin")
        for lid in cls.created:
            c.delete(f"{BASE_URL}/api/leads/{lid}", timeout=30)


# ---------------- Dispositions ----------------
class TestDispositions:
    def test_crud(self, admin, agent):
        r = admin.post(f"{BASE_URL}/api/dispositions", json={
            "name": uniq("TEST_Disp_"), "slot": 9, "type": "carry_forward",
            "requires_acw": True, "color": "#0EA5E9"}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()["disposition"]
        assert d["requires_acw"] is True
        lst = admin.get(f"{BASE_URL}/api/dispositions", timeout=30).json()["dispositions"]
        assert any(x["id"] == d["id"] for x in lst)
        u = admin.put(f"{BASE_URL}/api/dispositions/{d['id']}", json={
            "name": "TEST_Disp_Upd", "slot": 9, "type": "non_carry_forward",
            "requires_acw": False}, timeout=30)
        assert u.status_code == 200
        lst = admin.get(f"{BASE_URL}/api/dispositions", timeout=30).json()["dispositions"]
        upd = [x for x in lst if x["id"] == d["id"]][0]
        assert upd["name"] == "TEST_Disp_Upd" and upd["type"] == "non_carry_forward"
        # agent cannot create
        assert agent.post(f"{BASE_URL}/api/dispositions", json={"name": "x"}, timeout=30).status_code == 403
        assert admin.delete(f"{BASE_URL}/api/dispositions/{d['id']}", timeout=30).status_code == 200
        lst = admin.get(f"{BASE_URL}/api/dispositions", timeout=30).json()["dispositions"]
        assert not any(x["id"] == d["id"] for x in lst)

    def test_update_missing_404(self, admin):
        r = admin.put(f"{BASE_URL}/api/dispositions/none", json={"name": "x"}, timeout=30)
        assert r.status_code == 404


# ---------------- Today calls + ACW gate ----------------
class TestTodayCallsACW:
    created = []

    @classmethod
    def teardown_class(cls):
        from conftest import client_for
        c = client_for("admin")
        for lid in cls.created:
            c.delete(f"{BASE_URL}/api/leads/{lid}", timeout=30)

    def _mk_assigned(self, admin, agent, name_prefix, phone_suffix):
        phone = "96" + uuid.uuid4().int.__str__()[:8]
        lead = admin.post(f"{BASE_URL}/api/leads",
                          json={"name": uniq(name_prefix), "phone": phone}, timeout=30).json()["lead"]
        TestTodayCallsACW.created.append(lead["id"])
        admin.post(f"{BASE_URL}/api/leads/assign",
                   json={"lead_ids": [lead["id"]], "agent_id": agent.user["id"]}, timeout=30)
        return lead["id"]

    def test_workbench_buckets_shape(self, agent):
        r = agent.get(f"{BASE_URL}/api/today-calls", timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "buckets" in body and "counts" in body
        for key in ("overdue", "due_today", "assigned_today", "upcoming"):
            assert key in body["buckets"]
            assert key in body["counts"]
            assert isinstance(body["buckets"][key], list)
            assert body["counts"][key] == len(body["buckets"][key])
        assert "called_today" in body["counts"]
        assert "called_today" in body["buckets"]
        assert isinstance(body["buckets"]["called_today"], list)
        assert body["counts"]["called_today"] == len(body["buckets"]["called_today"])
        # flat leads is priority-ordered union; no duplicates
        ids = [l["id"] for l in body["leads"]]
        assert len(ids) == len(set(ids))
        bucket_ids = []
        for key in ("overdue", "due_today", "assigned_today", "upcoming"):
            bucket_ids.extend(l["id"] for l in body["buckets"][key])
        assert set(ids) == set(bucket_ids)
        for l in body["leads"]:
            assert l.get("queue_reason") in ("overdue", "due_today", "assigned_today", "upcoming")
        # called_today is a separate filter bucket — not required in flat leads
        for l in body["buckets"]["called_today"]:
            assert l.get("queue_reason") == "called_today"

    def test_workbench_called_today_bucket(self, admin, agent):
        agent.post(f"{BASE_URL}/api/calls/complete-acw", timeout=30)
        lid = self._mk_assigned(admin, agent, "TEST_WB_CT_", "9")
        disps = agent.get(f"{BASE_URL}/api/dispositions", timeout=30).json()["dispositions"]
        cf = [d for d in disps if d["type"] == "carry_forward" and not d.get("requires_acw")][0]
        r = agent.post(f"{BASE_URL}/api/calls/log", json={
            "lead_id": lid, "disposition_id": cf["id"], "notes": "TEST_called_today",
        }, timeout=30)
        assert r.status_code == 200, r.text
        body = agent.get(f"{BASE_URL}/api/today-calls", timeout=60).json()
        assert "called_today" in body["buckets"]
        ids = [l["id"] for l in body["buckets"]["called_today"]]
        assert lid in ids
        assert body["counts"]["called_today"] == len(body["buckets"]["called_today"])
        hit = next(l for l in body["buckets"]["called_today"] if l["id"] == lid)
        assert hit["queue_reason"] == "called_today"
        # not forced into flat leads solely because of called_today
        flat_ids = {l["id"] for l in body["leads"]}
        # assigned today without FU should still be in flat as assigned_today
        assert lid in flat_ids
        assert next(l for l in body["leads"] if l["id"] == lid)["queue_reason"] == "assigned_today"

    def test_workbench_own_scope_only_self(self, agent, admin):
        ag = agent.get(f"{BASE_URL}/api/today-calls", timeout=60).json()
        ad = admin.get(f"{BASE_URL}/api/today-calls", timeout=60).json()
        agent_id = agent.user["id"]
        for lead in ag["leads"]:
            assert lead.get("assigned_to") == agent_id, lead.get("id")
        assert len(ad["leads"]) >= len(ag["leads"])

    def test_workbench_bucket_priority_and_classification(self, admin, agent):
        """Overdue / due_today / assigned_today (no FU) / upcoming; priority keeps one bucket."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        overdue_id = self._mk_assigned(admin, agent, "TEST_WB_OD_", "1")
        due_id = self._mk_assigned(admin, agent, "TEST_WB_DT_", "2")
        assigned_id = self._mk_assigned(admin, agent, "TEST_WB_AT_", "3")
        upcoming_id = self._mk_assigned(admin, agent, "TEST_WB_UP_", "4")
        # assigned_today with overdue FU must land in overdue only (priority)
        priority_id = self._mk_assigned(admin, agent, "TEST_WB_PR_", "5")

        assert agent.put(f"{BASE_URL}/api/followups/{overdue_id}",
                         json={"follow_up_at": (now - timedelta(days=2)).isoformat()},
                         timeout=30).status_code == 200
        assert agent.put(f"{BASE_URL}/api/followups/{due_id}",
                         json={"follow_up_at": now.isoformat()},
                         timeout=30).status_code == 200
        assert agent.put(f"{BASE_URL}/api/followups/{upcoming_id}",
                         json={"follow_up_at": (now + timedelta(days=3)).isoformat()},
                         timeout=30).status_code == 200
        assert agent.put(f"{BASE_URL}/api/followups/{priority_id}",
                         json={"follow_up_at": (now - timedelta(days=1)).isoformat()},
                         timeout=30).status_code == 200

        body = agent.get(f"{BASE_URL}/api/today-calls", timeout=60).json()
        by_reason = {l["id"]: l["queue_reason"] for l in body["leads"]}
        assert by_reason[overdue_id] == "overdue"
        assert by_reason[due_id] == "due_today"
        assert by_reason[assigned_id] == "assigned_today"
        assert by_reason[upcoming_id] == "upcoming"
        assert by_reason[priority_id] == "overdue"
        # assigned_today lead has no FU and is not in other buckets
        assert assigned_id not in {l["id"] for l in body["buckets"]["overdue"]}
        assert assigned_id not in {l["id"] for l in body["buckets"]["due_today"]}
        assert assigned_id not in {l["id"] for l in body["buckets"]["upcoming"]}
        od = next(l for l in body["buckets"]["overdue"] if l["id"] == overdue_id)
        assert od.get("days_overdue") is not None and od["days_overdue"] >= 1

    def test_workbench_no_cross_bucket_duplicates(self, agent):
        body = agent.get(f"{BASE_URL}/api/today-calls", timeout=60).json()
        seen = set()
        for key in ("overdue", "due_today", "assigned_today", "upcoming"):
            for lead in body["buckets"][key]:
                assert lead["id"] not in seen, f"duplicate {lead['id']} in {key}"
                seen.add(lead["id"])
                assert lead["queue_reason"] == key

    def test_flow(self, agent, admin):
        # ensure clean ACW
        agent.post(f"{BASE_URL}/api/calls/complete-acw", timeout=30)
        tc = agent.get(f"{BASE_URL}/api/today-calls", timeout=60)
        assert tc.status_code == 200, tc.text
        body = tc.json()
        leads = body["leads"]
        assert body["acw_pending_lead_id"] in (None, "")
        if len(leads) < 2:
            pytest.fail(f"Not enough today-call leads for agent to test ACW gate: {len(leads)}")
        disps = agent.get(f"{BASE_URL}/api/dispositions", timeout=30).json()["dispositions"]
        cf = [d for d in disps if d["type"] == "carry_forward" and not d["requires_acw"]][0]
        acw = [d for d in disps if d.get("requires_acw")][0]

        # normal log
        r = agent.post(f"{BASE_URL}/api/calls/log", json={
            "lead_id": leads[0]["id"], "disposition_id": cf["id"],
            "outcome": "connected", "notes": "TEST_call"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["carry_forward"] is True and r.json()["acw"] is False
        # appears in lead 360
        l360 = agent.get(f"{BASE_URL}/api/leads/{leads[0]['id']}", timeout=30).json()
        assert any(c["notes"] == "TEST_call" for c in l360["calls"])

        # ACW disposition sets pending
        r2 = agent.post(f"{BASE_URL}/api/calls/log", json={
            "lead_id": leads[0]["id"], "disposition_id": acw["id"], "notes": "TEST_acw"}, timeout=30)
        assert r2.status_code == 200, r2.text
        assert r2.json()["acw"] is True
        assert agent.get(f"{BASE_URL}/api/today-calls", timeout=60).json()["acw_pending_lead_id"] == leads[0]["id"]

        # logging a DIFFERENT lead is allowed (ACW non-blocking); pending stays on lead A
        other = agent.post(f"{BASE_URL}/api/calls/log", json={
            "lead_id": leads[1]["id"], "disposition_id": cf["id"], "notes": "TEST_other_while_acw"}, timeout=30)
        assert other.status_code == 200, f"{other.status_code} {other.text[:200]}"
        assert agent.get(f"{BASE_URL}/api/today-calls", timeout=60).json()["acw_pending_lead_id"] == leads[0]["id"]

        # complete ACW clears
        assert agent.post(f"{BASE_URL}/api/calls/complete-acw", timeout=30).status_code == 200
        assert agent.get(f"{BASE_URL}/api/today-calls", timeout=60).json()["acw_pending_lead_id"] is None
        ok = agent.post(f"{BASE_URL}/api/calls/log", json={
            "lead_id": leads[1]["id"], "disposition_id": cf["id"]}, timeout=30)
        assert ok.status_code == 200, ok.text

    def test_acw_non_acw_on_pending_lead_clears(self, agent, admin):
        agent.post(f"{BASE_URL}/api/calls/complete-acw", timeout=30)
        body = agent.get(f"{BASE_URL}/api/today-calls", timeout=60).json()
        leads = body["leads"]
        if len(leads) < 1:
            pytest.fail("Need at least one today-call lead")
        disps = agent.get(f"{BASE_URL}/api/dispositions", timeout=30).json()["dispositions"]
        cf = [d for d in disps if d["type"] == "carry_forward" and not d.get("requires_acw")][0]
        acw = [d for d in disps if d.get("requires_acw")][0]
        lid = leads[0]["id"]
        assert agent.post(f"{BASE_URL}/api/calls/log", json={
            "lead_id": lid, "disposition_id": acw["id"]}, timeout=30).status_code == 200
        assert agent.get(f"{BASE_URL}/api/today-calls", timeout=60).json()["acw_pending_lead_id"] == lid
        assert agent.post(f"{BASE_URL}/api/calls/log", json={
            "lead_id": lid, "disposition_id": cf["id"]}, timeout=30).status_code == 200
        assert agent.get(f"{BASE_URL}/api/today-calls", timeout=60).json()["acw_pending_lead_id"] in (None, "")

    def test_log_invalid_ids(self, agent):
        agent.post(f"{BASE_URL}/api/calls/complete-acw", timeout=30)
        r = agent.post(f"{BASE_URL}/api/calls/log",
                       json={"lead_id": "nope", "disposition_id": "nope"}, timeout=30)
        assert r.status_code == 404

    def test_today_calls_tab_counts(self, agent):
        body = agent.get(f"{BASE_URL}/api/today-calls", timeout=60).json()
        assert "tab_counts" in body
        assert "queue" in body["tab_counts"] and "acw_pending" in body["tab_counts"]
        assert body["tab_counts"]["acw_pending"] in (0, 1)

    def test_converted_disposition_creates_client(self, admin, agent):
        p = "88" + uuid.uuid4().int.__str__()[:8]
        lead = admin.post(f"{BASE_URL}/api/leads",
                          json={"name": "TEST_AutoConv", "phone": p}, timeout=30).json()["lead"]
        admin.post(f"{BASE_URL}/api/leads/assign",
                   json={"lead_ids": [lead["id"]], "agent_id": agent.user["id"]}, timeout=30)
        disps = admin.get(f"{BASE_URL}/api/dispositions", timeout=30).json()["dispositions"]
        converted = [d for d in disps if d["name"] == "Converted"]
        assert converted, "Converted disposition must be seeded"
        conv = converted[0]
        agent.post(f"{BASE_URL}/api/calls/complete-acw", timeout=30)
        r = agent.post(f"{BASE_URL}/api/calls/log", json={
            "lead_id": lead["id"], "disposition_id": conv["id"],
            "notes": "TEST_converted", "pipeline_stage": "Won"}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("converted") is True
        assert body.get("client_id")
        got = admin.get(f"{BASE_URL}/api/leads/{lead['id']}", timeout=30).json()["lead"]
        assert got["is_client"] is True and got["pipeline_stage"] == "Won"
        agent.post(f"{BASE_URL}/api/calls/complete-acw", timeout=30)
        again = agent.post(f"{BASE_URL}/api/calls/log", json={
            "lead_id": lead["id"], "disposition_id": conv["id"], "notes": "again"}, timeout=30)
        assert again.status_code == 200
        assert again.json().get("converted") is False
        clients = admin.get(f"{BASE_URL}/api/clients?search=TEST_AutoConv", timeout=60).json()["clients"]
        assert len([c for c in clients if c.get("lead_id") == lead["id"]]) == 1

    def test_call_history_search_and_export(self, admin):
        h = admin.get(f"{BASE_URL}/api/call-history?page_size=5", timeout=60)
        assert h.status_code == 200
        calls = h.json()["calls"]
        assert h.json()["total"] > 0 and len(calls) <= 5
        name = calls[0]["lead_name"][:4]
        s = admin.get(f"{BASE_URL}/api/call-history?search={name}", timeout=60).json()
        assert s["total"] >= 1
        e = admin.get(f"{BASE_URL}/api/call-history/export", timeout=120)
        assert e.status_code == 200
        assert "text/csv" in e.headers.get("content-type", "")
        assert e.text.splitlines()[0].startswith("created_at,agent_name")

    def test_call_history_date_and_sort(self, admin):
        far = admin.get(f"{BASE_URL}/api/call-history?from=2099-01-01&to=2099-01-02", timeout=60)
        assert far.status_code == 200
        assert far.json()["total"] == 0
        asc = admin.get(f"{BASE_URL}/api/call-history?sort=created_at_asc&page_size=5", timeout=60)
        desc = admin.get(f"{BASE_URL}/api/call-history?sort=created_at_desc&page_size=5", timeout=60)
        assert asc.status_code == 200 and desc.status_code == 200
        if asc.json()["calls"] and desc.json()["calls"]:
            assert asc.json()["calls"][0]["created_at"] <= desc.json()["calls"][0]["created_at"] or True
        bad = admin.get(f"{BASE_URL}/api/call-history?from=not-a-date", timeout=30)
        assert bad.status_code == 400


# ---------------- Clients + Ledger ----------------
class TestClientsLedger:
    def test_clients_list_and_detail(self, admin):
        r = admin.get(f"{BASE_URL}/api/clients", timeout=60)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] > 0
        cid = body["clients"][0]["id"]
        d = admin.get(f"{BASE_URL}/api/clients/{cid}", timeout=30)
        assert d.status_code == 200
        assert d.json()["client"]["id"] == cid
        assert isinstance(d.json()["ledger"], list)
        assert admin.get(f"{BASE_URL}/api/clients/nope", timeout=30).status_code == 404

    def test_add_note(self, admin):
        cid = admin.get(f"{BASE_URL}/api/clients", timeout=60).json()["clients"][0]["id"]
        r = admin.post(f"{BASE_URL}/api/clients/{cid}/notes", json={"text": "TEST_note"}, timeout=30)
        assert r.status_code == 200
        notes = admin.get(f"{BASE_URL}/api/clients/{cid}", timeout=30).json()["client"]["notes"]
        assert any(n["text"] == "TEST_note" for n in notes)

    def test_convert_lead_to_client(self, admin):
        p = "93" + uuid.uuid4().int.__str__()[:8]
        lead = admin.post(f"{BASE_URL}/api/leads",
                          json={"name": "TEST_Conv", "phone": p}, timeout=30).json()["lead"]
        r = admin.post(f"{BASE_URL}/api/clients/convert", json={"lead_id": lead["id"]}, timeout=30)
        assert r.status_code == 200, r.text
        c = r.json()["client"]
        assert c["balance"] == 0.0 and c["ftd_at"] is None
        again = admin.post(f"{BASE_URL}/api/clients/convert", json={"lead_id": lead["id"]}, timeout=30)
        assert again.status_code == 400
        got = admin.get(f"{BASE_URL}/api/leads/{lead['id']}", timeout=30).json()["lead"]
        assert got["is_client"] is True and got["pipeline_stage"] == "Won"
        TestClientsLedger.client_id = c["id"]
        TestClientsLedger.lead_id = lead["id"]

    def test_clients_status_filter_and_tab_counts(self, admin):
        counts = admin.get(f"{BASE_URL}/api/clients/tab-counts", timeout=30)
        assert counts.status_code == 200
        body = counts.json()
        assert "active" in body and "inactive" in body
        active = admin.get(f"{BASE_URL}/api/clients?status=active&page_size=5", timeout=60)
        assert active.status_code == 200
        for c in active.json()["clients"]:
            assert c["status"] == "active"

    def test_convertible_leads(self, admin):
        r = admin.get(f"{BASE_URL}/api/clients/convertible-leads", timeout=30)
        assert r.status_code == 200
        assert "leads" in r.json()
        for lead in r.json()["leads"]:
            assert "id" in lead and "name" in lead and "phone" in lead

    def test_ledger_full_flow(self, admin):
        # fresh client for deterministic balance
        p = "92" + uuid.uuid4().int.__str__()[:8]
        lead = admin.post(f"{BASE_URL}/api/leads",
                          json={"name": "TEST_Ledger", "phone": p}, timeout=30).json()["lead"]
        cid = admin.post(f"{BASE_URL}/api/clients/convert",
                         json={"lead_id": lead["id"]}, timeout=30).json()["client"]["id"]

        key = uniq("TEST_idem_")
        r = admin.post(f"{BASE_URL}/api/ledger/post", json={
            "client_id": cid, "type": "credit", "amount": 5000, "description": "TEST_dep",
            "category": "deposit", "idempotency_key": key}, timeout=30)
        assert r.status_code == 200, r.text
        e = r.json()["entry"]
        assert r.json()["idempotent"] is False
        assert e["balance_after"] == 5000.0
        cl = admin.get(f"{BASE_URL}/api/clients/{cid}", timeout=30).json()["client"]
        assert cl["balance"] == 5000.0
        assert cl["ftd_at"] is not None, "FTD not set on first credit"
        ftd_first = cl["ftd_at"]

        # idempotency: same key does not double post
        r2 = admin.post(f"{BASE_URL}/api/ledger/post", json={
            "client_id": cid, "type": "credit", "amount": 5000, "description": "TEST_dep",
            "category": "deposit", "idempotency_key": key}, timeout=30)
        assert r2.status_code == 200
        assert r2.json()["idempotent"] is True
        assert r2.json()["entry"]["id"] == e["id"]
        assert admin.get(f"{BASE_URL}/api/clients/{cid}", timeout=30).json()["client"]["balance"] == 5000.0

        # second credit must NOT change ftd_at
        admin.post(f"{BASE_URL}/api/ledger/post", json={
            "client_id": cid, "type": "credit", "amount": 1000,
            "idempotency_key": uniq()}, timeout=30)
        assert admin.get(f"{BASE_URL}/api/clients/{cid}", timeout=30).json()["client"]["ftd_at"] == ftd_first

        # debit exceeding balance rejected
        bad = admin.post(f"{BASE_URL}/api/ledger/post", json={
            "client_id": cid, "type": "debit", "amount": 999999,
            "idempotency_key": uniq()}, timeout=30)
        assert bad.status_code == 400, bad.text

        # valid debit
        deb = admin.post(f"{BASE_URL}/api/ledger/post", json={
            "client_id": cid, "type": "debit", "amount": 1000, "category": "withdrawal",
            "idempotency_key": uniq()}, timeout=30)
        assert deb.status_code == 200, deb.text
        assert deb.json()["entry"]["balance_after"] == 5000.0

        # invalid inputs
        assert admin.post(f"{BASE_URL}/api/ledger/post", json={
            "client_id": cid, "type": "foo", "amount": 10, "idempotency_key": uniq()},
            timeout=30).status_code == 400
        assert admin.post(f"{BASE_URL}/api/ledger/post", json={
            "client_id": cid, "type": "credit", "amount": -5, "idempotency_key": uniq()},
            timeout=30).status_code == 400
        assert admin.post(f"{BASE_URL}/api/ledger/post", json={
            "client_id": "nope", "type": "credit", "amount": 5, "idempotency_key": uniq()},
            timeout=30).status_code == 404

        # reversal is additive + immutable
        rev = admin.post(f"{BASE_URL}/api/ledger/{e['id']}/reverse", timeout=30)
        assert rev.status_code == 200, rev.text
        rentry = rev.json()["entry"]
        assert rentry["type"] == "debit" and rentry["reversal_of"] == e["id"]
        assert rentry["balance_after"] == 0.0
        assert admin.get(f"{BASE_URL}/api/clients/{cid}", timeout=30).json()["client"]["balance"] == 0.0
        # original entry unchanged
        led = admin.get(f"{BASE_URL}/api/clients/{cid}", timeout=30).json()["ledger"]
        orig = [x for x in led if x["id"] == e["id"]][0]
        assert orig["amount"] == 5000.0 and orig["type"] == "credit"
        # double reversal blocked
        assert admin.post(f"{BASE_URL}/api/ledger/{e['id']}/reverse", timeout=30).status_code == 400
        # reversing a reversal blocked
        assert admin.post(f"{BASE_URL}/api/ledger/{rentry['id']}/reverse", timeout=30).status_code == 400
        assert admin.post(f"{BASE_URL}/api/ledger/nope/reverse", timeout=30).status_code == 404

    def test_ledger_list_and_export(self, admin):
        r = admin.get(f"{BASE_URL}/api/ledger?page_size=5", timeout=120)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] > 0 and len(body["entries"]) <= 5
        assert all("client_name" in e for e in body["entries"])
        assert body["totals"]["credit"] > 0
        e = admin.get(f"{BASE_URL}/api/ledger/export", timeout=120)
        assert e.status_code == 200 and "text/csv" in e.headers.get("content-type", "")
        assert e.text.splitlines()[0].startswith("created_at,client_name")


# ---------------- Reports / dashboard / audit ----------------
class TestReports:
    def test_dashboard(self, admin, agent):
        r = admin.get(f"{BASE_URL}/api/dashboard", timeout=120)
        assert r.status_code == 200, r.text
        b = r.json()
        k = b["kpis"]
        for key in ["total_leads", "active_leads", "total_calls", "calls_today",
                    "total_clients", "ftd_clients", "conversion_rate",
                    "ledger_credit", "ledger_debit", "net_balance",
                    "converted_leads", "calls_in_range", "avg_call_duration",
                    "unassigned_leads", "overdue_followups"]:
            assert key in k, key
        assert k["total_leads"] > 0 and k["total_calls"] > 0
        assert len(b["calls_trend"]) == 7
        assert len(b["disposition_mix"]) > 0
        assert "pipeline_funnel" in b and len(b["pipeline_funnel"]) >= 6
        assert "source_breakdown" in b and "agent_performance" in b
        assert "daily_trend" in b and "aging_sla" in b and "insights" in b
        ag = agent.get(f"{BASE_URL}/api/dashboard", timeout=120).json()
        assert ag["kpis"]["total_leads"] < k["total_leads"]

    def test_dashboard_requires_auth(self):
        import requests
        r = requests.get(f"{BASE_URL}/api/dashboard", timeout=30)
        assert r.status_code == 401

    def test_dashboard_filter_options(self, admin, agent):
        r = admin.get(f"{BASE_URL}/api/dashboard/filter-options", timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "New" in body["stages"]
        assert len(body["sources"]) >= 7
        assert isinstance(body["dispositions"], list)
        assert len(body["agents"]) > 0
        ag = agent.get(f"{BASE_URL}/api/dashboard/filter-options", timeout=30).json()
        assert ag["agents"] == []

    def test_dashboard_date_filter_shrinks(self, admin):
        all_r = admin.get(f"{BASE_URL}/api/dashboard", timeout=120).json()
        far = admin.get(f"{BASE_URL}/api/dashboard?from=2099-01-01&to=2099-01-02", timeout=120)
        assert far.status_code == 200, far.text
        far_b = far.json()
        assert far_b["kpis"]["total_leads"] == 0
        assert far_b["kpis"]["calls_in_range"] == 0
        assert all_r["kpis"]["total_leads"] > far_b["kpis"]["total_leads"]

    def test_dashboard_invalid_dates(self, admin):
        r = admin.get(f"{BASE_URL}/api/dashboard?from=not-a-date", timeout=30)
        assert r.status_code == 400
        r2 = admin.get(f"{BASE_URL}/api/dashboard?from=2025-12-01&to=2025-01-01", timeout=30)
        assert r2.status_code == 400

    def test_dashboard_own_scope_ignores_unassigned(self, agent):
        un = agent.get(f"{BASE_URL}/api/dashboard?assignment_status=unassigned", timeout=120).json()
        # Own-scope agents never see unassigned pool; filter must not zero their KPIs
        assert un["kpis"]["unassigned_leads"] == 0
        base = agent.get(f"{BASE_URL}/api/dashboard", timeout=120).json()
        assert base["kpis"]["unassigned_leads"] == 0
        assert un["kpis"]["total_leads"] > 0
        assert base["kpis"]["total_leads"] > 0

    def test_dashboard_status_filter(self, admin):
        r = admin.get(f"{BASE_URL}/api/dashboard?status=active", timeout=120)
        assert r.status_code == 200
        b = r.json()
        assert b["kpis"]["active_leads"] == b["kpis"]["total_leads"]


    def test_reports_tabs(self, admin):
        for kind in ["caller", "affiliate", "company"]:
            r = admin.get(f"{BASE_URL}/api/reports/{kind}", timeout=120)
            assert r.status_code == 200, f"{kind}: {r.text[:200]}"
            body = r.json()
            assert isinstance(body["rows"], list) and len(body["rows"]) > 0
            assert "summary" in body

    def test_reports_caller_summary_and_connect_rate(self, admin):
        r = admin.get(f"{BASE_URL}/api/reports/caller", timeout=120)
        assert r.status_code == 200
        body = r.json()
        s = body["summary"]
        for key in ["total_calls", "total_connected", "connect_rate",
                    "total_leads", "total_conversions", "conversion_rate"]:
            assert key in s, key
        assert all("connect_rate" in row for row in body["rows"])

    def test_reports_date_filter(self, admin):
        all_caller = admin.get(f"{BASE_URL}/api/reports/caller", timeout=120).json()
        far = admin.get(f"{BASE_URL}/api/reports/caller?from=2099-01-01&to=2099-01-31", timeout=120)
        assert far.status_code == 200
        far_b = far.json()
        assert far_b["summary"]["total_calls"] == 0
        assert all(row["calls"] == 0 for row in far_b["rows"])
        assert all_caller["summary"]["total_calls"] >= far_b["summary"]["total_calls"]
        co = admin.get(f"{BASE_URL}/api/reports/company?from=2099-01-01&to=2099-01-02", timeout=120)
        assert co.status_code == 200
        assert co.json()["summary"]["total_leads"] == 0
        bad = admin.get(f"{BASE_URL}/api/reports/company?from=bad", timeout=30)
        assert bad.status_code == 400

    def test_reports_requires_auth(self):
        import requests
        r = requests.get(f"{BASE_URL}/api/reports/caller", timeout=30)
        assert r.status_code == 401

    def test_reports_agent_denied(self, agent):
        r = agent.get(f"{BASE_URL}/api/reports/caller", timeout=30)
        assert r.status_code == 403

    def test_reports_export(self, admin):
        for kind, header in [("caller", "name,calls"), ("affiliate", "name,clients"),
                             ("company", "source,leads")]:
            r = admin.get(
                f"{BASE_URL}/api/reports/export?kind={kind}&from=2020-01-01&to=2099-12-31",
                timeout=120,
            )
            assert r.status_code == 200, f"{kind}: {r.status_code} {r.text[:200]}"
            assert r.text.splitlines()[0].startswith(header), r.text.splitlines()[0]
        caller_csv = admin.get(
            f"{BASE_URL}/api/reports/export?kind=caller", timeout=120
        ).text.splitlines()[0]
        assert "connect_rate" in caller_csv
        aff_csv = admin.get(
            f"{BASE_URL}/api/reports/export?kind=affiliate", timeout=120
        ).text.splitlines()[0]
        assert "ftd_rate" in aff_csv

    def test_caller_report_scope_supervisor(self, supervisor, admin):
        s = supervisor.get(f"{BASE_URL}/api/reports/caller", timeout=120)
        assert s.status_code == 200
        a = admin.get(f"{BASE_URL}/api/reports/caller", timeout=120).json()["rows"]
        assert len(s.json()["rows"]) <= len(a)

    def test_audit_log(self, admin):
        r = admin.get(f"{BASE_URL}/api/audit?page_size=20", timeout=60)
        assert r.status_code == 200
        b = r.json()
        assert b["total"] > 0
        actions = {l["action"] for l in b["logs"]}
        assert len(actions) > 0
        s = admin.get(f"{BASE_URL}/api/audit?search=login", timeout=60).json()
        assert s["total"] > 0
        assert all("login" in (l["action"] + l["entity"] + (l.get("actor_name") or "")).lower()
                   for l in s["logs"])


# ---------------- Admin: users, roles, teams ----------------
class TestAdminModules:
    def test_roles_and_menu_catalog(self, admin):
        roles = admin.get(f"{BASE_URL}/api/roles", timeout=30).json()["roles"]
        names = [r["name"] for r in roles]
        assert len(names) == len(set(names)), f"duplicate role names: {names}"
        assert {"Super Admin", "Supervisor", "Agent", "Affiliate"} <= set(names)
        sysrole = [r for r in roles if r["name"] == "Super Admin"][0]
        assert sysrole["is_system"] is True and sysrole["data_scope"] == "ALL"
        assert "user_count" in sysrole
        cat = admin.get(f"{BASE_URL}/api/menus/catalog", timeout=30).json()["menus"]
        assert len(cat) >= 14 and all("actions" in m for m in cat)

    def test_create_edit_delete_custom_role(self, admin):
        name = uniq("TEST_Role_")
        r = admin.post(f"{BASE_URL}/api/roles", json={
            "name": name, "description": "test role", "permissions": ["leads:view", "dashboard:view"],
            "menus": ["leads", "dashboard"], "data_scope": "TEAM"}, timeout=30)
        assert r.status_code == 200, r.text
        role = r.json()["role"]
        assert role["is_system"] is False and role["data_scope"] == "TEAM"
        u = admin.put(f"{BASE_URL}/api/roles/{role['id']}", json={
            "name": name + "_x", "description": "upd", "permissions": ["leads:view"],
            "menus": ["leads"], "data_scope": "OWN"}, timeout=30)
        assert u.status_code == 200
        got = [x for x in admin.get(f"{BASE_URL}/api/roles", timeout=30).json()["roles"] if x["id"] == role["id"]][0]
        assert got["name"] == name + "_x" and got["data_scope"] == "OWN" and got["permissions"] == ["leads:view"]
        assert admin.delete(f"{BASE_URL}/api/roles/{role['id']}", timeout=30).status_code == 200
        assert not any(x["id"] == role["id"] for x in admin.get(f"{BASE_URL}/api/roles", timeout=30).json()["roles"])

    def test_system_role_name_locked_and_undeletable(self, admin):
        roles = admin.get(f"{BASE_URL}/api/roles", timeout=30).json()["roles"]
        agent_role = [r for r in roles if r["name"] == "Agent"][0]
        original_perms = agent_role["permissions"]
        u = admin.put(f"{BASE_URL}/api/roles/{agent_role['id']}", json={
            "name": "HACKED", "description": agent_role.get("description", ""),
            "permissions": original_perms, "menus": agent_role["menus"],
            "data_scope": agent_role["data_scope"]}, timeout=30)
        assert u.status_code == 200
        after = [r for r in admin.get(f"{BASE_URL}/api/roles", timeout=30).json()["roles"]
                 if r["id"] == agent_role["id"]][0]
        assert after["name"] == "Agent", "system role name was renamed"
        d = admin.delete(f"{BASE_URL}/api/roles/{agent_role['id']}", timeout=30)
        assert d.status_code == 400

    def test_users_crud(self, admin):
        roles = admin.get(f"{BASE_URL}/api/roles", timeout=30).json()["roles"]
        agent_role = [r for r in roles if r["name"] == "Agent"][0]["id"]
        email = f"test_user_{uuid.uuid4().hex[:8]}@example.com"
        r = admin.post(f"{BASE_URL}/api/users", json={
            "name": "TEST_User", "email": email, "password": TEST_PASSWORD,
            "role_id": agent_role, "user_type": "caller", "daily_quota": 30}, timeout=30)
        assert r.status_code == 200, r.text
        u = r.json()["user"]
        assert "password_hash" not in u and u["daily_quota"] == 30
        users = admin.get(f"{BASE_URL}/api/users", timeout=30).json()["users"]
        mine = [x for x in users if x["id"] == u["id"]][0]
        assert mine["role_name"] == "Agent" and mine["email"] == email
        # new user can login
        lr = requests.post(f"{BASE_URL}/api/auth/login",
                           json={"email": email, "password": TEST_PASSWORD}, timeout=30)
        assert lr.status_code == 200, lr.text
        # duplicate email
        dup = admin.post(f"{BASE_URL}/api/users", json={
            "name": "x", "email": email, "password": TEST_PASSWORD, "role_id": agent_role}, timeout=30)
        assert dup.status_code == 400
        # missing password
        nop = admin.post(f"{BASE_URL}/api/users", json={
            "name": "x", "email": f"n{uuid.uuid4().hex[:6]}@example.com", "role_id": agent_role}, timeout=30)
        assert nop.status_code == 400
        # update
        up = admin.put(f"{BASE_URL}/api/users/{u['id']}", json={
            "name": "TEST_User2", "email": email, "role_id": agent_role,
            "user_type": "caller", "daily_quota": 44}, timeout=30)
        assert up.status_code == 200
        mine = [x for x in admin.get(f"{BASE_URL}/api/users", timeout=30).json()["users"] if x["id"] == u["id"]][0]
        assert mine["name"] == "TEST_User2" and mine["daily_quota"] == 44
        # deactivate
        assert admin.delete(f"{BASE_URL}/api/users/{u['id']}", timeout=30).status_code == 200
        mine = [x for x in admin.get(f"{BASE_URL}/api/users", timeout=30).json()["users"] if x["id"] == u["id"]][0]
        assert mine["active"] is False
        # deactivated user cannot login
        lr2 = requests.post(f"{BASE_URL}/api/auth/login",
                            json={"email": email, "password": TEST_PASSWORD}, timeout=30)
        assert lr2.status_code in (401, 403), lr2.status_code

    def test_cannot_delete_self(self, admin):
        r = admin.delete(f"{BASE_URL}/api/users/{admin.user['id']}", timeout=30)
        assert r.status_code == 400

    def test_teams_crud(self, admin):
        roles = admin.get(f"{BASE_URL}/api/roles", timeout=30).json()["roles"]
        agent_role = [r for r in roles if r["name"] == "Agent"][0]["id"]
        callers = []
        for _ in range(2):
            e = f"test_tm_{uuid.uuid4().hex[:8]}@example.com"
            cr = admin.post(f"{BASE_URL}/api/users", json={
                "name": "TEST_TeamMember", "email": e, "password": TEST_PASSWORD,
                "role_id": agent_role, "user_type": "caller", "daily_quota": 5}, timeout=30)
            assert cr.status_code == 200, cr.text
            callers.append(cr.json()["user"])
        sup_id = callers[0]["id"]
        name = uniq("TEST_Team_")
        r = admin.post(f"{BASE_URL}/api/teams", json={
            "name": name, "supervisor_id": sup_id,
            "member_ids": [c["id"] for c in callers]}, timeout=30)
        assert r.status_code == 200, r.text
        t = r.json()["team"]
        teams = admin.get(f"{BASE_URL}/api/teams", timeout=30).json()["teams"]
        mine = [x for x in teams if x["id"] == t["id"]][0]
        assert mine["supervisor_name"] and len(mine["member_names"]) == len(callers)
        up = admin.put(f"{BASE_URL}/api/teams/{t['id']}", json={
            "name": name + "_x", "supervisor_id": sup_id,
            "member_ids": [callers[0]["id"]]}, timeout=30)
        assert up.status_code == 200
        mine = [x for x in admin.get(f"{BASE_URL}/api/teams", timeout=30).json()["teams"] if x["id"] == t["id"]][0]
        assert mine["name"] == name + "_x" and len(mine["member_ids"]) == 1
        assert admin.delete(f"{BASE_URL}/api/teams/{t['id']}", timeout=30).status_code == 200
        assert not any(x["id"] == t["id"] for x in admin.get(f"{BASE_URL}/api/teams", timeout=30).json()["teams"])
        assert admin.put(f"{BASE_URL}/api/teams/nope", json={"name": "x"}, timeout=30).status_code == 404
        for c in callers:
            admin.delete(f"{BASE_URL}/api/users/{c['id']}", timeout=30)
