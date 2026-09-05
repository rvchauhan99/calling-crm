"""Clients (convert, notes) + append-only Finance Ledger with idempotency & reversals."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from core import (db, COMPANY_ID, require, scope_filter, client_scope_filter, new_id, now_iso, audit)

router = APIRouter(prefix="/api", tags=["clients"])


class ConvertIn(BaseModel):
    lead_id: str
    affiliate_id: Optional[str] = None
    deposit_amount: Optional[float] = None


class NoteIn(BaseModel):
    text: str


@router.get("/clients")
async def list_clients(search: Optional[str] = None, status: Optional[str] = None,
                       page: int = 1, page_size: int = 25,
                       principal: dict = Depends(require("clients:view"))):
    q = {"companyId": COMPANY_ID, **await client_scope_filter(principal)}
    if status in ("active", "inactive"):
        q["status"] = status
    if search:
        q["$or"] = [{"name": {"$regex": search, "$options": "i"}},
                    {"phone": {"$regex": search, "$options": "i"}}]
    total = await db.clients.count_documents(q)
    skip = (page - 1) * page_size
    clients = await db.clients.find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(page_size).to_list(page_size)
    return {"clients": clients, "total": total, "page": page, "page_size": page_size}


@router.get("/clients/tab-counts")
async def clients_tab_counts(principal: dict = Depends(require("clients:view"))):
    base = {"companyId": COMPANY_ID, **await client_scope_filter(principal)}
    active = await db.clients.count_documents({**base, "status": "active"})
    inactive = await db.clients.count_documents({**base, "status": "inactive"})
    return {"active": active, "inactive": inactive}


@router.get("/clients/convertible-leads")
async def convertible_leads(search: Optional[str] = None, page_size: int = 40,
                            principal: dict = Depends(require("clients:convert"))):
    q = {
        "companyId": COMPANY_ID,
        "is_client": {"$ne": True},
        "status": {"$in": ["active", "inactive"]},
        **await scope_filter(principal, "assigned_to"),
    }
    if search:
        q["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"phone": {"$regex": search, "$options": "i"}},
        ]
    leads = await db.leads.find(
        q, {"_id": 0, "id": 1, "name": 1, "phone": 1},
    ).sort("updated_at", -1).limit(min(page_size, 100)).to_list(100)
    return {"leads": leads}


async def _create_client_from_lead(lead: dict, principal: dict, affiliate_id: Optional[str] = None) -> dict:
    cid = new_id()
    client = {
        "id": cid, "companyId": COMPANY_ID, "lead_id": lead["id"],
        "name": lead["name"], "phone": lead["phone"], "email": lead.get("email", ""),
        "assigned_to": lead.get("assigned_to"), "assigned_name": lead.get("assigned_name"),
        "owner_id": lead.get("assigned_to") or principal["id"],
        "affiliate_id": affiliate_id, "ftd_at": None, "balance": 0.0,
        "status": "active", "notes": [], "created_at": now_iso(),
    }
    await db.clients.insert_one(dict(client))
    await db.leads.update_one(
        {"id": lead["id"]},
        {"$set": {
            "is_client": True, "client_id": cid,
            "status": "converted", "pipeline_stage": "Won",
            "follow_up_at": None,
            "updated_at": now_iso(),
        }},
    )
    await audit(principal, "convert", "client", cid, {"lead_id": lead["id"]})
    return client


async def _post_conversion_deposit(
    client_id: str,
    amount: float,
    principal: dict,
    *,
    idempotency_key: str,
    description: str = "Initial deposit on conversion",
) -> dict:
    """Post credit/deposit for a client on convert. Idempotent by key. Raises HTTPException on bad amount."""
    if amount is None:
        return {"deposit_posted": False, "entry": None, "idempotent": False}
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="deposit_amount must be a number")
    if amt < 0:
        raise HTTPException(status_code=400, detail="deposit_amount must be positive")
    if amt == 0:
        return {"deposit_posted": False, "entry": None, "idempotent": False}

    client = await db.clients.find_one({"id": client_id, "companyId": COMPANY_ID}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    existing = await db.ledger.find_one({"idempotency_key": idempotency_key}, {"_id": 0})
    if existing:
        return {"deposit_posted": True, "entry": existing, "idempotent": True}

    prev_balance = await _recompute_balance(client_id)
    new_balance = round(prev_balance + amt, 2)
    entry = {
        "id": new_id(),
        "companyId": COMPANY_ID,
        "client_id": client_id,
        "type": "credit",
        "amount": round(amt, 2),
        "balance_after": new_balance,
        "description": description or "Initial deposit on conversion",
        "category": "deposit",
        "idempotency_key": idempotency_key,
        "reversal_of": None,
        "created_by": principal["id"],
        "created_by_name": principal["name"],
        "created_at": now_iso(),
    }
    try:
        await db.ledger.insert_one(dict(entry))
    except Exception:
        dupe = await db.ledger.find_one({"idempotency_key": idempotency_key}, {"_id": 0})
        if dupe:
            return {"deposit_posted": True, "entry": dupe, "idempotent": True}
        raise
    await db.clients.update_one({"id": client_id}, {"$set": {"balance": new_balance}})
    if not client.get("ftd_at"):
        await db.clients.update_one({"id": client_id}, {"$set": {"ftd_at": entry["created_at"]}})
    await audit(principal, "ledger_post", "client", client_id,
                {"type": "credit", "amount": amt, "source": "conversion_deposit"})
    return {"deposit_posted": True, "entry": entry, "idempotent": False}


@router.post("/clients/convert")
async def convert_lead(body: ConvertIn, principal: dict = Depends(require("clients:convert"))):
    if body.deposit_amount is not None:
        try:
            dep_amt = float(body.deposit_amount)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="deposit_amount must be a number")
        if dep_amt < 0:
            raise HTTPException(status_code=400, detail="deposit_amount must be positive")
    lead = await db.leads.find_one({"id": body.lead_id, "companyId": COMPANY_ID}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.get("is_client"):
        raise HTTPException(status_code=400, detail="Lead is already a client")
    client = await _create_client_from_lead(lead, principal, body.affiliate_id)
    deposit = await _post_conversion_deposit(
        client["id"],
        body.deposit_amount,
        principal,
        idempotency_key=f"convert-deposit:{client['id']}:manual-convert",
    )
    # Refresh client balance/ftd after optional deposit
    if deposit.get("deposit_posted"):
        updated = await db.clients.find_one({"id": client["id"]}, {"_id": 0})
        if updated:
            client = updated
    return {
        "client": client,
        "deposit_posted": deposit.get("deposit_posted", False),
        "ledger_entry_id": (deposit.get("entry") or {}).get("id") if deposit.get("entry") else None,
    }


@router.get("/clients/{cid}")
async def client_detail(cid: str, principal: dict = Depends(require("clients:view"))):
    client = await db.clients.find_one({"id": cid, "companyId": COMPANY_ID}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    ledger = await db.ledger.find({"client_id": cid}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return {"client": client, "ledger": ledger}


@router.post("/clients/{cid}/notes")
async def add_note(cid: str, body: NoteIn, principal: dict = Depends(require("clients:edit"))):
    note = {"id": new_id(), "text": body.text, "author": principal["name"], "created_at": now_iso()}
    res = await db.clients.update_one({"id": cid, "companyId": COMPANY_ID}, {"$push": {"notes": note}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Client not found")
    return {"note": note}


# ---------------- Ledger (append-only) ----------------
class LedgerPostIn(BaseModel):
    client_id: str
    type: str  # credit | debit
    amount: float
    description: str = ""
    category: str = "deposit"
    idempotency_key: str


async def _recompute_balance(client_id: str) -> float:
    """Balance derived from immutable entries; never mutated in place."""
    entries = await db.ledger.find({"client_id": client_id}, {"_id": 0}).sort("created_at", 1).to_list(10000)
    bal = 0.0
    for e in entries:
        bal += e["amount"] if e["type"] == "credit" else -e["amount"]
    return round(bal, 2)


@router.get("/ledger")
async def ledger_all(page: int = 1, page_size: int = 40,
                     principal: dict = Depends(require("ledger:view"))):
    # scope by client ownership
    cfilter = {"companyId": COMPANY_ID, **await client_scope_filter(principal)}
    client_ids = [c["id"] for c in await db.clients.find(cfilter, {"_id": 0, "id": 1}).to_list(5000)]
    q = {"client_id": {"$in": client_ids}}
    total = await db.ledger.count_documents(q)
    skip = (page - 1) * page_size
    entries = await db.ledger.find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(page_size).to_list(page_size)
    cmap = {c["id"]: c["name"] for c in await db.clients.find(cfilter, {"_id": 0}).to_list(5000)}
    for e in entries:
        e["client_name"] = cmap.get(e["client_id"])
    totals = {"credit": 0.0, "debit": 0.0}
    for e in await db.ledger.find(q, {"_id": 0, "type": 1, "amount": 1}).to_list(100000):
        totals[e["type"]] = round(totals.get(e["type"], 0) + e["amount"], 2)
    return {"entries": entries, "total": total, "page": page, "page_size": page_size, "totals": totals}


@router.post("/ledger/post")
async def post_entry(body: LedgerPostIn, principal: dict = Depends(require("ledger:post"))):
    if body.type not in ("credit", "debit"):
        raise HTTPException(status_code=400, detail="type must be credit or debit")
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")
    client = await db.clients.find_one({"id": body.client_id, "companyId": COMPANY_ID}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    # idempotency
    existing = await db.ledger.find_one({"idempotency_key": body.idempotency_key}, {"_id": 0})
    if existing:
        return {"entry": existing, "idempotent": True}

    prev_balance = await _recompute_balance(body.client_id)
    if body.type == "debit" and body.amount > prev_balance:
        raise HTTPException(status_code=400, detail="Insufficient balance for debit")
    new_balance = round(prev_balance + (body.amount if body.type == "credit" else -body.amount), 2)

    entry = {"id": new_id(), "companyId": COMPANY_ID, "client_id": body.client_id,
             "type": body.type, "amount": round(body.amount, 2), "balance_after": new_balance,
             "description": body.description, "category": body.category,
             "idempotency_key": body.idempotency_key, "reversal_of": None,
             "created_by": principal["id"], "created_by_name": principal["name"],
             "created_at": now_iso()}
    try:
        await db.ledger.insert_one(dict(entry))
    except Exception:
        dupe = await db.ledger.find_one({"idempotency_key": body.idempotency_key}, {"_id": 0})
        if dupe:
            return {"entry": dupe, "idempotent": True}
        raise
    await db.clients.update_one({"id": body.client_id}, {"$set": {"balance": new_balance}})

    # FTD: first credit post-conversion, tracked once
    if body.type == "credit" and not client.get("ftd_at"):
        await db.clients.update_one({"id": body.client_id}, {"$set": {"ftd_at": entry["created_at"]}})

    await audit(principal, "ledger_post", "client", body.client_id,
                {"type": body.type, "amount": body.amount})
    return {"entry": entry, "idempotent": False}


@router.post("/ledger/{entry_id}/reverse")
async def reverse_entry(entry_id: str, principal: dict = Depends(require("ledger:reverse"))):
    orig = await db.ledger.find_one({"id": entry_id, "companyId": COMPANY_ID}, {"_id": 0})
    if not orig:
        raise HTTPException(status_code=404, detail="Entry not found")
    if orig.get("reversal_of"):
        raise HTTPException(status_code=400, detail="Cannot reverse a reversal entry")
    if await db.ledger.find_one({"reversal_of": entry_id}):
        raise HTTPException(status_code=400, detail="Entry already reversed")
    rev_type = "debit" if orig["type"] == "credit" else "credit"
    prev_balance = await _recompute_balance(orig["client_id"])
    new_balance = round(prev_balance + (orig["amount"] if rev_type == "credit" else -orig["amount"]), 2)
    entry = {"id": new_id(), "companyId": COMPANY_ID, "client_id": orig["client_id"],
             "type": rev_type, "amount": orig["amount"], "balance_after": new_balance,
             "description": f"Reversal of {orig['description'] or orig['id'][:8]}",
             "category": "reversal", "idempotency_key": new_id(), "reversal_of": entry_id,
             "created_by": principal["id"], "created_by_name": principal["name"],
             "created_at": now_iso()}
    await db.ledger.insert_one(dict(entry))
    await db.clients.update_one({"id": orig["client_id"]}, {"$set": {"balance": new_balance}})
    await audit(principal, "ledger_reverse", "client", orig["client_id"], {"entry": entry_id})
    return {"entry": entry}
