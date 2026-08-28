"""Reports, dashboards (computed aggregations, IST), CSV export, audit log."""
import io
import csv
from datetime import timedelta, timezone, datetime
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from typing import Optional
from core import (db, COMPANY_ID, require, scope_filter, client_scope_filter, now_utc)

router = APIRouter(prefix="/api", tags=["reports"])

IST = timezone(timedelta(hours=5, minutes=30))


def ist_date(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(IST).date().isoformat()
    except Exception:
        return None


@router.get("/dashboard")
async def dashboard(principal: dict = Depends(require("dashboard:view"))):
    lead_scope = await scope_filter(principal, "assigned_to")
    call_scope = await scope_filter(principal, "agent_id")
    client_scope = await client_scope_filter(principal)
    lq = {"companyId": COMPANY_ID, **lead_scope}
    cq = {"companyId": COMPANY_ID, **call_scope}
    clq = {"companyId": COMPANY_ID, **client_scope}
    today = now_utc().date().isoformat()

    total_leads = await db.leads.count_documents(lq)
    active_leads = await db.leads.count_documents({**lq, "status": "active"})
    total_calls = await db.calls.count_documents(cq)
    total_clients = await db.clients.count_documents(clq)
    ftd_clients = await db.clients.count_documents({**clq, "ftd_at": {"$ne": None}})

    # ledger totals (scoped by client ownership)
    client_ids = [c["id"] for c in await db.clients.find(clq, {"_id": 0, "id": 1}).to_list(5000)]
    ledger = await db.ledger.find({"client_id": {"$in": client_ids}}, {"_id": 0}).to_list(100000)
    credit = round(sum(e["amount"] for e in ledger if e["type"] == "credit"), 2)
    debit = round(sum(e["amount"] for e in ledger if e["type"] == "debit"), 2)

    # disposition mix
    disp_mix = {}
    for c in await db.calls.find(cq, {"_id": 0, "disposition_name": 1}).to_list(100000):
        d = c.get("disposition_name") or "Unknown"
        disp_mix[d] = disp_mix.get(d, 0) + 1
    disp_arr = [{"name": k, "value": v} for k, v in sorted(disp_mix.items(), key=lambda x: -x[1])]

    # calls trend last 7 days (IST)
    trend = {}
    for i in range(6, -1, -1):
        d = (now_utc().astimezone(IST).date() - timedelta(days=i)).isoformat()
        trend[d] = 0
    for c in await db.calls.find(cq, {"_id": 0, "created_at": 1}).to_list(100000):
        d = ist_date(c["created_at"])
        if d in trend:
            trend[d] += 1
    trend_arr = [{"date": k[5:], "calls": v} for k, v in trend.items()]
    calls_today = trend_arr[-1]["calls"] if trend_arr else 0

    conv_rate = round((total_clients / total_leads * 100) if total_leads else 0, 1)
    return {
        "kpis": {"total_leads": total_leads, "active_leads": active_leads,
                 "total_calls": total_calls, "calls_today": calls_today,
                 "total_clients": total_clients, "ftd_clients": ftd_clients,
                 "conversion_rate": conv_rate, "ledger_credit": credit,
                 "ledger_debit": debit, "net_balance": round(credit - debit, 2)},
        "disposition_mix": disp_arr, "calls_trend": trend_arr}


@router.get("/reports/caller")
async def caller_report(principal: dict = Depends(require("reports:view"))):
    scope = await scope_filter(principal, "agent_id")
    agents = await db.users.find({"companyId": COMPANY_ID, "user_type": "caller"}, {"_id": 0}).to_list(500)
    rows = []
    for a in agents:
        aq = {"companyId": COMPANY_ID, "agent_id": a["id"]}
        calls = await db.calls.count_documents(aq)
        connected = await db.calls.count_documents({**aq, "outcome": "connected"})
        leads = await db.leads.count_documents({"companyId": COMPANY_ID, "assigned_to": a["id"]})
        converted = await db.leads.count_documents({"companyId": COMPANY_ID, "assigned_to": a["id"], "is_client": True})
        rows.append({"agent_id": a["id"], "name": a["name"], "calls": calls,
                     "connected": connected, "leads": leads, "conversions": converted,
                     "conversion_rate": round((converted / leads * 100) if leads else 0, 1)})
    # apply scope: agents show only if in scope set
    if principal.get("data_scope") != "ALL" and "agent_id" in scope:
        allowed = scope["agent_id"].get("$in") if isinstance(scope["agent_id"], dict) else [scope["agent_id"]]
        rows = [r for r in rows if r["agent_id"] in allowed]
    return {"rows": rows}


@router.get("/reports/affiliate")
async def affiliate_report(principal: dict = Depends(require("reports:view"))):
    q = {"companyId": COMPANY_ID, "user_type": "affiliate"}
    if principal.get("user_type") == "affiliate":
        q["id"] = principal["id"]
    elif principal.get("data_scope") != "ALL":
        return {"rows": []}
    affs = await db.users.find(q, {"_id": 0}).to_list(500)
    rows = []
    for a in affs:
        clients = await db.clients.find({"companyId": COMPANY_ID, "affiliate_id": a["id"]}, {"_id": 0}).to_list(5000)
        ftd = sum(1 for c in clients if c.get("ftd_at"))
        deposits = round(sum(c.get("balance", 0) for c in clients), 2)
        rows.append({"affiliate_id": a["id"], "name": a["name"], "clients": len(clients),
                     "ftd": ftd, "total_balance": deposits})
    return {"rows": rows}


@router.get("/reports/company")
async def company_report(principal: dict = Depends(require("reports:view"))):
    sources = {}
    async for l in db.leads.find({"companyId": COMPANY_ID}, {"_id": 0, "source": 1, "is_client": 1}):
        s = l.get("source") or "Unknown"
        if s not in sources:
            sources[s] = {"source": s, "leads": 0, "conversions": 0}
        sources[s]["leads"] += 1
        if l.get("is_client"):
            sources[s]["conversions"] += 1
    for s in sources.values():
        s["conversion_rate"] = round((s["conversions"] / s["leads"] * 100) if s["leads"] else 0, 1)
    return {"rows": sorted(sources.values(), key=lambda x: -x["leads"])}


def _csv_response(rows, fieldnames, filename):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename={filename}"})


@router.get("/reports/export")
async def export_report(kind: str = Query("caller"), principal: dict = Depends(require("reports:export"))):
    if kind == "caller":
        data = (await caller_report(principal))["rows"]
        return _csv_response(data, ["name", "calls", "connected", "leads", "conversions", "conversion_rate"], "caller_report.csv")
    if kind == "affiliate":
        data = (await affiliate_report(principal))["rows"]
        return _csv_response(data, ["name", "clients", "ftd", "total_balance"], "affiliate_report.csv")
    data = (await company_report(principal))["rows"]
    return _csv_response(data, ["source", "leads", "conversions", "conversion_rate"], "company_report.csv")


@router.get("/call-history/export")
async def export_calls(principal: dict = Depends(require("call_history:export"))):
    scope = await scope_filter(principal, "agent_id")
    calls = await db.calls.find({"companyId": COMPANY_ID, **scope}, {"_id": 0}).sort("created_at", -1).to_list(50000)
    return _csv_response(calls, ["created_at", "agent_name", "lead_name", "lead_phone",
                                 "disposition_name", "outcome", "duration", "notes"], "call_history.csv")


@router.get("/ledger/export")
async def export_ledger(principal: dict = Depends(require("ledger:export"))):
    cfilter = {"companyId": COMPANY_ID, **await client_scope_filter(principal)}
    client_ids = [c["id"] for c in await db.clients.find(cfilter, {"_id": 0, "id": 1}).to_list(5000)]
    cmap = {c["id"]: c["name"] for c in await db.clients.find(cfilter, {"_id": 0}).to_list(5000)}
    entries = await db.ledger.find({"client_id": {"$in": client_ids}}, {"_id": 0}).sort("created_at", -1).to_list(50000)
    for e in entries:
        e["client_name"] = cmap.get(e["client_id"])
    return _csv_response(entries, ["created_at", "client_name", "type", "amount",
                                   "balance_after", "category", "description", "created_by_name"], "ledger.csv")


@router.get("/audit")
async def audit_log(search: Optional[str] = None, page: int = 1, page_size: int = 40,
                    principal: dict = Depends(require("audit:view"))):
    q = {"companyId": COMPANY_ID}
    if search:
        q["$or"] = [{"action": {"$regex": search, "$options": "i"}},
                    {"entity": {"$regex": search, "$options": "i"}},
                    {"actor_name": {"$regex": search, "$options": "i"}}]
    total = await db.audit_logs.count_documents(q)
    skip = (page - 1) * page_size
    logs = await db.audit_logs.find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(page_size).to_list(page_size)
    return {"logs": logs, "total": total, "page": page, "page_size": page_size}
