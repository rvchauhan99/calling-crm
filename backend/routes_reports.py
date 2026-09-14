"""Reports, dashboards (computed aggregations, IST), CSV export, audit log."""
import asyncio
import io
import csv
import os
from datetime import timedelta, timezone, datetime, time, date
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from typing import Optional, List
from core import (db, COMPANY_ID, require, scope_filter, client_scope_filter, team_member_ids, now_utc,
                  live_client_filter, live_ledger_filter, reportable_calls_filter, escape_regex,
                  clamp_page_size)
from lead_sources import source_names
from caller_sales import sales_disp_counts

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


async def _agg_groups(collection, match: dict, group_id, extra: Optional[dict] = None, limit: int = 500):
    """Run $match + $group; returns list of {_id, count, ...extra}."""
    group_stage = {"_id": group_id, "count": {"$sum": 1}}
    if extra:
        group_stage.update(extra)
    cursor = collection.aggregate([{"$match": match}, {"$group": group_stage}])
    return await cursor.to_list(limit)


async def _ledger_type_totals(client_ids: list) -> tuple[float, float]:
    if not client_ids:
        return 0.0, 0.0
    credit = debit = 0.0
    async for row in db.ledger.aggregate([
        {"$match": {"client_id": {"$in": client_ids}, **live_ledger_filter()}},
        {"$group": {"_id": "$type", "total": {"$sum": "$amount"}}},
    ]):
        if row["_id"] == "credit":
            credit = float(row.get("total") or 0)
        elif row["_id"] == "debit":
            debit = float(row.get("total") or 0)
    return round(credit, 2), round(debit, 2)


async def _ledger_type_totals_company(match_extra: Optional[dict] = None) -> tuple[float, float]:
    """Ledger totals for company (optional extra match), no client $in list."""
    match = {"companyId": COMPANY_ID, **live_ledger_filter()}
    if match_extra:
        match.update(match_extra)
    credit = debit = 0.0
    async for row in db.ledger.aggregate([
        {"$match": match},
        {"$group": {"_id": "$type", "total": {"$sum": "$amount"}}},
    ]):
        if row["_id"] == "credit":
            credit = float(row.get("total") or 0)
        elif row["_id"] == "debit":
            debit = float(row.get("total") or 0)
    return round(credit, 2), round(debit, 2)


IST_TZ_NAME = "Asia/Kolkata"
AGENT_PERFORMANCE_CAP = 50
DASHBOARD_CACHE_TTL_SEC = int(os.environ.get("DASHBOARD_CACHE_TTL", "30") or "30")
_dashboard_cache: dict = {}


def clear_dashboard_cache():
    _dashboard_cache.clear()


def _ist_day_group_expr(field: str = "$created_at"):
    """Group key = IST calendar day (YYYY-MM-DD) from ISO created_at strings."""
    return {
        "$let": {
            "vars": {
                "dt": {
                    "$dateFromString": {
                        "dateString": field,
                        "onError": None,
                        "onNull": None,
                    },
                },
            },
            "in": {
                "$cond": [
                    {"$eq": ["$$dt", None]},
                    None,
                    {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": "$$dt",
                            "timezone": IST_TZ_NAME,
                        },
                    },
                ],
            },
        },
    }


def _facet_count(rows: list) -> int:
    if not rows:
        return 0
    return int(rows[0].get("n") or 0)


def _dashboard_cache_key(principal: dict, params: dict) -> tuple:
    items = tuple(sorted((k, "" if v is None else str(v)) for k, v in params.items()))
    return (principal.get("id"), principal.get("data_scope"), items)


def _dashboard_cache_get(key: tuple):
    if DASHBOARD_CACHE_TTL_SEC <= 0:
        return None
    entry = _dashboard_cache.get(key)
    if not entry:
        return None
    expires_at, payload = entry
    if datetime.now(timezone.utc).timestamp() >= expires_at:
        _dashboard_cache.pop(key, None)
        return None
    return payload


def _dashboard_cache_set(key: tuple, payload: dict):
    if DASHBOARD_CACHE_TTL_SEC <= 0:
        return
    _dashboard_cache[key] = (
        datetime.now(timezone.utc).timestamp() + DASHBOARD_CACHE_TTL_SEC,
        payload,
    )
    # Soft bound: drop oldest if map grows large
    if len(_dashboard_cache) > 256:
        oldest = min(_dashboard_cache.items(), key=lambda kv: kv[1][0])
        _dashboard_cache.pop(oldest[0], None)


async def _dashboard_leads_bundle(lq: dict, is_own: bool, now_iso_cmp: str, today: date,
                                  trend_from: date, trend_to: date):
    """One leads $facet for KPIs/breakdowns/trend + aging from last_notes_at."""
    facet = {
        "total": [{"$count": "n"}],
        "active": [{"$match": {"status": "active"}}, {"$count": "n"}],
        "converted": [{"$match": {"is_client": True}}, {"$count": "n"}],
        "unassigned": [{"$match": {"assigned_to": None}}, {"$count": "n"}],
        "overdue": [{
            "$match": {
                "status": "active",
                "follow_up_at": {"$ne": None, "$lt": now_iso_cmp},
            },
        }, {"$count": "n"}],
        "with_response": [{
            "$match": {"disposition_name": {"$nin": [None, ""]}},
        }, {"$count": "n"}],
        "carry_forward": [{"$match": {"carry_forward": True}}, {"$count": "n"}],
        "by_status": [{
            "$group": {
                "_id": {"$ifNull": ["$status", "unknown"]},
                "count": {"$sum": 1},
            },
        }],
        "by_stage": [{
            "$group": {
                "_id": {"$ifNull": ["$pipeline_stage", "New"]},
                "count": {"$sum": 1},
            },
        }],
        "by_lead_disp": [{
            "$group": {
                "_id": {"$ifNull": ["$disposition_name", "__none__"]},
                "count": {"$sum": 1},
            },
        }],
        "by_source": [{
            "$group": {
                "_id": {"$ifNull": ["$source", "Unknown"]},
                "count": {"$sum": 1},
                "conversions": {
                    "$sum": {"$cond": [{"$eq": ["$is_client", True]}, 1, 0]},
                },
            },
        }],
        "by_agent": [
            {"$match": {"assigned_to": {"$ne": None}}},
            {"$group": {
                "_id": "$assigned_to",
                "name": {"$first": "$assigned_name"},
                "leads": {"$sum": 1},
                "conversions": {
                    "$sum": {"$cond": [{"$eq": ["$is_client", True]}, 1, 0]},
                },
            }},
        ],
        "daily": [{
            "$group": {
                "_id": _ist_day_group_expr("$created_at"),
                "count": {"$sum": 1},
            },
        }],
    }
    rows = await db.leads.aggregate([{"$match": lq}, {"$facet": facet}]).to_list(1)
    fac = rows[0] if rows else {}

    aging = {"overdue_followup": 0, "no_call_3d": 0, "no_call_7d": 0, "no_call_14d": 0}
    async for l in db.leads.find(
        {**lq, "status": "active"},
        {"_id": 0, "follow_up_at": 1, "created_at": 1, "last_notes_at": 1},
    ):
        if l.get("follow_up_at") and l["follow_up_at"] < now_iso_cmp:
            aging["overdue_followup"] += 1
        ref = l.get("last_notes_at") or l.get("created_at")
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

    return {
        "total_leads": _facet_count(fac.get("total") or []),
        "active_leads": _facet_count(fac.get("active") or []),
        "converted_leads": _facet_count(fac.get("converted") or []),
        "unassigned_leads": 0 if is_own else _facet_count(fac.get("unassigned") or []),
        "overdue_followups": _facet_count(fac.get("overdue") or []),
        "with_response": _facet_count(fac.get("with_response") or []),
        "carry_forward_count": _facet_count(fac.get("carry_forward") or []),
        "status_rows": fac.get("by_status") or [],
        "stage_rows": fac.get("by_stage") or [],
        "lead_disp_rows": fac.get("by_lead_disp") or [],
        "source_rows": fac.get("by_source") or [],
        "lead_agent_rows": fac.get("by_agent") or [],
        "daily_lead_rows": fac.get("daily") or [],
        "aging": aging,
        "trend_from": trend_from,
        "trend_to": trend_to,
    }


async def _dashboard_calls_bundle(cq: dict, call_scope: dict, today: date,
                                  trend_from: date, trend_to: date):
    """Calls $facet for range stats + parallel all-time / today counts."""
    facet = {
        "stats": [{
            "$group": {
                "_id": None,
                "n": {"$sum": 1},
                "avg": {"$avg": "$duration"},
            },
        }],
        "by_disp": [{
            "$group": {
                "_id": {"$ifNull": ["$disposition_name", "Unknown"]},
                "count": {"$sum": 1},
            },
        }],
        "by_agent": [
            {"$match": {"agent_id": {"$ne": None}}},
            {"$group": {
                "_id": "$agent_id",
                "name": {"$first": "$agent_name"},
                "calls": {"$sum": 1},
            }},
        ],
        "daily": [{
            "$group": {
                "_id": _ist_day_group_expr("$created_at"),
                "count": {"$sum": 1},
            },
        }],
    }

    today_lo, today_hi = date_bounds_iso(today, today)
    calls_today_q = {"companyId": COMPANY_ID, **reportable_calls_filter(), **call_scope}
    if today_lo or today_hi:
        calls_today_q["created_at"] = {}
        if today_lo:
            calls_today_q["created_at"]["$gte"] = today_lo
        if today_hi:
            calls_today_q["created_at"]["$lte"] = today_hi

    all_time_q = {"companyId": COMPANY_ID, **reportable_calls_filter(), **call_scope}

    week_from = today - timedelta(days=6)
    need_week_scan = not (trend_from <= week_from and trend_to >= today)
    week_q = {"companyId": COMPANY_ID, **reportable_calls_filter(), **call_scope}
    apply_created_range(week_q, week_from, today)

    async def _week_daily():
        if not need_week_scan:
            return None
        rows = await db.calls.aggregate([
            {"$match": week_q},
            {"$group": {"_id": _ist_day_group_expr("$created_at"), "count": {"$sum": 1}}},
        ]).to_list(14)
        return rows

    facet_rows, total_calls_all, calls_today, week_rows = await asyncio.gather(
        db.calls.aggregate([{"$match": cq}, {"$facet": facet}]).to_list(1),
        db.calls.count_documents(all_time_q),
        db.calls.count_documents(calls_today_q),
        _week_daily(),
    )
    fac = facet_rows[0] if facet_rows else {}
    stats = (fac.get("stats") or [{}])[0] if fac.get("stats") else {}
    return {
        "calls_in_range": int(stats.get("n") or 0),
        "avg_call_duration": round(float(stats.get("avg") or 0), 1) if stats.get("n") else 0.0,
        "disp_rows": fac.get("by_disp") or [],
        "call_agent_rows": fac.get("by_agent") or [],
        "daily_call_rows": fac.get("daily") or [],
        "total_calls_all": total_calls_all,
        "calls_today": calls_today,
        "week_rows": week_rows,
        "week_from": week_from,
        "need_week_scan": need_week_scan,
        "trend_from": trend_from,
        "trend_to": trend_to,
    }


async def _dashboard_finance_bundle(clq: dict, principal: dict):
    total_clients, ftd_clients = await asyncio.gather(
        db.clients.count_documents(clq),
        db.clients.count_documents({**clq, "ftd_at": {"$ne": None}}),
    )
    # ALL scope: aggregate ledger by company without fetching client ids
    if principal.get("data_scope") == "ALL" and principal.get("user_type") != "affiliate":
        credit, debit = await _ledger_type_totals_company()
    else:
        client_ids = [c["id"] for c in await db.clients.find(clq, {"_id": 0, "id": 1}).to_list(5000)]
        credit, debit = await _ledger_type_totals(client_ids)
    return {
        "total_clients": total_clients,
        "ftd_clients": ftd_clients,
        "credit": credit,
        "debit": debit,
    }


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
        "sources": await source_names(active_only=True, creatable_only=False),
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
    fresh: Optional[int] = Query(None, description="Set to 1 to bypass short TTL cache"),
    principal: dict = Depends(require("dashboard:view")),
):
    cache_key = _dashboard_cache_key(principal, {
        "from": from_date, "to": to_date, "status": status, "source": source,
        "stage": stage, "disposition": disposition,
        "assignment_status": assignment_status, "assigned_to": assigned_to,
    })
    if not fresh:
        cached = _dashboard_cache_get(cache_key)
        if cached is not None:
            return cached

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
    cq = {"companyId": COMPANY_ID, **reportable_calls_filter(), **call_scope}
    clq = {"companyId": COMPANY_ID, **live_client_filter(), **client_scope}

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

    today = ist_today()
    trend_from = from_d or date(today.year, today.month, 1)
    trend_to = to_d or today
    now_iso_cmp = now_utc().isoformat()

    leads_b, calls_b, fin_b = await asyncio.gather(
        _dashboard_leads_bundle(lq, is_own, now_iso_cmp, today, trend_from, trend_to),
        _dashboard_calls_bundle(cq, call_scope, today, trend_from, trend_to),
        _dashboard_finance_bundle(clq, principal),
    )

    total_leads = leads_b["total_leads"]
    active_leads = leads_b["active_leads"]
    converted_leads = leads_b["converted_leads"]
    unassigned_leads = leads_b["unassigned_leads"]
    overdue_followups = leads_b["overdue_followups"]
    with_response = leads_b["with_response"]
    carry_forward_count = leads_b["carry_forward_count"]
    conv_rate = round((converted_leads / total_leads * 100) if total_leads else 0, 1)

    status_breakdown = sorted(
        [{"status": r["_id"], "count": r["count"]} for r in leads_b["status_rows"]],
        key=lambda x: -x["count"],
    )

    stage_counts = {s: 0 for s in PIPELINE_STAGES}
    for r in leads_b["stage_rows"]:
        st = r["_id"] or "New"
        stage_counts[st] = stage_counts.get(st, 0) + r["count"]
    pipeline_funnel = []
    prev = None
    for st in PIPELINE_STAGES:
        cnt = stage_counts.get(st, 0)
        rate = round((cnt / prev * 100) if prev else (100.0 if cnt else 0.0), 1)
        pipeline_funnel.append({"stage": st, "count": cnt, "rate_from_prev": rate})
        prev = cnt if cnt else prev

    disposition_mix = sorted(
        [{"name": r["_id"], "value": r["count"]} for r in calls_b["disp_rows"]],
        key=lambda x: -x["value"],
    )

    lead_disposition_breakdown = []
    for r in sorted(leads_b["lead_disp_rows"], key=lambda x: -x["count"]):
        name = r["_id"]
        lead_disposition_breakdown.append({
            "name": name,
            "label": "No response" if name == "__none__" else name,
            "count": r["count"],
            "pct": round((r["count"] / total_leads * 100) if total_leads else 0, 1),
        })

    top_response = lead_disposition_breakdown[0] if lead_disposition_breakdown else None
    response_conversion = {
        "converted_leads": converted_leads,
        "converted_by_response": converted_leads,
        "converted_share_pct": round((converted_leads / total_leads * 100) if total_leads else 0, 1),
        "leads_with_response": with_response,
        "response_coverage_pct": round((with_response / total_leads * 100) if total_leads else 0, 1),
        "carry_forward_count": carry_forward_count,
        "carry_forward_pct": round((carry_forward_count / total_leads * 100) if total_leads else 0, 1),
        "top_response": top_response["label"] if top_response else None,
        "top_response_count": top_response["count"] if top_response else 0,
    }

    source_breakdown = []
    for r in leads_b["source_rows"]:
        leads_n = r["count"]
        conv_n = r.get("conversions") or 0
        source_breakdown.append({
            "source": r["_id"],
            "leads": leads_n,
            "conversions": conv_n,
            "conversion_rate": round((conv_n / leads_n * 100) if leads_n else 0, 1),
        })
    source_breakdown.sort(key=lambda x: -x["leads"])

    agent_map = {}
    for r in leads_b["lead_agent_rows"]:
        aid = r["_id"]
        if not aid:
            continue
        agent_map[aid] = {
            "agent_id": aid,
            "name": r.get("name") or "Unknown",
            "leads": r["leads"],
            "calls": 0,
            "conversions": r.get("conversions") or 0,
        }
    for r in calls_b["call_agent_rows"]:
        aid = r["_id"]
        if not aid:
            continue
        if aid not in agent_map:
            agent_map[aid] = {
                "agent_id": aid,
                "name": r.get("name") or "Unknown",
                "leads": 0,
                "calls": 0,
                "conversions": 0,
            }
        agent_map[aid]["calls"] = r["calls"]
        if (not agent_map[aid]["name"] or agent_map[aid]["name"] == "Unknown") and r.get("name"):
            agent_map[aid]["name"] = r["name"]
    agent_performance = []
    for row in agent_map.values():
        row["conversion_rate"] = round(
            (row["conversions"] / row["leads"] * 100) if row["leads"] else 0, 1,
        )
        agent_performance.append(row)
    agent_performance.sort(key=lambda x: (-x["conversions"], -x["calls"], -x["leads"]))
    agent_performance = agent_performance[:AGENT_PERFORMANCE_CAP]

    daily = {}
    cursor_d = trend_from
    while cursor_d <= trend_to:
        daily[cursor_d.isoformat()] = {"date": cursor_d.isoformat(), "leads": 0, "calls": 0}
        cursor_d += timedelta(days=1)
        if len(daily) > 120:
            break
    for r in leads_b["daily_lead_rows"]:
        day = r.get("_id")
        if day in daily:
            daily[day]["leads"] = r["count"]
    for r in calls_b["daily_call_rows"]:
        day = r.get("_id")
        if day in daily:
            daily[day]["calls"] = r["count"]
    daily_trend = list(daily.values())

    seven = {}
    for i in range(6, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        seven[d] = 0
    week_source = calls_b["week_rows"] if calls_b["need_week_scan"] else calls_b["daily_call_rows"]
    if week_source:
        for r in week_source:
            day = r.get("_id")
            if day in seven:
                seven[day] = r["count"]
    calls_trend = [{"date": k[5:], "calls": v} for k, v in seven.items()]

    aging = leads_b["aging"]
    aging_sla = [
        {"bucket": "Overdue follow-ups", "count": aging["overdue_followup"]},
        {"bucket": "No call 3–6 days", "count": aging["no_call_3d"]},
        {"bucket": "No call 7–13 days", "count": aging["no_call_7d"]},
        {"bucket": "No call 14+ days", "count": aging["no_call_14d"]},
    ]

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

    credit, debit = fin_b["credit"], fin_b["debit"]
    payload = {
        "kpis": {
            "total_leads": total_leads,
            "active_leads": active_leads,
            "converted_leads": converted_leads,
            "conversion_rate": conv_rate,
            "unassigned_leads": unassigned_leads,
            "overdue_followups": overdue_followups,
            "total_calls": calls_b["total_calls_all"],
            "calls_in_range": calls_b["calls_in_range"],
            "calls_today": calls_b["calls_today"],
            "avg_call_duration": calls_b["avg_call_duration"],
            "total_clients": fin_b["total_clients"],
            "ftd_clients": fin_b["ftd_clients"],
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
    _dashboard_cache_set(cache_key, payload)
    return payload


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


def _lead_attr_filters_active(
    status: Optional[str] = None,
    source: Optional[str] = None,
    stage: Optional[str] = None,
    disposition: Optional[str] = None,
    assignment_status: Optional[str] = None,
    assigned_to: Optional[str] = None,
) -> bool:
    return bool(status or source or stage or disposition or assignment_status or assigned_to)


def _apply_lead_attr_filters(
    lq: dict,
    *,
    status: Optional[str] = None,
    source: Optional[str] = None,
    stage: Optional[str] = None,
    disposition: Optional[str] = None,
    assignment_status: Optional[str] = None,
    assigned_to: Optional[str] = None,
    is_own: bool = False,
    principal_id: Optional[str] = None,
    apply_assignment: bool = True,
) -> dict:
    """Apply dashboard-parity lead attribute filters onto a Mongo match dict."""
    statuses = csv_list(status)
    sources = csv_list(source)
    stages = csv_list(stage)
    dispositions_f = csv_list(disposition)

    if apply_assignment:
        if is_own and principal_id:
            lq["assigned_to"] = principal_id
        else:
            if assigned_to:
                lq["assigned_to"] = assigned_to
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
            # null matches missing; include "" for empty-string dispositions
            lq["disposition_name"] = {"$in": [None, ""]}
        elif "__none__" in dispositions_f:
            others = [d for d in dispositions_f if d != "__none__"]
            lq["$or"] = [
                {"disposition_name": {"$in": [None, ""]}},
                {"disposition_name": {"$in": others}},
            ]
        else:
            lq["disposition_name"] = (
                {"$in": dispositions_f} if len(dispositions_f) > 1 else dispositions_f[0]
            )
    return lq


def _prefix_lead_fields(lead_match: dict) -> dict:
    """Rewrite lead match keys to `_lead.*` after equality $lookup + $unwind."""
    out = {}
    for key, val in lead_match.items():
        if key == "$or":
            out["$or"] = [
                {f"_lead.{sk}": sv for sk, sv in clause.items()}
                for clause in (val or [])
            ]
        elif key.startswith("$"):
            out[key] = val
        else:
            out[f"_lead.{key}"] = val
    return out


def _build_lead_filter(
    *,
    date_q: dict,
    status: Optional[str] = None,
    source: Optional[str] = None,
    stage: Optional[str] = None,
    disposition: Optional[str] = None,
    assignment_status: Optional[str] = None,
    assigned_to: Optional[str] = None,
    is_own: bool = False,
    principal_id: Optional[str] = None,
    apply_assignment: bool = True,
) -> dict:
    lead = {"companyId": COMPANY_ID, **date_q}
    _apply_lead_attr_filters(
        lead,
        status=status,
        source=source,
        stage=stage,
        disposition=disposition,
        assignment_status=assignment_status,
        assigned_to=assigned_to,
        is_own=is_own,
        principal_id=principal_id,
        apply_assignment=apply_assignment,
    )
    return lead


def _agg_calls_by_disposition(
    match_q: dict,
    lead_match: Optional[dict] = None,
    *,
    group_by_agent: bool = False,
):
    """Aggregate calls by disposition/outcome; optional indexed lead join via localField."""
    pipeline = [{"$match": match_q}]
    if lead_match is not None:
        pipeline.extend([
            {"$lookup": {
                "from": "leads",
                "localField": "lead_id",
                "foreignField": "id",
                "as": "_lead",
            }},
            {"$unwind": "$_lead"},
            {"$match": _prefix_lead_fields(lead_match)},
        ])
    group_id = {
        "disposition_name": {"$ifNull": ["$disposition_name", "Unknown"]},
        "outcome": "$outcome",
    }
    group_stage = {"_id": group_id, "n": {"$sum": 1}}
    if group_by_agent:
        group_id["agent_id"] = "$agent_id"
        group_stage["agent_name"] = {"$first": "$agent_name"}
    pipeline.append({"$group": group_stage})
    return db.calls.aggregate(pipeline)


@router.get("/reports/caller")
async def caller_report(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    assigned_to: Optional[str] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
    stage: Optional[str] = None,
    disposition: Optional[str] = None,
    assignment_status: Optional[str] = None,
    principal: dict = Depends(require("reports:view")),
):
    from_d, to_d = _report_date_range(from_date, to_date)
    date_q = _created_at_clause(from_d, to_d)
    scope = await scope_filter(principal, "agent_id")
    is_own = principal.get("data_scope") == "OWN"
    lead_attrs_on = _lead_attr_filters_active(
        status, source, stage, disposition, assignment_status, None,
    )
    agents = await db.users.find(
        {"companyId": COMPANY_ID, "user_type": "caller"}, {"_id": 0, "id": 1, "name": 1},
    ).to_list(500)
    if assigned_to:
        agents = [a for a in agents if a["id"] == assigned_to]
    if is_own:
        agents = [a for a in agents if a["id"] == principal["id"]]
    agent_by_id = {a["id"]: a for a in agents}
    agent_ids = list(agent_by_id.keys())

    disp_meta = {
        d["name"]: d
        for d in await db.dispositions.find({"companyId": COMPANY_ID}, {"_id": 0}).to_list(100)
    }

    # Per-agent call buckets from one aggregation (indexed lead join when filters on)
    call_stats = {aid: {"disp_counts": {}, "connected": 0, "calls": 0} for aid in agent_ids}
    skip_calls = False
    if lead_attrs_on:
        probe = _build_lead_filter(
            date_q=date_q,
            status=status,
            source=source,
            stage=stage,
            disposition=disposition,
            assignment_status=assignment_status if assignment_status == "unassigned" else None,
            apply_assignment=assignment_status == "unassigned",
        )
        if await db.leads.count_documents(probe) == 0:
            skip_calls = True

    if agent_ids and not skip_calls:
        cq = {
            "companyId": COMPANY_ID,
            "agent_id": {"$in": agent_ids},
            **reportable_calls_filter(),
            **date_q,
        }
        if lead_attrs_on and assignment_status != "unassigned":
            pipeline_lead = _build_lead_filter(
                date_q=date_q,
                status=status,
                source=source,
                stage=stage,
                disposition=disposition,
                assignment_status=None,
                apply_assignment=False,
            )
            # Equality lookup + lead attrs + lead assigned to the call's agent
            pipe = [
                {"$match": cq},
                {"$lookup": {
                    "from": "leads",
                    "localField": "lead_id",
                    "foreignField": "id",
                    "as": "_lead",
                }},
                {"$unwind": "$_lead"},
                {"$match": {
                    **_prefix_lead_fields(pipeline_lead),
                    "$expr": {"$eq": ["$_lead.assigned_to", "$agent_id"]},
                }},
                {"$group": {
                    "_id": {
                        "agent_id": "$agent_id",
                        "disposition_name": {"$ifNull": ["$disposition_name", "Unknown"]},
                        "outcome": "$outcome",
                    },
                    "n": {"$sum": 1},
                    "agent_name": {"$first": "$agent_name"},
                }},
            ]
            agg_iter = db.calls.aggregate(pipe)
        elif lead_attrs_on:
            pipeline_lead = _build_lead_filter(
                date_q=date_q,
                status=status,
                source=source,
                stage=stage,
                disposition=disposition,
                assignment_status=assignment_status,
                apply_assignment=True,
            )
            agg_iter = _agg_calls_by_disposition(cq, pipeline_lead, group_by_agent=True)
        else:
            agg_iter = _agg_calls_by_disposition(cq, None, group_by_agent=True)

        async for row in agg_iter:
            key = row.get("_id") or {}
            aid = key.get("agent_id")
            if aid not in call_stats:
                continue
            n = int(row.get("n") or 0)
            call_stats[aid]["calls"] += n
            dn = key.get("disposition_name") or "Unknown"
            call_stats[aid]["disp_counts"][dn] = call_stats[aid]["disp_counts"].get(dn, 0) + n
            if key.get("outcome") == "connected":
                call_stats[aid]["connected"] += n

    # One leads aggregation for per-agent lead/conversion counts
    lead_counts = {aid: {"leads": 0, "conversions": 0} for aid in agent_ids}
    if assignment_status != "unassigned" and agent_ids:
        lq = {"companyId": COMPANY_ID, "assigned_to": {"$in": agent_ids}, **date_q}
        _apply_lead_attr_filters(
            lq,
            status=status,
            source=source,
            stage=stage,
            disposition=disposition,
            assignment_status=assignment_status,
            apply_assignment=False,
        )
        async for row in db.leads.aggregate([
            {"$match": lq},
            {"$group": {
                "_id": "$assigned_to",
                "leads": {"$sum": 1},
                "conversions": {"$sum": {"$cond": [{"$eq": ["$is_client", True]}, 1, 0]}},
            }},
        ]):
            aid = row.get("_id")
            if aid in lead_counts:
                lead_counts[aid]["leads"] = int(row.get("leads") or 0)
                lead_counts[aid]["conversions"] = int(row.get("conversions") or 0)

    rows = []
    for a in agents:
        aid = a["id"]
        stats = call_stats.get(aid) or {"disp_counts": {}, "connected": 0, "calls": 0}
        disp_counts = stats["disp_counts"]
        calls = stats["calls"]
        connected = stats["connected"]
        top_disp = max(disp_counts.items(), key=lambda x: x[1])[0] if disp_counts else None
        converted_disp_calls = sum(
            n for dn, n in disp_counts.items()
            if dn == "Converted" or (dn and disp_meta.get(dn, {}).get("converts_to_client"))
        )
        sales = sales_disp_counts(disp_counts)
        interested = sales["interested"]
        registered = sales["registered"]
        deposite = sales["deposite"]
        conversion_ratio = round((deposite / calls * 100) if calls else 0, 1)
        leads = lead_counts[aid]["leads"] if assignment_status != "unassigned" else 0
        converted = lead_counts[aid]["conversions"] if assignment_status != "unassigned" else 0
        rows.append({
            "agent_id": aid,
            "name": a["name"],
            "interested": interested,
            "registered": registered,
            "deposite": deposite,
            "calls": calls,
            "conversion_ratio": conversion_ratio,
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
    rows.sort(key=lambda x: (-x["deposite"], -x["calls"], -x["interested"]))
    total_calls = sum(r["calls"] for r in rows)
    total_connected = sum(r["connected"] for r in rows)
    total_leads = sum(r["leads"] for r in rows)
    total_conversions = sum(r["conversions"] for r in rows)
    total_converted_responses = sum(r["converted_responses"] for r in rows)
    total_interested = sum(r["interested"] for r in rows)
    total_registered = sum(r["registered"] for r in rows)
    total_deposite = sum(r["deposite"] for r in rows)
    conversion_ratio = round((total_deposite / total_calls * 100) if total_calls else 0, 1)
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
        "total_interested": total_interested,
        "total_registered": total_registered,
        "total_deposite": total_deposite,
        "conversion_ratio": conversion_ratio,
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
    affs = await db.users.find(q, {"_id": 0, "id": 1, "name": 1}).to_list(500)
    rows = []
    for a in affs:
        cq = {"companyId": COMPANY_ID, "affiliate_id": a["id"], **live_client_filter(), **date_q}
        clients_n = await db.clients.count_documents(cq)
        bal_rows = await db.clients.aggregate([
            {"$match": cq},
            {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$balance", 0]}}}},
        ]).to_list(1)
        deposits = round(float(bal_rows[0]["total"]), 2) if bal_rows else 0.0
        ftd_q = {**cq, "ftd_at": {"$ne": None}}
        if from_d or to_d:
            flo, fhi = date_bounds_iso(from_d, to_d)
            ftd_q["ftd_at"] = {"$ne": None}
            if flo or fhi:
                ftd_q["ftd_at"] = {}
                if flo:
                    ftd_q["ftd_at"]["$gte"] = flo
                if fhi:
                    ftd_q["ftd_at"]["$lte"] = fhi
        ftd = await db.clients.count_documents(ftd_q)
        rows.append({
            "affiliate_id": a["id"],
            "name": a["name"],
            "clients": clients_n,
            "ftd": ftd,
            "ftd_rate": round((ftd / clients_n * 100) if clients_n else 0, 1),
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
    status: Optional[str] = None,
    stage: Optional[str] = None,
    disposition: Optional[str] = None,
    assignment_status: Optional[str] = None,
    assigned_to: Optional[str] = None,
    principal: dict = Depends(require("reports:view")),
):
    from_d, to_d = _report_date_range(from_date, to_date)
    date_q = _created_at_clause(from_d, to_d)
    is_own = principal.get("data_scope") == "OWN"
    q = {"companyId": COMPANY_ID, **date_q}
    _apply_lead_attr_filters(
        q,
        status=status,
        source=source,
        stage=stage,
        disposition=disposition,
        assignment_status=assignment_status,
        assigned_to=assigned_to,
        is_own=is_own,
        principal_id=principal.get("id"),
    )
    source_rows = await _agg_groups(
        db.leads, q, {"$ifNull": ["$source", "Unknown"]},
        extra={"conversions": {"$sum": {"$cond": [{"$eq": ["$is_client", True]}, 1, 0]}}},
    )
    rows = []
    for r in source_rows:
        leads_n = r["count"]
        conv_n = r.get("conversions") or 0
        rows.append({
            "source": r["_id"],
            "leads": leads_n,
            "conversions": conv_n,
            "conversion_rate": round((conv_n / leads_n * 100) if leads_n else 0, 1),
        })
    rows.sort(key=lambda x: -x["leads"])
    total_leads = sum(r["leads"] for r in rows)
    total_conversions = sum(r["conversions"] for r in rows)

    cq = {"companyId": COMPANY_ID, **reportable_calls_filter(), **date_q}
    if is_own:
        cq["agent_id"] = principal["id"]
    elif assigned_to:
        cq["agent_id"] = assigned_to
    disp_meta = {
        d["name"]: d
        for d in await db.dispositions.find({"companyId": COMPANY_ID}, {"_id": 0}).to_list(100)
    }
    # per disposition: count + connected via aggregation (no 50k doc materialization)
    per_disp = {}
    connected = 0
    converted_responses = 0
    responses_logged = 0

    lead_attrs_on = _lead_attr_filters_active(
        status, source, stage, disposition, assignment_status, assigned_to if not is_own else None,
    )
    lead_match = None
    skip_calls = False
    if lead_attrs_on:
        lead_match = _build_lead_filter(
            date_q=date_q,
            status=status,
            source=source,
            stage=stage,
            disposition=disposition,
            assignment_status=assignment_status,
            assigned_to=assigned_to,
            is_own=is_own,
            principal_id=principal.get("id"),
        )
        if await db.leads.count_documents(lead_match) == 0:
            skip_calls = True

    if not skip_calls:
        async for row in _agg_calls_by_disposition(cq, lead_match if lead_attrs_on else None):
            n = int(row.get("n") or 0)
            responses_logged += n
            key = row["_id"] or {}
            dn = key.get("disposition_name") or "Unknown"
            bucket = per_disp.setdefault(dn, {"count": 0, "connected": 0})
            bucket["count"] += n
            if key.get("outcome") == "connected":
                bucket["connected"] += n
                connected += n
            if dn == "Converted" or disp_meta.get(dn, {}).get("converts_to_client"):
                converted_responses += n
    disposition_breakdown = [
        {
            "name": k,
            "count": v["count"],
            "pct": round((v["count"] / responses_logged * 100) if responses_logged else 0, 1),
            "connected": v["connected"],
            "conversions": (
                v["count"] if (k == "Converted" or disp_meta.get(k, {}).get("converts_to_client")) else 0
            ),
        }
        for k, v in sorted(per_disp.items(), key=lambda x: -x[1]["count"])
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
    """Sync CSV for small in-memory row lists (report summaries)."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename={filename}"})


async def _csv_stream_from_cursor(cursor, fieldnames, filename, row_map=None, max_rows: int = 50000):
    """Stream CSV rows from an async Mongo cursor without materializing the full list."""
    async def gen():
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        n = 0
        async for doc in cursor:
            row = row_map(doc) if row_map else doc
            w.writerow(row)
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
            n += 1
            if n >= max_rows:
                break

    return StreamingResponse(
        gen(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/reports/export")
async def export_report(
    kind: str = Query("caller"),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    assigned_to: Optional[str] = None,
    source: Optional[str] = None,
    status: Optional[str] = None,
    stage: Optional[str] = None,
    disposition: Optional[str] = None,
    assignment_status: Optional[str] = None,
    principal: dict = Depends(require("reports:export")),
):
    if kind == "caller":
        data = (await caller_report(
            from_date=from_date,
            to_date=to_date,
            assigned_to=assigned_to,
            status=status,
            source=source,
            stage=stage,
            disposition=disposition,
            assignment_status=assignment_status,
            principal=principal,
        ))["rows"]
        return _csv_response(
            data,
            ["name", "interested", "registered", "deposite", "calls", "conversion_ratio"],
            "caller_report.csv",
        )
    if kind == "affiliate":
        data = (await affiliate_report(from_date=from_date, to_date=to_date, principal=principal))["rows"]
        return _csv_response(
            data, ["name", "clients", "ftd", "ftd_rate", "total_balance"], "affiliate_report.csv"
        )
    data = (await company_report(
        from_date=from_date,
        to_date=to_date,
        source=source,
        status=status,
        stage=stage,
        disposition=disposition,
        assignment_status=assignment_status,
        assigned_to=assigned_to,
        principal=principal,
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
        safe = escape_regex(search)
        q["$or"] = [{"lead_name": {"$regex": safe, "$options": "i"}},
                    {"lead_phone": {"$regex": safe, "$options": "i"}}]
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
    fields = ["created_at", "agent_name", "lead_name", "lead_phone",
              "disposition_name", "outcome", "duration", "notes"]
    proj = {"_id": 0, **{f: 1 for f in fields}}
    cursor = db.calls.find(q, proj).sort("created_at", -1)
    return await _csv_stream_from_cursor(cursor, fields, "call_history.csv")


@router.get("/ledger/export")
async def export_ledger(principal: dict = Depends(require("ledger:export"))):
    cfilter = {"companyId": COMPANY_ID, **live_client_filter(), **await client_scope_filter(principal)}
    clients = await db.clients.find(cfilter, {"_id": 0, "id": 1, "name": 1}).to_list(5000)
    client_ids = [c["id"] for c in clients]
    cmap = {c["id"]: c["name"] for c in clients}
    fields = ["created_at", "client_name", "type", "amount",
              "balance_after", "category", "description", "created_by_name"]
    proj = {"_id": 0, "client_id": 1, "created_at": 1, "type": 1, "amount": 1,
            "balance_after": 1, "category": 1, "description": 1, "created_by_name": 1}
    cursor = db.ledger.find(
        {"client_id": {"$in": client_ids}, **live_ledger_filter()}, proj,
    ).sort("created_at", -1)

    def row_map(e):
        out = {k: e.get(k) for k in fields if k != "client_name"}
        out["client_name"] = cmap.get(e.get("client_id"))
        return out

    return await _csv_stream_from_cursor(cursor, fields, "ledger.csv", row_map=row_map)


@router.get("/audit")
async def audit_log(search: Optional[str] = None, page: int = 1, page_size: int = 40,
                    principal: dict = Depends(require("audit:view"))):
    page = max(1, page)
    page_size = clamp_page_size(page_size, 40)
    q = {"companyId": COMPANY_ID}
    if search:
        safe = escape_regex(search)
        q["$or"] = [{"action": {"$regex": safe, "$options": "i"}},
                    {"entity": {"$regex": safe, "$options": "i"}},
                    {"actor_name": {"$regex": safe, "$options": "i"}}]
    total = await db.audit_logs.count_documents(q)
    skip = (page - 1) * page_size
    logs = await db.audit_logs.find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(page_size).to_list(page_size)
    return {"logs": logs, "total": total, "page": page, "page_size": page_size}
