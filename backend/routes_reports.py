"""Reports, dashboards (computed aggregations, IST), CSV export, audit log."""
import io
import csv
from datetime import timedelta, timezone, datetime, time, date
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from typing import Optional, List
from core import (db, COMPANY_ID, require, scope_filter, client_scope_filter, team_member_ids, now_utc)
from lead_constants import LEAD_SOURCES

router = APIRouter(prefix="/api", tags=["reports"])

IST = timezone(timedelta(hours=5, minutes=30))
PIPELINE_STAGES = ["New", "Contacted", "Qualified", "Proposal", "Won", "Lost"]


def ist_date(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(IST).date().isoformat()
    except Exception:
        return None


def ist_today() -> date:
    return now_utc().astimezone(IST).date()


def parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except Exception:
        return None


def csv_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


def date_bounds_iso(from_d: Optional[date], to_d: Optional[date]):
    """Return UTC ISO bounds for created_at filtering (inclusive IST days)."""
    lo = hi = None
    if from_d:
        lo = datetime.combine(from_d, time.min, tzinfo=IST).astimezone(timezone.utc).isoformat()
    if to_d:
        hi = datetime.combine(to_d, time.max, tzinfo=IST).astimezone(timezone.utc).isoformat()
    return lo, hi


def apply_created_range(q: dict, from_d: Optional[date], to_d: Optional[date]) -> dict:
    lo, hi = date_bounds_iso(from_d, to_d)
    if not lo and not hi:
        return q
    rng = {}
    if lo:
        rng["$gte"] = lo
    if hi:
        rng["$lte"] = hi
    q["created_at"] = rng
    return q


def in_range(iso_str, from_d: Optional[date], to_d: Optional[date]) -> bool:
    d = ist_date(iso_str)
    if not d:
        return False
    dd = date.fromisoformat(d)
    if from_d and dd < from_d:
        return False
    if to_d and dd > to_d:
        return False
    return True


@router.get("/dashboard/filter-options")
async def dashboard_filter_options(principal: dict = Depends(require("dashboard:view"))):
    dispositions = await db.dispositions.find(
        {"companyId": COMPANY_ID, "active": True}, {"_id": 0, "id": 1, "name": 1}
    ).sort("order", 1).to_list(100)
    agents = []
    if principal.get("data_scope") != "OWN":
        q = {"companyId": COMPANY_ID, "user_type": "caller", "active": True}
        if principal.get("data_scope") == "TEAM":
            q["id"] = {"$in": await team_member_ids(principal)}
        agents = await db.users.find(q, {"_id": 0, "id": 1, "name": 1}).to_list(500)
    return {
        "stages": PIPELINE_STAGES,
        "sources": LEAD_SOURCES,
        "dispositions": dispositions,
        "agents": agents,
        "statuses": ["active", "inactive", "converted"],
    }


@router.get("/dashboard")
async def dashboard(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    status: Optional[str] = None,
    source: Optional[str] = None,
    stage: Optional[str] = None,
    disposition: Optional[str] = None,
    assignment_status: Optional[str] = None,
    assigned_to: Optional[str] = None,
    principal: dict = Depends(require("dashboard:view")),
):
    from_d = parse_date(from_date)
    to_d = parse_date(to_date)
    if from_date and from_d is None:
        raise HTTPException(status_code=400, detail="Invalid from date")
    if to_date and to_d is None:
        raise HTTPException(status_code=400, detail="Invalid to date")
    if from_d and to_d and from_d > to_d:
        raise HTTPException(status_code=400, detail="from must be on or before to")

    statuses = csv_list(status)
    sources = csv_list(source)
    stages = csv_list(stage)
    dispositions_f = csv_list(disposition)
    is_own = principal.get("data_scope") == "OWN"

    lead_scope = await scope_filter(principal, "assigned_to")
    call_scope = await scope_filter(principal, "agent_id")
    client_scope = await client_scope_filter(principal)

    lq = {"companyId": COMPANY_ID, **lead_scope}
    cq = {"companyId": COMPANY_ID, **call_scope}
    clq = {"companyId": COMPANY_ID, **client_scope}

    # OWN scope: force self, ignore unassigned assignment_status
    if is_own:
        lq["assigned_to"] = principal["id"]
        cq["agent_id"] = principal["id"]
    else:
        if assigned_to:
            lq["assigned_to"] = assigned_to
            cq["agent_id"] = assigned_to
        elif assignment_status == "unassigned":
            lq["assigned_to"] = None
        elif assignment_status == "assigned":
            lq["assigned_to"] = {"$ne": None}

    if statuses:
        lq["status"] = {"$in": statuses} if len(statuses) > 1 else statuses[0]
    if sources:
        lq["source"] = {"$in": sources} if len(sources) > 1 else sources[0]
    if stages:
        lq["pipeline_stage"] = {"$in": stages} if len(stages) > 1 else stages[0]
    if dispositions_f:
        if "__none__" in dispositions_f and len(dispositions_f) == 1:
            lq["disposition_name"] = None
        elif "__none__" in dispositions_f:
            others = [d for d in dispositions_f if d != "__none__"]
            lq["$or"] = [{"disposition_name": None}, {"disposition_name": {"$in": others}}]
        else:
            lq["disposition_name"] = {"$in": dispositions_f} if len(dispositions_f) > 1 else dispositions_f[0]

    apply_created_range(lq, from_d, to_d)
    apply_created_range(cq, from_d, to_d)

    # Default trend window when no dates: this month (or last 30 days fallback handled by UI)
    today = ist_today()
    trend_from = from_d or date(today.year, today.month, 1)
    trend_to = to_d or today

    leads = await db.leads.find(lq, {"_id": 0}).to_list(20000)
    calls = await db.calls.find(cq, {"_id": 0}).to_list(50000)

    # Clients / ledger stay scope-based (not date-filtered on lead create for affiliate KPIs)
    total_clients = await db.clients.count_documents(clq)
    ftd_clients = await db.clients.count_documents({**clq, "ftd_at": {"$ne": None}})
    client_ids = [c["id"] for c in await db.clients.find(clq, {"_id": 0, "id": 1}).to_list(5000)]
    ledger = await db.ledger.find({"client_id": {"$in": client_ids}}, {"_id": 0}).to_list(100000)
    credit = round(sum(e["amount"] for e in ledger if e["type"] == "credit"), 2)
    debit = round(sum(e["amount"] for e in ledger if e["type"] == "debit"), 2)

    total_leads = len(leads)
    active_leads = sum(1 for l in leads if l.get("status") == "active")
    converted_leads = sum(1 for l in leads if l.get("status") == "converted" or l.get("is_client"))
    unassigned_leads = 0 if is_own else sum(1 for l in leads if not l.get("assigned_to"))
    now_iso_cmp = now_utc().isoformat()
    overdue_followups = sum(
        1 for l in leads
        if l.get("follow_up_at") and l.get("status") == "active" and l["follow_up_at"] < now_iso_cmp
    )

    total_calls_all = await db.calls.count_documents({"companyId": COMPANY_ID, **call_scope})
    calls_in_range = len(calls)
    durations = [c.get("duration") or 0 for c in calls]
    avg_call_duration = round(sum(durations) / len(durations), 1) if durations else 0.0

    # calls today (IST) within scope (unfiltered by date params for KPI hint)
    calls_today = 0
    today_s = today.isoformat()
    for c in await db.calls.find({"companyId": COMPANY_ID, **call_scope}, {"_id": 0, "created_at": 1}).to_list(100000):
        if ist_date(c.get("created_at")) == today_s:
            calls_today += 1

    conv_rate = round((converted_leads / total_leads * 100) if total_leads else 0, 1)

    # Status breakdown
    status_counts = {}
    for l in leads:
        s = l.get("status") or "unknown"
        status_counts[s] = status_counts.get(s, 0) + 1
    status_breakdown = [{"status": k, "count": v} for k, v in sorted(status_counts.items(), key=lambda x: -x[1])]

    # Pipeline funnel
    stage_counts = {s: 0 for s in PIPELINE_STAGES}
    for l in leads:
        st = l.get("pipeline_stage") or "New"
        if st not in stage_counts:
            stage_counts[st] = 0
        stage_counts[st] += 1
    pipeline_funnel = []
    prev = None
    for st in PIPELINE_STAGES:
        cnt = stage_counts.get(st, 0)
        rate = round((cnt / prev * 100) if prev else (100.0 if cnt else 0.0), 1)
        pipeline_funnel.append({"stage": st, "count": cnt, "rate_from_prev": rate})
        prev = cnt if cnt else prev

    # Disposition mix (from filtered calls)
    disp_mix = {}
    for c in calls:
        d = c.get("disposition_name") or "Unknown"
        disp_mix[d] = disp_mix.get(d, 0) + 1
    disposition_mix = [{"name": k, "value": v} for k, v in sorted(disp_mix.items(), key=lambda x: -x[1])]

    # Lead last-response breakdown (primary Responses analysis)
    lead_disp_counts = {}
    for l in leads:
        d = l.get("disposition_name") or "__none__"
        lead_disp_counts[d] = lead_disp_counts.get(d, 0) + 1
    lead_disposition_breakdown = []
    for name, cnt in sorted(lead_disp_counts.items(), key=lambda x: -x[1]):
        lead_disposition_breakdown.append({
            "name": name,
            "label": "No response" if name == "__none__" else name,
            "count": cnt,
            "pct": round((cnt / total_leads * 100) if total_leads else 0, 1),
        })

    disp_meta = {
        d["name"]: d
        for d in await db.dispositions.find({"companyId": COMPANY_ID}, {"_id": 0}).to_list(100)
    }
    converted_by_response = sum(
        1 for l in leads
        if l.get("is_client") or l.get("status") == "converted"
        or (l.get("disposition_name") and (
            disp_meta.get(l["disposition_name"], {}).get("converts_to_client")
            or l.get("disposition_name") == "Converted"
        ))
    )
    with_response = sum(1 for l in leads if l.get("disposition_name"))
    carry_forward_count = sum(1 for l in leads if l.get("carry_forward") is True)
    top_response = lead_disposition_breakdown[0] if lead_disposition_breakdown else None
    response_conversion = {
        "converted_leads": converted_leads,
        "converted_by_response": converted_by_response,
        "converted_share_pct": round((converted_leads / total_leads * 100) if total_leads else 0, 1),
        "leads_with_response": with_response,
        "response_coverage_pct": round((with_response / total_leads * 100) if total_leads else 0, 1),
        "carry_forward_count": carry_forward_count,
        "carry_forward_pct": round((carry_forward_count / total_leads * 100) if total_leads else 0, 1),
        "top_response": top_response["label"] if top_response else None,
        "top_response_count": top_response["count"] if top_response else 0,
    }

    # Source breakdown
    source_map = {}
    for l in leads:
        s = l.get("source") or "Unknown"
        if s not in source_map:
            source_map[s] = {"source": s, "leads": 0, "conversions": 0}
        source_map[s]["leads"] += 1
        if l.get("is_client") or l.get("status") == "converted":
            source_map[s]["conversions"] += 1
    source_breakdown = []
    for row in source_map.values():
        row["conversion_rate"] = round((row["conversions"] / row["leads"] * 100) if row["leads"] else 0, 1)
        source_breakdown.append(row)
    source_breakdown.sort(key=lambda x: -x["leads"])

    # Agent performance
    agent_map = {}
    for l in leads:
        aid = l.get("assigned_to")
        if not aid:
            continue
        if aid not in agent_map:
            agent_map[aid] = {
                "agent_id": aid,
                "name": l.get("assigned_name") or "Unknown",
                "leads": 0, "calls": 0, "conversions": 0,
            }
        agent_map[aid]["leads"] += 1
        if l.get("is_client") or l.get("status") == "converted":
            agent_map[aid]["conversions"] += 1
    for c in calls:
        aid = c.get("agent_id")
        if not aid:
            continue
        if aid not in agent_map:
            agent_map[aid] = {
                "agent_id": aid,
                "name": c.get("agent_name") or "Unknown",
                "leads": 0, "calls": 0, "conversions": 0,
            }
        agent_map[aid]["calls"] += 1
        if not agent_map[aid]["name"] or agent_map[aid]["name"] == "Unknown":
            agent_map[aid]["name"] = c.get("agent_name") or agent_map[aid]["name"]
    agent_performance = []
    for row in agent_map.values():
        row["conversion_rate"] = round((row["conversions"] / row["leads"] * 100) if row["leads"] else 0, 1)
        agent_performance.append(row)
    agent_performance.sort(key=lambda x: (-x["conversions"], -x["calls"], -x["leads"]))

    # Daily trend (leads + calls) for range
    daily = {}
    cursor = trend_from
    while cursor <= trend_to:
        daily[cursor.isoformat()] = {"date": cursor.isoformat(), "leads": 0, "calls": 0}
        cursor += timedelta(days=1)
        if len(daily) > 120:
            break
    for l in leads:
        d = ist_date(l.get("created_at"))
        if d in daily:
            daily[d]["leads"] += 1
    for c in calls:
        d = ist_date(c.get("created_at"))
        if d in daily:
            daily[d]["calls"] += 1
    daily_trend = list(daily.values())

    # Backward-compatible calls_trend (last 7 IST days, scope-only)
    seven = {}
    for i in range(6, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        seven[d] = 0
    scoped_calls_for_week = await db.calls.find(
        {"companyId": COMPANY_ID, **call_scope}, {"_id": 0, "created_at": 1}
    ).to_list(100000)
    for c in scoped_calls_for_week:
        d = ist_date(c.get("created_at"))
        if d in seven:
            seven[d] += 1
    calls_trend = [{"date": k[5:], "calls": v} for k, v in seven.items()]

    # Aging / SLA on active leads in filter set
    aging = {"overdue_followup": 0, "no_call_3d": 0, "no_call_7d": 0, "no_call_14d": 0}
    lead_last_call = {}
    lead_ids = [l["id"] for l in leads]
    if lead_ids:
        for c in await db.calls.find(
            {"companyId": COMPANY_ID, "lead_id": {"$in": lead_ids}},
            {"_id": 0, "lead_id": 1, "created_at": 1},
        ).to_list(100000):
            lid = c.get("lead_id")
            ca = c.get("created_at") or ""
            if lid and ca >= lead_last_call.get(lid, ""):
                lead_last_call[lid] = ca
    for l in leads:
        if l.get("status") != "active":
            continue
        if l.get("follow_up_at") and l["follow_up_at"] < now_iso_cmp:
            aging["overdue_followup"] += 1
        last = lead_last_call.get(l["id"])
        created = l.get("created_at")
        ref = last or created
        ref_d = ist_date(ref)
        if not ref_d:
            continue
        age_days = (today - date.fromisoformat(ref_d)).days
        if age_days >= 14:
            aging["no_call_14d"] += 1
        elif age_days >= 7:
            aging["no_call_7d"] += 1
        elif age_days >= 3:
            aging["no_call_3d"] += 1
    aging_sla = [
        {"bucket": "Overdue follow-ups", "count": aging["overdue_followup"]},
        {"bucket": "No call 3–6 days", "count": aging["no_call_3d"]},
        {"bucket": "No call 7–13 days", "count": aging["no_call_7d"]},
        {"bucket": "No call 14+ days", "count": aging["no_call_14d"]},
    ]

    # Insights (max 5)
    insights = []
    if not is_own and unassigned_leads >= max(5, int(total_leads * 0.2)):
        insights.append({
            "severity": "warning",
            "title": "Large unassigned pool",
            "detail": f"{unassigned_leads} leads waiting to be assigned",
            "href_params": {"tab": "unassigned"},
        })
    if overdue_followups > 0:
        insights.append({
            "severity": "critical" if overdue_followups >= 10 else "warning",
            "title": "Overdue follow-ups",
            "detail": f"{overdue_followups} active leads past follow-up time",
            "href_params": {},
        })
    if source_breakdown:
        worst = min(source_breakdown, key=lambda x: x["conversion_rate"] if x["leads"] >= 3 else 999)
        if worst["leads"] >= 3 and worst["conversion_rate"] < 5:
            insights.append({
                "severity": "info",
                "title": f"Low conversion: {worst['source']}",
                "detail": f"{worst['conversion_rate']}% on {worst['leads']} leads",
                "href_params": {"source": worst["source"]},
            })
    if total_leads and conv_rate >= 10:
        insights.append({
            "severity": "info",
            "title": "Healthy conversion",
            "detail": f"{conv_rate}% lead → client in selected filters",
            "href_params": {"status": "converted"},
        })
    insights = insights[:5]

    return {
        "kpis": {
            "total_leads": total_leads,
            "active_leads": active_leads,
            "converted_leads": converted_leads,
            "conversion_rate": conv_rate,
            "unassigned_leads": unassigned_leads,
            "overdue_followups": overdue_followups,
            "total_calls": total_calls_all,
            "calls_in_range": calls_in_range,
            "calls_today": calls_today,
            "avg_call_duration": avg_call_duration,
            "total_clients": total_clients,
            "ftd_clients": ftd_clients,
            "ledger_credit": credit,
            "ledger_debit": debit,
            "net_balance": round(credit - debit, 2),
        },
        "lead_disposition_breakdown": lead_disposition_breakdown,
        "response_conversion": response_conversion,
        "pipeline_funnel": pipeline_funnel,
        "status_breakdown": status_breakdown,
        "disposition_mix": disposition_mix,
        "source_breakdown": source_breakdown,
        "agent_performance": agent_performance,
        "daily_trend": daily_trend,
        "calls_trend": calls_trend,
        "aging_sla": aging_sla,
        "insights": insights,
    }


def _report_date_range(from_date: Optional[str], to_date: Optional[str]):
    from_d = parse_date(from_date)
    to_d = parse_date(to_date)
    if from_date and from_d is None:
        raise HTTPException(status_code=400, detail="Invalid from date")
    if to_date and to_d is None:
        raise HTTPException(status_code=400, detail="Invalid to date")
    if from_d and to_d and from_d > to_d:
        raise HTTPException(status_code=400, detail="from must be on or before to")
    return from_d, to_d


def _created_at_clause(from_d, to_d):
    lo, hi = date_bounds_iso(from_d, to_d)
    if not lo and not hi:
        return {}
    clause = {}
    if lo:
        clause["$gte"] = lo
    if hi:
        clause["$lte"] = hi
    return {"created_at": clause}


@router.get("/reports/caller")
async def caller_report(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    assigned_to: Optional[str] = None,
    principal: dict = Depends(require("reports:view")),
):
    from_d, to_d = _report_date_range(from_date, to_date)
    date_q = _created_at_clause(from_d, to_d)
    scope = await scope_filter(principal, "agent_id")
    agents = await db.users.find({"companyId": COMPANY_ID, "user_type": "caller"}, {"_id": 0}).to_list(500)
    if assigned_to:
        agents = [a for a in agents if a["id"] == assigned_to]
    disp_meta = {
        d["name"]: d
        for d in await db.dispositions.find({"companyId": COMPANY_ID}, {"_id": 0}).to_list(100)
    }
    rows = []
    for a in agents:
        aq = {"companyId": COMPANY_ID, "agent_id": a["id"], **date_q}
        calls_list = await db.calls.find(aq, {"_id": 0, "disposition_name": 1, "outcome": 1}).to_list(50000)
        calls = len(calls_list)
        connected = sum(1 for c in calls_list if c.get("outcome") == "connected")
        disp_counts = {}
        for c in calls_list:
            dn = c.get("disposition_name") or "Unknown"
            disp_counts[dn] = disp_counts.get(dn, 0) + 1
        top_disp = max(disp_counts.items(), key=lambda x: x[1])[0] if disp_counts else None
        converted_disp_calls = sum(
            1 for c in calls_list
            if c.get("disposition_name") == "Converted"
            or (c.get("disposition_name") and disp_meta.get(c["disposition_name"], {}).get("converts_to_client"))
        )
        lq = {"companyId": COMPANY_ID, "assigned_to": a["id"], **date_q}
        leads = await db.leads.count_documents(lq)
        converted = await db.leads.count_documents({**lq, "is_client": True})
        rows.append({
            "agent_id": a["id"],
            "name": a["name"],
            "calls": calls,
            "connected": connected,
            "connect_rate": round((connected / calls * 100) if calls else 0, 1),
            "leads": leads,
            "conversions": converted,
            "conversion_rate": round((converted / leads * 100) if leads else 0, 1),
            "top_disposition": top_disp,
            "converted_responses": converted_disp_calls,
            "disposition_breakdown": [
                {"name": k, "count": v} for k, v in sorted(disp_counts.items(), key=lambda x: -x[1])
            ],
        })
    if principal.get("data_scope") != "ALL" and "agent_id" in scope:
        allowed = scope["agent_id"].get("$in") if isinstance(scope["agent_id"], dict) else [scope["agent_id"]]
        rows = [r for r in rows if r["agent_id"] in allowed]
    rows.sort(key=lambda x: (-x["conversions"], -x["calls"], -x["leads"]))
    total_calls = sum(r["calls"] for r in rows)
    total_connected = sum(r["connected"] for r in rows)
    total_leads = sum(r["leads"] for r in rows)
    total_conversions = sum(r["conversions"] for r in rows)
    total_converted_responses = sum(r["converted_responses"] for r in rows)
    # Company-level disposition mix for caller report
    all_disp = {}
    for r in rows:
        for d in r.get("disposition_breakdown") or []:
            all_disp[d["name"]] = all_disp.get(d["name"], 0) + d["count"]
    disposition_breakdown = [
        {"name": k, "count": v, "pct": round((v / total_calls * 100) if total_calls else 0, 1)}
        for k, v in sorted(all_disp.items(), key=lambda x: -x[1])
    ]
    summary = {
        "total_calls": total_calls,
        "total_connected": total_connected,
        "connect_rate": round((total_connected / total_calls * 100) if total_calls else 0, 1),
        "total_leads": total_leads,
        "total_conversions": total_conversions,
        "conversion_rate": round((total_conversions / total_leads * 100) if total_leads else 0, 1),
        "responses_logged": total_calls,
        "converted_responses": total_converted_responses,
        "converted_response_share": round(
            (total_converted_responses / total_calls * 100) if total_calls else 0, 1
        ),
    }
    return {
        "rows": rows,
        "summary": summary,
        "disposition_breakdown": disposition_breakdown,
        "from": from_d.isoformat() if from_d else None,
        "to": to_d.isoformat() if to_d else None,
    }


@router.get("/reports/affiliate")
async def affiliate_report(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    principal: dict = Depends(require("reports:view")),
):
    from_d, to_d = _report_date_range(from_date, to_date)
    date_q = _created_at_clause(from_d, to_d)
    empty = {
        "rows": [],
        "summary": {"total_clients": 0, "total_ftd": 0, "ftd_rate": 0.0, "total_balance": 0.0},
        "from": from_d.isoformat() if from_d else None,
        "to": to_d.isoformat() if to_d else None,
    }
    q = {"companyId": COMPANY_ID, "user_type": "affiliate"}
    if principal.get("user_type") == "affiliate":
        q["id"] = principal["id"]
    elif principal.get("data_scope") != "ALL":
        return empty
    affs = await db.users.find(q, {"_id": 0}).to_list(500)
    rows = []
    for a in affs:
        cq = {"companyId": COMPANY_ID, "affiliate_id": a["id"], **date_q}
        clients = await db.clients.find(cq, {"_id": 0}).to_list(5000)
        ftd = sum(1 for c in clients if c.get("ftd_at") and (not from_d and not to_d or in_range(c.get("ftd_at"), from_d, to_d)))
        deposits = round(sum(c.get("balance", 0) for c in clients), 2)
        rows.append({
            "affiliate_id": a["id"],
            "name": a["name"],
            "clients": len(clients),
            "ftd": ftd,
            "ftd_rate": round((ftd / len(clients) * 100) if clients else 0, 1),
            "total_balance": deposits,
        })
    rows.sort(key=lambda x: (-x["ftd"], -x["clients"]))
    total_clients = sum(r["clients"] for r in rows)
    total_ftd = sum(r["ftd"] for r in rows)
    total_balance = round(sum(r["total_balance"] for r in rows), 2)
    summary = {
        "total_clients": total_clients,
        "total_ftd": total_ftd,
        "ftd_rate": round((total_ftd / total_clients * 100) if total_clients else 0, 1),
        "total_balance": total_balance,
    }
    return {
        "rows": rows,
        "summary": summary,
        "from": from_d.isoformat() if from_d else None,
        "to": to_d.isoformat() if to_d else None,
    }


@router.get("/reports/company")
async def company_report(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    source: Optional[str] = None,
    principal: dict = Depends(require("reports:view")),
):
    from_d, to_d = _report_date_range(from_date, to_date)
    date_q = _created_at_clause(from_d, to_d)
    q = {"companyId": COMPANY_ID, **date_q}
    if source:
        q["source"] = source
    sources = {}
    async for l in db.leads.find(q, {"_id": 0, "source": 1, "is_client": 1}):
        s = l.get("source") or "Unknown"
        if s not in sources:
            sources[s] = {"source": s, "leads": 0, "conversions": 0}
        sources[s]["leads"] += 1
        if l.get("is_client"):
            sources[s]["conversions"] += 1
    for s in sources.values():
        s["conversion_rate"] = round((s["conversions"] / s["leads"] * 100) if s["leads"] else 0, 1)
    rows = sorted(sources.values(), key=lambda x: -x["leads"])
    total_leads = sum(r["leads"] for r in rows)
    total_conversions = sum(r["conversions"] for r in rows)

    cq = {"companyId": COMPANY_ID, **date_q}
    if source:
        # Limit calls to leads matching source when filter set
        lead_ids = [
            l["id"] for l in await db.leads.find(
                {"companyId": COMPANY_ID, "source": source, **date_q},
                {"_id": 0, "id": 1},
            ).to_list(20000)
        ]
        if lead_ids:
            cq["lead_id"] = {"$in": lead_ids}
        else:
            cq["lead_id"] = "__none__"
    disp_meta = {
        d["name"]: d
        for d in await db.dispositions.find({"companyId": COMPANY_ID}, {"_id": 0}).to_list(100)
    }
    call_docs = await db.calls.find(cq, {"_id": 0, "disposition_name": 1, "outcome": 1}).to_list(50000)
    disp_counts = {}
    connected = 0
    converted_responses = 0
    for c in call_docs:
        dn = c.get("disposition_name") or "Unknown"
        disp_counts[dn] = disp_counts.get(dn, 0) + 1
        if c.get("outcome") == "connected":
            connected += 1
        if dn == "Converted" or disp_meta.get(dn, {}).get("converts_to_client"):
            converted_responses += 1
    responses_logged = len(call_docs)
    disposition_breakdown = [
        {
            "name": k,
            "count": v,
            "pct": round((v / responses_logged * 100) if responses_logged else 0, 1),
            "connected": sum(
                1 for c in call_docs
                if (c.get("disposition_name") or "Unknown") == k and c.get("outcome") == "connected"
            ),
            "conversions": sum(
                1 for c in call_docs
                if (c.get("disposition_name") or "Unknown") == k
                and (k == "Converted" or disp_meta.get(k, {}).get("converts_to_client"))
            ),
        }
        for k, v in sorted(disp_counts.items(), key=lambda x: -x[1])
    ]
    summary = {
        "total_leads": total_leads,
        "total_conversions": total_conversions,
        "conversion_rate": round((total_conversions / total_leads * 100) if total_leads else 0, 1),
        "responses_logged": responses_logged,
        "converted_responses": converted_responses,
        "converted_response_share": round(
            (converted_responses / responses_logged * 100) if responses_logged else 0, 1
        ),
        "connect_rate": round((connected / responses_logged * 100) if responses_logged else 0, 1),
    }
    return {
        "rows": rows,
        "summary": summary,
        "disposition_breakdown": disposition_breakdown,
        "from": from_d.isoformat() if from_d else None,
        "to": to_d.isoformat() if to_d else None,
    }


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
async def export_report(
    kind: str = Query("caller"),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    assigned_to: Optional[str] = None,
    source: Optional[str] = None,
    principal: dict = Depends(require("reports:export")),
):
    if kind == "caller":
        data = (await caller_report(
            from_date=from_date, to_date=to_date, assigned_to=assigned_to, principal=principal
        ))["rows"]
        return _csv_response(
            data,
            ["name", "calls", "connected", "connect_rate", "leads", "conversions",
             "conversion_rate", "top_disposition", "converted_responses"],
            "caller_report.csv",
        )
    if kind == "affiliate":
        data = (await affiliate_report(from_date=from_date, to_date=to_date, principal=principal))["rows"]
        return _csv_response(
            data, ["name", "clients", "ftd", "ftd_rate", "total_balance"], "affiliate_report.csv"
        )
    data = (await company_report(
        from_date=from_date, to_date=to_date, source=source, principal=principal
    ))["rows"]
    return _csv_response(data, ["source", "leads", "conversions", "conversion_rate"], "company_report.csv")


@router.get("/call-history/export")
async def export_calls(
    search: Optional[str] = None, disposition: Optional[str] = None,
    agent_id: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    principal: dict = Depends(require("call_history:export")),
):
    from_d = parse_date(from_date)
    to_d = parse_date(to_date)
    scope = await scope_filter(principal, "agent_id")
    q = {"companyId": COMPANY_ID, **scope}
    if search:
        q["$or"] = [{"lead_name": {"$regex": search, "$options": "i"}},
                    {"lead_phone": {"$regex": search, "$options": "i"}}]
    if disposition:
        q["disposition_name"] = disposition
    if agent_id:
        q["agent_id"] = agent_id
    lo, hi = date_bounds_iso(from_d, to_d)
    if lo or hi:
        q["created_at"] = {}
        if lo:
            q["created_at"]["$gte"] = lo
        if hi:
            q["created_at"]["$lte"] = hi
    calls = await db.calls.find(q, {"_id": 0}).sort("created_at", -1).to_list(50000)
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
