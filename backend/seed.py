"""Seed: menu catalog, roles, admin + demo users, dispositions, leads, clients, ledger."""
import random
from datetime import timedelta
from core import (db, COMPANY_ID, hash_password, new_id, now_utc, now_iso,
                  normalize_phone, verify_password, dedupe_menus_by_key)
from lead_constants import LEAD_SOURCES
import os

# ---------- Menu catalog (key, label, icon, path, group, order, actions) ----------
MENU_CATALOG = [
    ("dashboard", "Dashboard", "Gauge", "/dashboard", "Overview", 1, ["view"]),
    ("leads", "Leads", "Users", "/leads", "Sales", 2, ["view", "create", "edit", "delete", "import", "export", "assign"]),
    ("today_calls", "Today Calls", "PhoneCall", "/today-calls", "Sales", 3, ["view", "log"]),
    ("call_history", "Call History", "ClockCounterClockwise", "/call-history", "Sales", 4, ["view", "export"]),
    ("pipeline", "Pipeline", "Kanban", "/pipeline", "Sales", 5, ["view", "edit"]),
    ("followups", "Follow-ups", "CalendarCheck", "/followups", "Sales", 6, ["view", "edit"]),
    ("dispositions", "Responses", "ListChecks", "/dispositions", "Config", 7, ["view", "create", "edit", "delete"]),
    ("clients", "Clients", "UserCircleGear", "/clients", "Finance", 8, ["view", "create", "edit", "convert"]),
    ("ledger", "Finance Ledger", "Wallet", "/ledger", "Finance", 9, ["view", "post", "reverse", "export"]),
    ("reports", "Reports", "ChartBar", "/reports", "Analytics", 10, ["view", "export"]),
    ("users", "Users", "IdentificationBadge", "/users", "Admin", 11, ["view", "create", "edit", "delete"]),
    ("teams", "Teams", "UsersThree", "/teams", "Admin", 12, ["view", "create", "edit", "delete"]),
    ("roles_menus", "Roles & Menus", "ShieldCheck", "/roles", "Admin", 13, ["view", "create", "edit", "delete"]),
    ("audit", "Audit Log", "FileMagnifyingGlass", "/audit", "Admin", 14, ["view"]),
]


def all_permissions():
    perms = []
    for key, *_rest, actions in MENU_CATALOG:
        for a in actions:
            perms.append(f"{key}:{a}")
    return perms


def perms_for(keys_actions):
    out = []
    for key, actions in keys_actions.items():
        for a in actions:
            out.append(f"{key}:{a}")
    return out


ROLE_DEFS = {
    "Super Admin": {
        "description": "Full access to every menu, permission and all data.",
        "data_scope": "ALL", "is_system": True,
        "permissions": all_permissions(),
        "menus": [m[0] for m in MENU_CATALOG],
    },
    "Supervisor": {
        "description": "Manages a team; sees team data.",
        "data_scope": "TEAM", "is_system": True,
        "permissions": perms_for({
            "dashboard": ["view"], "leads": ["view", "edit", "assign", "export"],
            "today_calls": ["view", "log"], "call_history": ["view", "export"],
            "pipeline": ["view", "edit"], "followups": ["view", "edit"],
            "dispositions": ["view"], "clients": ["view", "convert"],
            "ledger": ["view"], "reports": ["view", "export"], "teams": ["view"],
        }),
        "menus": ["dashboard", "leads", "today_calls", "call_history", "pipeline",
                  "followups", "dispositions", "clients", "ledger", "reports", "teams"],
    },
    "Agent": {
        "description": "Caller. Works own assigned leads via Today Calls.",
        "data_scope": "OWN", "is_system": True,
        "permissions": perms_for({
            "dashboard": ["view"], "leads": ["view"], "today_calls": ["view", "log"],
            "call_history": ["view"], "pipeline": ["view", "edit"],
            "followups": ["view", "edit"], "clients": ["view"],
        }),
        "menus": ["dashboard", "today_calls", "call_history", "leads", "pipeline",
                  "followups", "clients"],
    },
    "Affiliate": {
        "description": "External partner; sees own referred clients & reports.",
        "data_scope": "OWN", "is_system": True,
        "permissions": perms_for({
            "dashboard": ["view"], "clients": ["view"], "reports": ["view"],
        }),
        "menus": ["dashboard", "clients", "reports"],
    },
}

# name, order, type, requires_acw, color, default_pipeline_stage, converts_to_client
DISPOSITIONS = [
    ("Interested", 1, "carry_forward", False, "#0EA5E9", "Qualified", False),
    ("Call Back", 2, "carry_forward", False, "#38BDF8", "Contacted", False),
    ("Ringing / No Answer", 3, "carry_forward", False, "#7DD3FC", "Contacted", False),
    ("Switched Off", 4, "carry_forward", False, "#94A3B8", "Contacted", False),
    ("Not Interested", 5, "non_carry_forward", False, "#F59E0B", "Lost", False),
    ("Wrong Number", 6, "non_carry_forward", False, "#EF4444", "Lost", False),
    ("Converted", 7, "non_carry_forward", True, "#0369A1", "Won", True),
    ("DND / Do Not Call", 8, "non_carry_forward", False, "#475569", "Lost", False),
]

DISPOSITION_PIPELINE_DEFAULTS = {row[0]: (row[5], row[6]) for row in DISPOSITIONS}

PIPELINE_STAGES = ["New", "Contacted", "Qualified", "Proposal", "Won", "Lost"]

FIRST = ["Aarav", "Vivaan", "Aditya", "Diya", "Ananya", "Ishaan", "Kabir", "Meera",
         "Rohan", "Saanvi", "Arjun", "Priya", "Karan", "Neha", "Rahul", "Sneha",
         "Vikram", "Pooja", "Amit", "Tanya", "Nikhil", "Riya", "Sameer", "Kavya"]
LAST = ["Sharma", "Verma", "Patel", "Gupta", "Reddy", "Nair", "Iyer", "Mehta",
        "Singh", "Kapoor", "Joshi", "Malhotra", "Rao", "Bose", "Chopra", "Desai"]
SOURCES = [s for s in LEAD_SOURCES if s not in ("Manual", "Import")]
CITIES = ["Mumbai", "Delhi", "Bengaluru", "Pune", "Hyderabad", "Chennai", "Kolkata"]


async def dedupe_menu_catalog():
    """Remove duplicate menu rows left by parallel seed runs (same companyId + key)."""
    pipeline = [
        {"$group": {
            "_id": {"companyId": "$companyId", "key": "$key"},
            "ids": {"$push": "$_id"},
            "count": {"$sum": 1},
        }},
        {"$match": {"count": {"$gt": 1}}},
    ]
    async for group in db.menus.aggregate(pipeline):
        for oid in group["ids"][1:]:
            await db.menus.delete_one({"_id": oid})


async def dedupe_roles():
    """Remove duplicate role rows left by parallel seed runs (same companyId + name)."""
    pipeline = [
        {"$group": {
            "_id": {"companyId": "$companyId", "name": "$name"},
            "docs": {"$push": {"id": "$id", "created_at": "$created_at", "_id": "$_id"}},
            "count": {"$sum": 1},
        }},
        {"$match": {"count": {"$gt": 1}}},
    ]
    async for group in db.roles.aggregate(pipeline):
        docs = group["docs"]
        best = docs[0]
        best_score = (-1, "")
        for doc in docs:
            user_count = await db.users.count_documents({"role_id": doc["id"]})
            created = doc.get("created_at") or ""
            score = (user_count, created)
            if score > best_score:
                best_score = score
                best = doc
        keep_id = best["id"]
        for doc in docs:
            if doc["id"] == keep_id:
                continue
            await db.users.update_many({"role_id": doc["id"]}, {"$set": {"role_id": keep_id}})
            await db.roles.delete_one({"_id": doc["_id"]})


async def ensure_indexes():
    await dedupe_menu_catalog()
    await dedupe_roles()
    await db.menus.create_index([("companyId", 1), ("key", 1)], unique=True)
    await db.roles.create_index([("companyId", 1), ("name", 1)], unique=True)
    await db.users.create_index("email", unique=True)
    await db.users.create_index("id")
    await db.leads.create_index([("companyId", 1), ("phone", 1)])
    await db.leads.create_index("assigned_to")
    await db.ledger.create_index("idempotency_key", unique=True, sparse=True)
    await db.ledger.create_index([("client_id", 1), ("created_at", 1)])
    await db.calls.create_index("agent_id")
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.login_attempts.create_index("identifier")


async def migrate_disposition_pipeline_links():
    """Backfill default_pipeline_stage + converts_to_client on known dispositions."""
    for name, (stage, converts) in DISPOSITION_PIPELINE_DEFAULTS.items():
        await db.dispositions.update_many(
            {"companyId": COMPANY_ID, "name": name},
            {"$set": {
                "default_pipeline_stage": stage,
                "converts_to_client": converts,
            }},
        )
    # Ensure any disposition missing the new keys gets safe defaults
    await db.dispositions.update_many(
        {"companyId": COMPANY_ID, "default_pipeline_stage": {"$exists": False}},
        {"$set": {"default_pipeline_stage": None}},
    )
    await db.dispositions.update_many(
        {"companyId": COMPANY_ID, "converts_to_client": {"$exists": False}},
        {"$set": {"converts_to_client": False}},
    )
    # Converted by name always converts + Won
    await db.dispositions.update_many(
        {"companyId": COMPANY_ID, "name": "Converted"},
        {"$set": {"default_pipeline_stage": "Won", "converts_to_client": True}},
    )
    # Call Back: no ACW — next work is the scheduled follow-up
    await db.dispositions.update_many(
        {"companyId": COMPANY_ID, "name": "Call Back"},
        {"$set": {"requires_acw": False}},
    )
    # Converted / client leads never stay on follow-up queue
    await db.leads.update_many(
        {"companyId": COMPANY_ID, "$or": [{"is_client": True}, {"status": "converted"}]},
        {"$set": {"follow_up_at": None}},
    )


async def seed():
    await ensure_indexes()

    # Menus
    for key, label, icon, path, group, order, actions in MENU_CATALOG:
        await db.menus.update_one(
            {"companyId": COMPANY_ID, "key": key},
            {"$set": {"key": key, "label": label, "icon": icon, "path": path,
                      "group": group, "order": order, "actions": actions,
                      "companyId": COMPANY_ID}},
            upsert=True)

    # Roles
    role_ids = {}
    for name, cfg in ROLE_DEFS.items():
        rid = new_id()
        await db.roles.update_one(
            {"companyId": COMPANY_ID, "name": name},
            {"$set": {
                "description": cfg["description"],
                "permissions": cfg["permissions"],
                "menus": cfg["menus"],
                "data_scope": cfg["data_scope"],
                "is_system": cfg["is_system"],
            }, "$setOnInsert": {
                "id": rid,
                "companyId": COMPANY_ID,
                "name": name,
                "created_at": now_iso(),
            }},
            upsert=True)
        role_doc = await db.roles.find_one({"companyId": COMPANY_ID, "name": name}, {"_id": 0, "id": 1})
        role_ids[name] = role_doc["id"]

    # Admin user
    admin_email = os.environ.get("ADMIN_EMAIL").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD")
    admin = await db.users.find_one({"email": admin_email})
    if not admin:
        admin_id = new_id()
        await db.users.insert_one({
            "id": admin_id, "companyId": COMPANY_ID, "email": admin_email,
            "password_hash": hash_password(admin_password), "name": "Shivaay (Owner)",
            "role_id": role_ids["Super Admin"], "user_type": "admin",
            "team_id": None, "active": True, "daily_quota": 0,
            "acw_pending_lead_id": None, "created_at": now_iso()})
    else:
        admin_id = admin["id"]
        if not verify_password(admin_password, admin["password_hash"]):
            await db.users.update_one({"id": admin_id},
                                      {"$set": {"password_hash": hash_password(admin_password)}})
        await db.users.update_one({"id": admin_id}, {"$set": {"role_id": role_ids["Super Admin"]}})

    await migrate_disposition_pipeline_links()

    # Keep demo passwords in sync with DEMO_PASSWORD (like admin above)
    demo_password = os.environ.get("DEMO_PASSWORD", "Passw0rd!")
    if await db.users.count_documents({"companyId": COMPANY_ID, "is_demo": True}) > 0:
        await db.users.update_many(
            {"companyId": COMPANY_ID, "is_demo": True},
            {"$set": {"password_hash": hash_password(demo_password)}},
        )
        return

    # Dispositions
    for name, order, dtype, acw, color, stage, converts in DISPOSITIONS:
        await db.dispositions.insert_one({
            "id": new_id(), "companyId": COMPANY_ID, "name": name, "slot": order,
            "type": dtype, "requires_acw": acw, "color": color, "order": order,
            "default_pipeline_stage": stage, "converts_to_client": converts,
            "active": True, "created_at": now_iso()})

    # Demo users: supervisor + agents + affiliate
    def mk_user(name, email, role, utype, quota=0, team=None):
        return {"id": new_id(), "companyId": COMPANY_ID, "email": email.lower(),
                "password_hash": hash_password(os.environ.get("DEMO_PASSWORD", "Passw0rd!")), "name": name,
                "role_id": role_ids[role], "user_type": utype, "team_id": team,
                "active": True, "daily_quota": quota, "acw_pending_lead_id": None,
                "is_demo": True, "created_at": now_iso()}

    sup = mk_user("Priya Menon", "supervisor@callingcrm.com", "Supervisor", "admin", 0)
    agents = [
        mk_user("Rohan Das", "rohan@callingcrm.com", "Agent", "caller", 25),
        mk_user("Sneha Roy", "sneha@callingcrm.com", "Agent", "caller", 25),
        mk_user("Karan Malhotra", "karan@callingcrm.com", "Agent", "caller", 20),
    ]
    aff = mk_user("Growth Partners LLP", "affiliate@callingcrm.com", "Affiliate", "affiliate", 0)
    await db.users.insert_many([sup] + agents + [aff])

    team_id = new_id()
    await db.teams.insert_one({
        "id": team_id, "companyId": COMPANY_ID, "name": "Sales Squad A",
        "supervisor_id": sup["id"], "member_ids": [a["id"] for a in agents],
        "created_at": now_iso()})
    for a in agents:
        await db.users.update_one({"id": a["id"]}, {"$set": {"team_id": team_id}})

    disp_docs = await db.dispositions.find({"companyId": COMPANY_ID}, {"_id": 0}).to_list(100)
    disp_map = {d["name"]: d for d in disp_docs}

    # Leads
    leads = []
    used_phones = set()
    for i in range(120):
        fn, ln = random.choice(FIRST), random.choice(LAST)
        base = 9000000000 + random.randint(0, 999999999)
        phone = normalize_phone(str(base))
        if phone in used_phones:
            continue
        used_phones.add(phone)
        assigned = random.choice(agents)
        created = now_utc() - timedelta(days=random.randint(0, 25))
        has_disp = random.random() < 0.6
        disp = random.choice(list(disp_map.values())) if has_disp else None
        stage = random.choice(PIPELINE_STAGES[:4]) if random.random() < 0.7 else "New"
        lead = {
            "id": new_id(), "companyId": COMPANY_ID,
            "name": f"{fn} {ln}", "phone": phone,
            "email": f"{fn.lower()}.{ln.lower()}{i}@example.com",
            "source": random.choice(SOURCES), "city": random.choice(CITIES),
            "status": "converted" if (disp and disp["name"] == "Converted") else "active",
            "assigned_to": assigned["id"], "assigned_name": assigned["name"],
            "owner_id": assigned["id"],
            "disposition_id": disp["id"] if disp else None,
            "disposition_name": disp["name"] if disp else None,
            "carry_forward": (disp["type"] == "carry_forward") if disp else True,
            "pipeline_stage": stage,
            "custom_fields": {"budget": random.choice(["10k", "25k", "50k", "1L"])},
            "follow_up_at": (now_utc() + timedelta(days=random.randint(0, 5))).isoformat()
            if (disp and disp["name"] == "Call Back") else None,
            "is_client": False, "client_id": None,
            "assigned_date": created.date().isoformat(),
            "created_at": created.isoformat(), "updated_at": created.isoformat(),
        }
        leads.append(lead)
    await db.leads.insert_many(leads)

    # Some leads assigned TODAY for Today Calls demo
    today = now_utc().date().isoformat()
    todays = random.sample(leads, 30)
    for l in todays:
        await db.leads.update_one({"id": l["id"]}, {"$set": {"assigned_date": today}})

    # Call activity history
    calls = []
    for l in random.sample(leads, 80):
        d = disp_map[l["disposition_name"]] if l["disposition_name"] else random.choice(disp_docs)
        when = now_utc() - timedelta(days=random.randint(0, 20), minutes=random.randint(0, 600))
        calls.append({
            "id": new_id(), "companyId": COMPANY_ID, "lead_id": l["id"],
            "lead_name": l["name"], "lead_phone": l["phone"],
            "agent_id": l["assigned_to"], "agent_name": l["assigned_name"],
            "disposition_id": d["id"], "disposition_name": d["name"],
            "outcome": "connected", "notes": "Discussed the offering. Follow-up noted.",
            "duration": random.randint(30, 480),
            "follow_up_at": None, "created_at": when.isoformat()})
    await db.calls.insert_many(calls)

    # Clients from converted leads + ledger
    converted = [l for l in leads if l["status"] == "converted"][:14]
    for l in converted:
        cid = new_id()
        conv_at = now_utc() - timedelta(days=random.randint(1, 15))
        await db.clients.insert_one({
            "id": cid, "companyId": COMPANY_ID, "lead_id": l["id"],
            "name": l["name"], "phone": l["phone"], "email": l["email"],
            "assigned_to": l["assigned_to"], "assigned_name": l["assigned_name"],
            "owner_id": l["assigned_to"], "affiliate_id": aff["id"],
            "ftd_at": None, "balance": 0.0, "status": "active",
            "notes": [], "created_at": conv_at.isoformat()})
        await db.leads.update_one({"id": l["id"]},
                                  {"$set": {"is_client": True, "client_id": cid,
                                            "pipeline_stage": "Won"}})
        # ledger entries
        bal = 0.0
        n_tx = random.randint(2, 6)
        first_deposit_done = False
        for j in range(n_tx):
            is_credit = random.random() < 0.65 or j == 0 or bal <= 0
            amt = round(random.choice([500, 1000, 2500, 5000, 10000]) * random.uniform(0.8, 1.5), 2)
            if is_credit:
                bal += amt
            else:
                amt = round(min(amt, bal), 2)
                if amt <= 0:
                    continue
                bal -= amt
            tx_at = conv_at + timedelta(hours=(j + 1) * 8)
            if tx_at > now_utc():
                tx_at = now_utc() - timedelta(minutes=random.randint(1, 120))
            entry = {
                "id": new_id(), "companyId": COMPANY_ID, "client_id": cid,
                "type": "credit" if is_credit else "debit", "amount": amt,
                "balance_after": round(bal, 2),
                "description": "Deposit" if is_credit else "Withdrawal",
                "category": "deposit" if is_credit else "withdrawal",
                "idempotency_key": new_id(), "reversal_of": None,
                "created_by": sup["id"], "created_by_name": sup["name"],
                "created_at": tx_at.isoformat()}
            await db.ledger.insert_one(entry)
            if is_credit and not first_deposit_done:
                first_deposit_done = True
                await db.clients.update_one({"id": cid}, {"$set": {"ftd_at": tx_at.isoformat()}})
        await db.clients.update_one({"id": cid}, {"$set": {"balance": round(bal, 2)}})
