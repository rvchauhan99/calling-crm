#!/usr/bin/env python3
"""Seed / teardown large tagged fixtures for local hard memory testing.

LOCAL Mongo only. Never point MONGO_URL at Atlas.

Usage:
  cd backend && source .venv/bin/activate
  python scripts/seed_loadtest.py --tag LOADTEST_demo
  python scripts/seed_loadtest.py --teardown --tag LOADTEST_demo

Scale defaults match the Phase-2 hard gate (override with flags).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from core import COMPANY_ID, db, now_iso  # noqa: E402


def _assert_local_mongo():
    url = (os.environ.get("MONGO_URL") or "").lower()
    if not any(x in url for x in ("127.0.0.1", "localhost", "0.0.0.0")):
        raise SystemExit(
            f"Refusing to seed: MONGO_URL is not local ({os.environ.get('MONGO_URL')!r})"
        )


def _phone(i: int, tag: str) -> str:
    # 10-digit unique-ish phones per tag+index
    base = abs(hash(f"{tag}:{i}")) % 10_000_000_000
    return f"{base:010d}"


async def seed(tag: str, leads: int, calls: int, clients: int, ledger: int) -> dict:
    _assert_local_mongo()
    now = datetime.now(timezone.utc)
    agent_id = f"{tag}_agent"
    await db.users.update_one(
        {"id": agent_id},
        {"$set": {
            "id": agent_id,
            "companyId": COMPANY_ID,
            "name": f"{tag} Agent",
            "email": f"{tag.lower()}@example.local",
            "user_type": "caller",
            "active": True,
            "daily_quota": 500,
            "created_at": now_iso(),
        }},
        upsert=True,
    )

    lead_docs = []
    lead_ids = []
    for i in range(leads):
        lid = f"{tag}_lead_{i}"
        lead_ids.append(lid)
        created = (now - timedelta(days=(i % 30))).isoformat()
        fu = None
        if i % 11 == 0:
            fu = (now - timedelta(days=2)).isoformat()
        lead_docs.append({
            "id": lid,
            "companyId": COMPANY_ID,
            "name": f"{tag}_Lead_{i}",
            "phone": _phone(i, tag),
            "email": "",
            "source": "Import" if i % 2 == 0 else "Facebook Ads",
            "city": "Mumbai",
            "status": "active",
            "assigned_to": agent_id if i % 3 else None,
            "assigned_name": f"{tag} Agent" if i % 3 else None,
            "owner_id": agent_id if i % 3 else None,
            "disposition_id": None,
            "disposition_name": None,
            "carry_forward": True,
            "pipeline_stage": ["New", "Contacted", "Qualified"][i % 3],
            "custom_fields": {},
            "follow_up_at": fu,
            "is_client": False,
            "client_id": None,
            "assigned_date": now.date().isoformat() if i % 5 == 0 else None,
            "last_notes": None,
            "last_notes_at": None,
            "loadtest_tag": tag,
            "created_at": created,
            "updated_at": created,
        })
        if len(lead_docs) >= 1000:
            await db.leads.insert_many(lead_docs)
            lead_docs = []
            await asyncio.sleep(0)
    if lead_docs:
        await db.leads.insert_many(lead_docs)

    call_docs = []
    for i in range(calls):
        lid = lead_ids[i % len(lead_ids)]
        created = (now - timedelta(days=(i % 14), hours=(i % 24))).isoformat()
        call_docs.append({
            "id": f"{tag}_call_{i}",
            "companyId": COMPANY_ID,
            "lead_id": lid,
            "lead_name": f"{tag}_Lead_{i % len(lead_ids)}",
            "lead_phone": _phone(i % len(lead_ids), tag),
            "agent_id": agent_id,
            "agent_name": f"{tag} Agent",
            "disposition_name": ["Interested", "No Answer", "Callback"][i % 3],
            "outcome": "connected" if i % 2 == 0 else "no_answer",
            "duration": i % 120,
            "notes": "",
            "excluded_from_reports": False,
            "loadtest_tag": tag,
            "created_at": created,
        })
        if len(call_docs) >= 1000:
            await db.calls.insert_many(call_docs)
            call_docs = []
            await asyncio.sleep(0)
    if call_docs:
        await db.calls.insert_many(call_docs)

    client_ids = []
    client_docs = []
    for i in range(clients):
        cid = f"{tag}_client_{i}"
        client_ids.append(cid)
        client_docs.append({
            "id": cid,
            "companyId": COMPANY_ID,
            "name": f"{tag}_Client_{i}",
            "phone": _phone(10_000_000 + i, tag),
            "status": "active",
            "balance": float(i % 100),
            "ftd_at": now.isoformat() if i % 4 == 0 else None,
            "affiliate_id": None,
            "owner_id": agent_id,
            "deleted_at": None,
            "loadtest_tag": tag,
            "created_at": now.isoformat(),
        })
        if len(client_docs) >= 1000:
            await db.clients.insert_many(client_docs)
            client_docs = []
    if client_docs:
        await db.clients.insert_many(client_docs)

    ledger_docs = []
    for i in range(ledger):
        cid = client_ids[i % len(client_ids)] if client_ids else None
        if not cid:
            break
        ledger_docs.append({
            "id": f"{tag}_ledger_{i}",
            "companyId": COMPANY_ID,
            "client_id": cid,
            "type": "credit" if i % 2 == 0 else "debit",
            "amount": float((i % 50) + 1),
            "category": "deposit",
            "deleted_at": None,
            "loadtest_tag": tag,
            "created_at": now.isoformat(),
        })
        if len(ledger_docs) >= 1000:
            await db.ledger.insert_many(ledger_docs)
            ledger_docs = []
    if ledger_docs:
        await db.ledger.insert_many(ledger_docs)

    counts = {
        "leads": await db.leads.count_documents({"loadtest_tag": tag}),
        "calls": await db.calls.count_documents({"loadtest_tag": tag}),
        "clients": await db.clients.count_documents({"loadtest_tag": tag}),
        "ledger": await db.ledger.count_documents({"loadtest_tag": tag}),
        "tag": tag,
    }
    print("Seeded:", counts)
    return counts


async def teardown(tag: str) -> dict:
    _assert_local_mongo()
    out = {}
    for coll in ("leads", "calls", "clients", "ledger"):
        res = await db[coll].delete_many({"loadtest_tag": tag})
        out[coll] = res.deleted_count
    await db.users.delete_many({"id": f"{tag}_agent"})
    # Also remove by name prefix leftovers
    await db.leads.delete_many({"name": {"$regex": f"^{tag}_"}})
    print("Teardown:", out)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tag", default=f"LOADTEST_{uuid.uuid4().hex[:8]}")
    p.add_argument("--teardown", action="store_true")
    p.add_argument("--leads", type=int, default=50_000)
    p.add_argument("--calls", type=int, default=100_000)
    p.add_argument("--clients", type=int, default=5_000)
    p.add_argument("--ledger", type=int, default=20_000)
    # Smaller profile for quick CI-ish runs
    p.add_argument("--quick", action="store_true", help="Use 5k/10k/500/2k scale")
    args = p.parse_args()
    if args.quick:
        args.leads, args.calls, args.clients, args.ledger = 5_000, 10_000, 500, 2_000

    if args.teardown:
        asyncio.run(teardown(args.tag))
    else:
        asyncio.run(seed(args.tag, args.leads, args.calls, args.clients, args.ledger))


if __name__ == "__main__":
    main()
