"""Leads, dispositions, calls (today/history), pipeline, follow-ups, lead 360."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import Response
from lead_import import ImportValidationError, run_lead_import
from lead_import_jobs import (
    create_lead_import_job,
    get_job_error_csv,
    get_job_for_actor,
    job_status_dto,
    sse_response,
)
from pydantic import BaseModel
from typing import Optional, List
from core import (db, COMPANY_ID, require, get_principal, scope_filter, team_member_ids, new_id,
                  now_iso, now_utc, normalize_and_validate_phone, validate_email_optional, audit)
from lead_sources import (
    list_lead_sources,
    source_names,
    is_allowed_source,
    find_source_by_name,
)
from datetime import datetime, timedelta, timezone, time
from routes_reports import IST, ist_today, ist_date, parse_date, date_bounds_iso

router = APIRouter(prefix="/api", tags=["leads"])

PIPELINE_STAGES = ["New", "Contacted", "Qualified", "Proposal", "Won", "Lost"]


# ---------------- Dispositions ----------------
class DispositionIn(BaseModel):
    name: str
    slot: int = 1
    type: str = "carry_forward"
    requires_acw: bool = False
    color: str = "#0EA5E9"
    active: bool = True
    default_pipeline_stage: Optional[str] = None
    converts_to_client: bool = False


def _normalize_disposition_fields(body: DispositionIn) -> dict:
    data = body.model_dump()
    stage = data.get("default_pipeline_stage") or None
    if stage == "" or stage == "none":
        stage = None
    if stage and stage not in PIPELINE_STAGES:
        raise HTTPException(status_code=400, detail="Invalid default_pipeline_stage")
    if data.get("converts_to_client"):
        stage = "Won"
    data["default_pipeline_stage"] = stage
    data["converts_to_client"] = bool(data.get("converts_to_client"))
    return data


def _mapped_stage_for_disposition(disp: dict) -> Optional[str]:
    if disp.get("converts_to_client") or disp.get("name") == "Converted":
        return "Won"
    stage = disp.get("default_pipeline_stage")
    if stage and stage in PIPELINE_STAGES:
        return stage
    return None


@router.get("/dispositions")
async def list_dispositions(principal: dict = Depends(get_principal)):
    docs = await db.dispositions.find({"companyId": COMPANY_ID}, {"_id": 0}).sort("order", 1).to_list(100)
    return {"dispositions": docs}


@router.post("/dispositions")
async def create_disposition(body: DispositionIn, principal: dict = Depends(require("dispositions:create"))):
    did = new_id()
    fields = _normalize_disposition_fields(body)
    doc = {"id": did, "companyId": COMPANY_ID, **fields, "order": body.slot, "created_at": now_iso()}
    await db.dispositions.insert_one(dict(doc))
    await audit(principal, "create", "disposition", did, {"name": body.name})
    return {"disposition": doc}


@router.put("/dispositions/{did}")
async def update_disposition(did: str, body: DispositionIn, principal: dict = Depends(require("dispositions:edit"))):
    fields = _normalize_disposition_fields(body)
    res = await db.dispositions.update_one({"id": did, "companyId": COMPANY_ID},
                                           {"$set": {**fields, "order": body.slot}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    await audit(principal, "update", "disposition", did)
    return {"ok": True}


@router.delete("/dispositions/{did}")
async def delete_disposition(did: str, principal: dict = Depends(require("dispositions:delete"))):
    await db.dispositions.delete_one({"id": did, "companyId": COMPANY_ID})
    await audit(principal, "delete", "disposition", did)
    return {"ok": True}


# ---------------- Lead sources ----------------
class LeadSourceIn(BaseModel):
    name: str
    order: int = 1
    active: bool = True
    creatable: bool = True


@router.get("/lead-sources")
async def get_lead_sources(principal: dict = Depends(get_principal)):
    docs = await list_lead_sources()
    return {"lead_sources": docs}


@router.post("/lead-sources")
async def create_lead_source(body: LeadSourceIn, principal: dict = Depends(require("lead_sources:create"))):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    existing = await find_source_by_name(name)
    if existing:
        raise HTTPException(status_code=400, detail="Lead source already exists")
    sid = new_id()
    doc = {
        "id": sid,
        "companyId": COMPANY_ID,
        "name": name,
        "order": int(body.order or 1),
        "active": bool(body.active),
        "creatable": bool(body.creatable),
        "is_system": False,
        "created_at": now_iso(),
    }
    await db.lead_sources.insert_one(dict(doc))
    await audit(principal, "create", "lead_source", sid, {"name": name})
    return {"lead_source": doc}


@router.put("/lead-sources/{sid}")
async def update_lead_source(sid: str, body: LeadSourceIn, principal: dict = Depends(require("lead_sources:edit"))):
    current = await db.lead_sources.find_one({"id": sid, "companyId": COMPANY_ID}, {"_id": 0})
    if not current:
        raise HTTPException(status_code=404, detail="Not found")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    dup = await db.lead_sources.find_one(
        {"companyId": COMPANY_ID, "name": name, "id": {"$ne": sid}},
        {"_id": 1},
    )
    if dup:
        raise HTTPException(status_code=400, detail="Lead source already exists")
    fields = {
        "name": name,
        "order": int(body.order or 1),
        "active": bool(body.active),
    }
    # System Import stays non-creatable; other rows may toggle creatable
    if current.get("is_system") and current.get("name") == "Import":
        fields["creatable"] = False
    else:
        fields["creatable"] = bool(body.creatable)
    res = await db.lead_sources.update_one(
        {"id": sid, "companyId": COMPANY_ID},
        {"$set": fields},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    await audit(principal, "update", "lead_source", sid)
    return {"ok": True}


@router.delete("/lead-sources/{sid}")
async def delete_lead_source(sid: str, principal: dict = Depends(require("lead_sources:delete"))):
    current = await db.lead_sources.find_one({"id": sid, "companyId": COMPANY_ID}, {"_id": 0})
    if not current:
        raise HTTPException(status_code=404, detail="Not found")
    if current.get("is_system"):
        raise HTTPException(status_code=400, detail="System lead sources cannot be deleted")
    await db.lead_sources.delete_one({"id": sid, "companyId": COMPANY_ID})
    await audit(principal, "delete", "lead_source", sid)
    return {"ok": True}


# ---------------- Leads ----------------
class LeadIn(BaseModel):
    name: str
    phone: str
    email: Optional[str] = ""
    source: Optional[str] = "Manual"
    city: Optional[str] = ""
    assigned_to: Optional[str] = None
    custom_fields: dict = {}


class AssignIn(BaseModel):
    lead_ids: List[str]
    agent_id: str


class AutoAssignAllocationIn(BaseModel):
    agent_id: str
    count: int


class AutoAssignIn(BaseModel):
    max_leads: Optional[int] = None
    allocations: Optional[List[AutoAssignAllocationIn]] = None


CSV_TEMPLATE_ROWS = [
    ("Sample Website", "9876543210", "sample@example.com", "Mumbai", "Website"),
    ("Sample Facebook Ads", "9876543211", "sample@example.com", "Mumbai", "Facebook Ads"),
    ("Sample Google Ads", "9876543212", "sample@example.com", "Mumbai", "Google Ads"),
    ("Sample Referral", "9876543213", "sample@example.com", "Mumbai", "Referral"),
    ("Sample Cold List", "9876543214", "sample@example.com", "Mumbai", "Cold List"),
    ("Sample Webinar", "9876543215", "sample@example.com", "Mumbai", "Webinar"),
    ("Sample Manual", "9876543216", "sample@example.com", "Mumbai", "Manual"),
    ("Sample Import", "9876543217", "sample@example.com", "Mumbai", "Import"),
]
CSV_TEMPLATE = "name,phone,email,city,source\n" + "\n".join(
    f"{name},{phone},{email},{city},{source}" for name, phone, email, city, source in CSV_TEMPLATE_ROWS
) + "\n"


async def _validate_lead_source(source: str, *, allow_import: bool = False) -> str:
    s = (source or "Manual").strip()
    if not await is_allowed_source(s, allow_non_creatable=allow_import):
        raise HTTPException(status_code=400, detail="Invalid source")
    return s


async def _parse_lead_input(body: LeadIn, *, allow_import_source: bool = False) -> dict:
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    try:
        phone = normalize_and_validate_phone(body.phone)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        email = validate_email_optional(body.email)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    source = await _validate_lead_source(body.source, allow_import=allow_import_source)
    return {"name": name, "phone": phone, "email": email, "source": source, "city": (body.city or "").strip()}


async def _scoped_leads_query(principal: dict) -> dict:
    return {"companyId": COMPANY_ID, **await scope_filter(principal, "assigned_to")}


def _apply_lead_filters(q: dict, *, search: Optional[str] = None, status: Optional[str] = None,
                        disposition: Optional[str] = None, assigned_to: Optional[str] = None,
                        assignment_status: Optional[str] = None, stage: Optional[str] = None,
                        source: Optional[str] = None, skip_assignment_status: bool = False) -> dict:
    if search:
        q["$or"] = [{"name": {"$regex": search, "$options": "i"}},
                    {"phone": {"$regex": search, "$options": "i"}},
                    {"email": {"$regex": search, "$options": "i"}}]
    if status:
        q["status"] = status
    if disposition == "__none__":
        q["disposition_name"] = None
    elif disposition:
        q["disposition_name"] = disposition
    if not skip_assignment_status:
        if assigned_to:
            q["assigned_to"] = assigned_to
        elif assignment_status == "unassigned":
            q["assigned_to"] = None
        elif assignment_status == "assigned":
            q["assigned_to"] = {"$ne": None}
    elif assigned_to:
        q["assigned_to"] = assigned_to
    if stage:
        q["pipeline_stage"] = stage
    if source:
        q["source"] = source
    return q


async def _agent_assigned_today_map(agents: list, today: str) -> dict:
    result = {}
    for agent in agents:
        result[agent["id"]] = await db.leads.count_documents(
            {"assigned_to": agent["id"], "assigned_date": today})
    return result


async def _auto_assign_plan(
    max_leads: Optional[int],
    dry_run: bool = False,
    allocations: Optional[List[AutoAssignAllocationIn]] = None,
) -> dict:
    """Compute or execute equal (round-robin) auto-assign from the unassigned pool.

    When `allocations` is provided, assign exactly those per-agent counts (validated
    against remaining daily slots and pool size). Otherwise distribute `max_leads`
    (or the full pool) equally among callers with remaining quota.
    """
    from auto_assign import plan_equal_assignments, build_by_agent_from_allocations

    agents = await db.users.find({"companyId": COMPANY_ID, "user_type": "caller", "active": True},
                                 {"_id": 0}).to_list(100)
    if not agents:
        raise HTTPException(status_code=400, detail="No active callers")
    today = now_utc().date().isoformat()
    pool = await db.leads.find(
        {"companyId": COMPANY_ID, "status": "active", "is_client": False, "assigned_to": None},
        {"_id": 0}).to_list(5000)
    pool_size = len(pool)
    assigned_today_map = await _agent_assigned_today_map(agents, today)
    agents_by_id = {a["id"]: a for a in agents}

    if allocations is not None:
        allocation_counts: dict = {}
        for item in allocations:
            if item.count < 0:
                raise HTTPException(status_code=400, detail="Allocation count cannot be negative")
            if item.agent_id not in agents_by_id:
                raise HTTPException(status_code=400, detail=f"Unknown or inactive agent: {item.agent_id}")
            allocation_counts[item.agent_id] = allocation_counts.get(item.agent_id, 0) + int(item.count)

        by_agent = build_by_agent_from_allocations(agents, assigned_today_map, allocation_counts)
        for row in by_agent:
            if row["assigned"] > row["slots_available"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Allocation for {row['agent_name']} ({row['assigned']}) exceeds slots ({row['slots_available']})",
                )
        total_requested = sum(int(r["assigned"]) for r in by_agent)
        if total_requested > pool_size:
            raise HTTPException(
                status_code=400,
                detail=f"Allocations sum ({total_requested}) exceeds unassigned pool ({pool_size})",
            )
        requested = max_leads if max_leads is not None else total_requested
    else:
        cap = min(max(0, max_leads), pool_size) if max_leads is not None else pool_size
        by_agent = plan_equal_assignments(agents, assigned_today_map, cap)
        total_requested = sum(int(r["assigned"]) for r in by_agent)
        requested = max_leads

    # Execute assignments in by_agent order (deterministic name/id sort)
    total_assigned = 0
    idx = 0
    for row in by_agent:
        need = int(row["assigned"])
        got = 0
        for _ in range(need):
            if idx >= len(pool):
                break
            lead = pool[idx]
            idx += 1
            got += 1
            total_assigned += 1
            if not dry_run:
                await db.leads.update_one({"id": lead["id"]}, {"$set": {
                    "assigned_to": row["agent_id"], "assigned_name": row["agent_name"],
                    "owner_id": row["agent_id"], "assigned_date": today}})
        row["assigned"] = got

    return {
        "assigned": total_assigned,
        "requested": requested,
        "available_in_pool": pool_size,
        "by_agent": [a for a in by_agent if a["slots_available"] > 0 or a["assigned"] > 0],
    }


@router.get("/leads")
async def list_leads(search: Optional[str] = None, status: Optional[str] = None,
                     disposition: Optional[str] = None, assigned_to: Optional[str] = None,
                     assignment_status: Optional[str] = None, stage: Optional[str] = None,
                     source: Optional[str] = None, sort: Optional[str] = None,
                     page: int = 1, page_size: int = 25,
                     principal: dict = Depends(require("leads:view"))):
    q = await _scoped_leads_query(principal)
    skip_assignment = principal.get("data_scope") == "OWN"
    _apply_lead_filters(q, search=search, status=status, disposition=disposition,
                        assigned_to=assigned_to, assignment_status=assignment_status,
                        stage=stage, source=source, skip_assignment_status=skip_assignment)
    total = await db.leads.count_documents(q)
    skip = (page - 1) * page_size
    sort_map = {
        "created_at_asc": [("created_at", 1)],
        "name_asc": [("name", 1)],
        "updated_at_desc": [("updated_at", -1)],
        "created_at_desc": [("created_at", -1)],
    }
    sort_spec = sort_map.get(sort or "created_at_desc", [("created_at", -1)])
    leads = await db.leads.find(q, {"_id": 0}).sort(sort_spec).skip(skip).limit(page_size).to_list(page_size)
    return {"leads": leads, "total": total, "page": page, "page_size": page_size}


@router.post("/leads")
async def create_lead(body: LeadIn, principal: dict = Depends(require("leads:create"))):
    parsed = await _parse_lead_input(body)
    if await db.leads.find_one({"companyId": COMPANY_ID, "phone": parsed["phone"]}):
        raise HTTPException(status_code=400, detail="A lead with this phone already exists")
    assigned = body.assigned_to
    assigned_name = None
    owner_id = None
    assigned_date = None
    if assigned:
        au = await db.users.find_one({"id": assigned}, {"_id": 0, "name": 1})
        if not au:
            raise HTTPException(status_code=404, detail="Agent not found")
        assigned_name = au["name"]
        owner_id = assigned
        assigned_date = now_utc().date().isoformat()
    lid = new_id()
    doc = {"id": lid, "companyId": COMPANY_ID, "name": parsed["name"], "phone": parsed["phone"],
           "email": parsed["email"], "source": parsed["source"], "city": parsed["city"],
           "status": "active", "assigned_to": assigned,
           "assigned_name": assigned_name, "owner_id": owner_id,
           "disposition_id": None, "disposition_name": None, "carry_forward": True,
           "pipeline_stage": "New", "custom_fields": body.custom_fields,
           "follow_up_at": None, "is_client": False, "client_id": None,
           "assigned_date": assigned_date,
           "last_notes": None, "last_notes_at": None,
           "created_at": now_iso(), "updated_at": now_iso()}
    await db.leads.insert_one(dict(doc))
    await audit(principal, "create", "lead", lid, {"name": parsed["name"]})
    return {"lead": doc}


@router.get("/leads/assignable-callers")
async def assignable_callers(principal: dict = Depends(require("leads:assign"))):
    """Callers the principal may assign to, respecting data scope."""
    q = {"companyId": COMPANY_ID, "user_type": "caller", "active": True}
    if principal.get("data_scope") == "TEAM":
        q["id"] = {"$in": await team_member_ids(principal)}
    elif principal.get("data_scope") == "OWN":
        q["id"] = principal["id"]
    users = await db.users.find(q, {"_id": 0, "password_hash": 0}).to_list(500)
    return {"users": users}


@router.get("/leads/tab-counts")
async def leads_tab_counts(principal: dict = Depends(require("leads:view"))):
    base = await _scoped_leads_query(principal)
    if principal.get("data_scope") == "OWN":
        assigned = await db.leads.count_documents(base)
        return {"unassigned": 0, "assigned": assigned}
    unassigned = await db.leads.count_documents({**base, "assigned_to": None})
    assigned = await db.leads.count_documents({**base, "assigned_to": {"$ne": None}})
    return {"unassigned": unassigned, "assigned": assigned}


@router.get("/leads/filter-options")
async def leads_filter_options(principal: dict = Depends(require("leads:view"))):
    dispositions = await db.dispositions.find(
        {"companyId": COMPANY_ID, "active": True}, {"_id": 0, "id": 1, "name": 1}
    ).sort("order", 1).to_list(100)
    sources = await source_names(active_only=True, creatable_only=False)
    sources_creatable = await source_names(active_only=True, creatable_only=True)
    return {
        "stages": PIPELINE_STAGES,
        "sources": sources,
        "sources_creatable": sources_creatable,
        "dispositions": dispositions,
    }


@router.get("/leads/auto-assign/preview")
async def auto_assign_preview(max_leads: Optional[int] = None,
                              principal: dict = Depends(require("leads:assign"))):
    result = await _auto_assign_plan(max_leads, dry_run=True)
    return result


def _ensure_csv_filename(filename: Optional[str]):
    name = (filename or "").lower()
    if not name.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")


@router.get("/leads/import/template")
async def import_template(principal: dict = Depends(require("leads:import"))):
    return Response(
        content=CSV_TEMPLATE,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="leads_import_template.csv"'},
    )


@router.post("/leads/import-jobs", status_code=202)
async def create_import_job(file: UploadFile = File(...), principal: dict = Depends(require("leads:import"))):
    _ensure_csv_filename(file.filename)
    raw = await file.read()
    try:
        queued = await create_lead_import_job(raw, file.filename or "leads.csv", principal["id"])
    except ImportValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await audit(principal, "import-job", "lead", queued["jobId"], {"file_name": file.filename})
    return queued


@router.get("/leads/import-jobs/{job_id}/events")
async def import_job_events(job_id: str, principal: dict = Depends(require("leads:import"))):
    await get_job_for_actor(job_id, principal["id"])
    return sse_response(job_id)


@router.get("/leads/import-jobs/{job_id}/errors.csv")
async def import_job_error_csv(job_id: str, principal: dict = Depends(require("leads:import"))):
    file_name, csv_text = await get_job_error_csv(job_id, principal["id"])
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@router.get("/leads/import-jobs/{job_id}")
async def import_job_status(job_id: str, principal: dict = Depends(require("leads:import"))):
    job = await get_job_for_actor(job_id, principal["id"])
    return job_status_dto(job)


@router.get("/leads/{lid}")
async def lead_360(lid: str, principal: dict = Depends(require("leads:view"))):
    lead = await db.leads.find_one({"id": lid, "companyId": COMPANY_ID}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    calls = await db.calls.find({"lead_id": lid}, {"_id": 0}).sort("created_at", -1).to_list(200)
    client = await db.clients.find_one({"lead_id": lid}, {"_id": 0})
    activity = await db.audit_logs.find(
        {
            "companyId": COMPANY_ID,
            "$or": [
                {"entity_id": lid},
                {"meta.lead_id": lid},
            ],
        },
        {"_id": 0},
    ).sort("created_at", -1).to_list(100)
    return {"lead": lead, "calls": calls, "client": client, "activity": activity}


@router.put("/leads/{lid}")
async def update_lead(lid: str, body: LeadIn, principal: dict = Depends(require("leads:edit"))):
    parsed = await _parse_lead_input(body)
    dup = await db.leads.find_one(
        {"companyId": COMPANY_ID, "phone": parsed["phone"], "id": {"$ne": lid}})
    if dup:
        raise HTTPException(status_code=400, detail="A lead with this phone already exists")
    upd = {"name": parsed["name"], "phone": parsed["phone"], "email": parsed["email"],
           "source": parsed["source"], "city": parsed["city"],
           "custom_fields": body.custom_fields, "updated_at": now_iso()}
    if body.assigned_to:
        au = await db.users.find_one({"id": body.assigned_to}, {"_id": 0, "name": 1})
        upd["assigned_to"] = body.assigned_to
        upd["assigned_name"] = au["name"] if au else None
        upd["owner_id"] = body.assigned_to
        upd["assigned_date"] = now_utc().date().isoformat()
    res = await db.leads.update_one({"id": lid, "companyId": COMPANY_ID}, {"$set": upd})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found")
    await audit(principal, "update", "lead", lid)
    return {"ok": True}


@router.delete("/leads/{lid}")
async def delete_lead(lid: str, principal: dict = Depends(require("leads:delete"))):
    await db.leads.delete_one({"id": lid, "companyId": COMPANY_ID})
    await audit(principal, "delete", "lead", lid)
    return {"ok": True}


@router.post("/leads/assign")
async def assign_leads(body: AssignIn, principal: dict = Depends(require("leads:assign"))):
    au = await db.users.find_one({"id": body.agent_id}, {"_id": 0, "name": 1})
    if not au:
        raise HTTPException(status_code=404, detail="Agent not found")
    res = await db.leads.update_many(
        {"id": {"$in": body.lead_ids}, "companyId": COMPANY_ID},
        {"$set": {"assigned_to": body.agent_id, "assigned_name": au["name"],
                  "owner_id": body.agent_id, "assigned_date": now_utc().date().isoformat()}})
    await audit(principal, "assign", "lead", None, {"count": res.modified_count, "agent": au["name"]})
    return {"assigned": res.modified_count}


@router.post("/leads/auto-assign")
async def auto_assign(body: AutoAssignIn = AutoAssignIn(),
                      principal: dict = Depends(require("leads:assign"))):
    """Distribute unassigned/pooled leads to active callers up to their daily quota."""
    result = await _auto_assign_plan(
        body.max_leads, dry_run=False, allocations=body.allocations)
    await audit(principal, "auto-assign", "lead", None, {"count": result["assigned"]})
    return result


@router.post("/leads/import")
async def import_leads(file: UploadFile = File(...), principal: dict = Depends(require("leads:import"))):
    _ensure_csv_filename(file.filename)
    raw = await file.read()
    try:
        result = await run_lead_import(raw)
    except ImportValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await audit(principal, "import", "lead", None, {
        "created": result.created, "dupes": result.duplicates, "invalid": result.invalid,
    })
    return {"created": result.created, "duplicates": result.duplicates, "invalid": result.invalid}


# ---------------- Today Calls & disposition logging ----------------
class LogCallIn(BaseModel):
    lead_id: str
    disposition_id: str
    outcome: str = "connected"
    notes: str = ""
    duration: int = 0
    follow_up_at: Optional[str] = None
    pipeline_stage: Optional[str] = None
    deposit_amount: Optional[float] = None


@router.get("/today-calls")
async def today_calls(principal: dict = Depends(require("today_calls:view"))):
    """Calls workbench: overdue / due-today / assigned-today / upcoming (7d), RBAC-scoped."""
    from datetime import date as date_cls

    today = ist_today()
    today_s = today.isoformat()
    now = now_utc()
    upcoming_end = datetime.combine(today + timedelta(days=7), time.max, tzinfo=IST).astimezone(timezone.utc)

    scope = await scope_filter(principal, "assigned_to")
    base = {"companyId": COMPANY_ID, "status": "active", "is_client": False, **scope}

    candidates = await db.leads.find({
        **base,
        "$or": [
            {"assigned_date": today_s},
            {"follow_up_at": {"$ne": None, "$lte": upcoming_end.isoformat()}},
        ],
    }, {"_id": 0}).to_list(5000)

    buckets = {"overdue": [], "due_today": [], "assigned_today": [], "upcoming": []}
    seen = set()

    def annotate(lead, reason):
        item = dict(lead)
        item["queue_reason"] = reason
        fu = lead.get("follow_up_at")
        days_overdue = None
        hours_until = None
        if fu:
            try:
                dt = datetime.fromisoformat(fu)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                fu_day = ist_date(fu)
                if reason == "overdue" and fu_day:
                    days_overdue = max(1, (today - date_cls.fromisoformat(fu_day)).days)
                elif reason in ("due_today", "upcoming"):
                    hours_until = round((dt - now).total_seconds() / 3600, 1)
            except Exception:
                pass
        item["days_overdue"] = days_overdue
        item["hours_until"] = hours_until
        return item

    for lead in candidates:
        fu = lead.get("follow_up_at")
        if not fu:
            continue
        fu_day = ist_date(fu)
        if not fu_day or fu_day >= today_s:
            continue
        lid = lead["id"]
        if lid in seen:
            continue
        seen.add(lid)
        buckets["overdue"].append(annotate(lead, "overdue"))

    for lead in candidates:
        fu = lead.get("follow_up_at")
        if not fu:
            continue
        fu_day = ist_date(fu)
        if fu_day != today_s:
            continue
        lid = lead["id"]
        if lid in seen:
            continue
        seen.add(lid)
        buckets["due_today"].append(annotate(lead, "due_today"))

    # Assigned today: today's assignment with no pending FU (future FU → upcoming)
    for lead in candidates:
        if lead.get("assigned_date") != today_s:
            continue
        lid = lead["id"]
        if lid in seen:
            continue
        fu = lead.get("follow_up_at")
        if fu:
            continue
        seen.add(lid)
        buckets["assigned_today"].append(annotate(lead, "assigned_today"))

    for lead in candidates:
        fu = lead.get("follow_up_at")
        if not fu:
            continue
        fu_day = ist_date(fu)
        if not fu_day or fu_day <= today_s:
            continue
        try:
            dt = datetime.fromisoformat(fu)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt > upcoming_end:
                continue
        except Exception:
            continue
        lid = lead["id"]
        if lid in seen:
            continue
        seen.add(lid)
        buckets["upcoming"].append(annotate(lead, "upcoming"))

    def sort_key_fu(item):
        return item.get("follow_up_at") or ""

    buckets["overdue"].sort(key=sort_key_fu)
    buckets["due_today"].sort(key=sort_key_fu)
    buckets["assigned_today"].sort(key=lambda x: (x.get("name") or "").lower())
    buckets["upcoming"].sort(key=sort_key_fu)

    for key in buckets:
        buckets[key] = buckets[key][:500]

    flat = (
        buckets["overdue"]
        + buckets["due_today"]
        + buckets["assigned_today"]
        + buckets["upcoming"]
    )

    # Called today: unique leads this principal logged a call on (IST today). Not in flat `leads`.
    today_calls_rows = []
    for c in await db.calls.find(
        {"companyId": COMPANY_ID, "agent_id": principal["id"]},
        {"_id": 0, "lead_id": 1, "created_at": 1},
    ).to_list(100000):
        if ist_date(c.get("created_at")) == today_s and c.get("lead_id"):
            today_calls_rows.append(c)
    today_calls_rows.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    called_ids = []
    seen_called = set()
    for c in today_calls_rows:
        lid = c["lead_id"]
        if lid in seen_called:
            continue
        seen_called.add(lid)
        called_ids.append(lid)

    called_bucket = []
    if called_ids:
        lead_docs = await db.leads.find(
            {"companyId": COMPANY_ID, "id": {"$in": called_ids[:500]}},
            {"_id": 0},
        ).to_list(500)
        by_id = {l["id"]: l for l in lead_docs}
        for lid in called_ids[:500]:
            lead = by_id.get(lid)
            if not lead:
                continue
            called_bucket.append(annotate(lead, "called_today"))
    buckets["called_today"] = called_bucket

    fresh = await db.users.find_one({"id": principal["id"]}, {"_id": 0, "acw_pending_lead_id": 1})
    acw = fresh.get("acw_pending_lead_id") if fresh else principal.get("acw_pending_lead_id")

    return {
        "date": today_s,
        "acw_pending_lead_id": acw,
        "counts": {
            "overdue": len(buckets["overdue"]),
            "due_today": len(buckets["due_today"]),
            "assigned_today": len(buckets["assigned_today"]),
            "upcoming": len(buckets["upcoming"]),
            "called_today": len(buckets["called_today"]),
        },
        "tab_counts": {
            "queue": len(flat),
            "acw_pending": 1 if acw else 0,
        },
        "buckets": buckets,
        "leads": flat,
    }


@router.post("/calls/log")
async def log_call(body: LogCallIn, principal: dict = Depends(require("today_calls:log"))):
    lead = await db.leads.find_one({"id": body.lead_id, "companyId": COMPANY_ID}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    disp = await db.dispositions.find_one({"id": body.disposition_id, "companyId": COMPANY_ID}, {"_id": 0})
    if not disp:
        raise HTTPException(status_code=404, detail="Disposition not found")

    # Normalize: blank / missing next FU → clear previous obligation
    next_fu = body.follow_up_at.strip() if isinstance(body.follow_up_at, str) else body.follow_up_at
    if not next_fu:
        next_fu = None

    should_convert = bool(disp.get("converts_to_client")) or disp.get("name") == "Converted"
    if disp.get("name") == "Call Back" and not next_fu and not should_convert:
        raise HTTPException(status_code=400, detail="Follow-up required for Call Back")
    if body.deposit_amount is not None:
        try:
            dep_amt = float(body.deposit_amount)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="deposit_amount must be a number")
        if dep_amt < 0:
            raise HTTPException(status_code=400, detail="deposit_amount must be positive")

    # ACW is non-blocking: track pending separately; never 409 other leads
    fresh = await db.users.find_one({"id": principal["id"]}, {"_id": 0, "acw_pending_lead_id": 1})
    pending = fresh.get("acw_pending_lead_id") if fresh else None

    notes = (body.notes or "").strip()
    call_at = now_iso()
    cid = new_id()
    call = {"id": cid, "companyId": COMPANY_ID, "lead_id": body.lead_id,
            "lead_name": lead["name"], "lead_phone": lead["phone"],
            "agent_id": principal["id"], "agent_name": principal["name"],
            "disposition_id": disp["id"], "disposition_name": disp["name"],
            "outcome": body.outcome, "notes": notes, "duration": body.duration,
            "follow_up_at": next_fu, "created_at": call_at}
    await db.calls.insert_one(dict(call))

    carry = disp["type"] == "carry_forward"
    lead_upd = {"disposition_id": disp["id"], "disposition_name": disp["name"],
                "carry_forward": carry, "follow_up_at": next_fu,
                "last_notes": notes, "last_notes_at": call_at,
                "updated_at": now_iso()}
    mapped_stage = _mapped_stage_for_disposition(disp)
    if mapped_stage:
        if body.pipeline_stage and body.pipeline_stage != mapped_stage:
            raise HTTPException(
                status_code=400,
                detail=f"Disposition '{disp['name']}' maps to pipeline stage {mapped_stage}",
            )
        lead_upd["pipeline_stage"] = mapped_stage
    elif body.pipeline_stage:
        if body.pipeline_stage not in PIPELINE_STAGES:
            raise HTTPException(status_code=400, detail="Invalid pipeline_stage")
        lead_upd["pipeline_stage"] = body.pipeline_stage
    if not carry:
        lead_upd["status"] = "inactive"  # leaves active queue, retained
    if should_convert:
        lead_upd["follow_up_at"] = None
    await db.leads.update_one({"id": body.lead_id}, {"$set": lead_upd})

    # Auto-convert when disposition converts_to_client (or legacy name Converted)
    converted = False
    client_id = lead.get("client_id")
    deposit_posted = False
    ledger_entry_id = None
    if should_convert:
        fresh_lead = await db.leads.find_one({"id": body.lead_id, "companyId": COMPANY_ID}, {"_id": 0})
        if fresh_lead and not fresh_lead.get("is_client"):
            from routes_clients import _create_client_from_lead, _post_conversion_deposit
            client = await _create_client_from_lead(fresh_lead, principal)
            converted = True
            client_id = client["id"]
            dep = await _post_conversion_deposit(
                client_id,
                body.deposit_amount,
                principal,
                idempotency_key=f"convert-deposit:{client_id}:{cid}",
            )
            deposit_posted = bool(dep.get("deposit_posted"))
            ledger_entry_id = (dep.get("entry") or {}).get("id") if dep.get("entry") else None
        elif fresh_lead and fresh_lead.get("is_client"):
            client_id = fresh_lead.get("client_id")
            converted = False
            await db.leads.update_one(
                {"id": body.lead_id}, {"$set": {"follow_up_at": None, "updated_at": now_iso()}},
            )
            if client_id and body.deposit_amount:
                from routes_clients import _post_conversion_deposit
                dep = await _post_conversion_deposit(
                    client_id,
                    body.deposit_amount,
                    principal,
                    idempotency_key=f"convert-deposit:{client_id}:{cid}",
                )
                deposit_posted = bool(dep.get("deposit_posted"))
                ledger_entry_id = (dep.get("entry") or {}).get("id") if dep.get("entry") else None

    # ACW pending is a reminder only: set on ACW disposition; clear only for same lead or complete-acw
    if disp.get("requires_acw"):
        await db.users.update_one({"id": principal["id"]},
                                  {"$set": {"acw_pending_lead_id": body.lead_id}})
    elif not pending or pending == body.lead_id:
        await db.users.update_one({"id": principal["id"]},
                                  {"$set": {"acw_pending_lead_id": None}})
    await audit(principal, "log_call", "lead", body.lead_id, {"disposition": disp["name"]})
    return {
        "call": call,
        "carry_forward": carry,
        "acw": bool(disp.get("requires_acw")),
        "converted": converted,
        "client_id": client_id,
        "deposit_posted": deposit_posted,
        "ledger_entry_id": ledger_entry_id,
    }


@router.post("/calls/complete-acw")
async def complete_acw(principal: dict = Depends(require("today_calls:log"))):
    await db.users.update_one({"id": principal["id"]}, {"$set": {"acw_pending_lead_id": None}})
    return {"ok": True}


@router.get("/call-history")
async def call_history(search: Optional[str] = None, disposition: Optional[str] = None,
                       agent_id: Optional[str] = None,
                       from_date: Optional[str] = Query(None, alias="from"),
                       to_date: Optional[str] = Query(None, alias="to"),
                       sort: Optional[str] = None,
                       page: int = 1, page_size: int = 30,
                       principal: dict = Depends(require("call_history:view"))):
    from_d = parse_date(from_date)
    to_d = parse_date(to_date)
    if from_date and from_d is None:
        raise HTTPException(status_code=400, detail="Invalid from date")
    if to_date and to_d is None:
        raise HTTPException(status_code=400, detail="Invalid to date")
    if from_d and to_d and from_d > to_d:
        raise HTTPException(status_code=400, detail="from must be on or before to")

    q = {"companyId": COMPANY_ID, **await scope_filter(principal, "agent_id")}
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
    total = await db.calls.count_documents(q)
    skip = (page - 1) * page_size
    sort_dir = 1 if sort == "created_at_asc" else -1
    calls = await db.calls.find(q, {"_id": 0}).sort("created_at", sort_dir).skip(skip).limit(page_size).to_list(page_size)
    return {"calls": calls, "total": total, "page": page, "page_size": page_size}


# ---------------- Pipeline ----------------
class StageIn(BaseModel):
    stage: str


@router.get("/pipeline")
async def pipeline(search: Optional[str] = None, source: Optional[str] = None,
                   disposition: Optional[str] = None, assigned_to: Optional[str] = None,
                   principal: dict = Depends(require("pipeline:view"))):
    q = await _scoped_leads_query(principal)
    skip_assignment = principal.get("data_scope") == "OWN"
    _apply_lead_filters(
        q, search=search, source=source, disposition=disposition,
        assigned_to=assigned_to, skip_assignment_status=skip_assignment,
    )
    leads = await db.leads.find(q, {"_id": 0}).sort("updated_at", -1).to_list(2000)
    board = {s: [] for s in PIPELINE_STAGES}
    for l in leads:
        s = l.get("pipeline_stage") or "New"
        if l.get("is_client"):
            s = "Won"
        board.setdefault(s, []).append(l)
    counts = {s: len(board.get(s) or []) for s in PIPELINE_STAGES}
    return {"stages": PIPELINE_STAGES, "board": board, "counts": counts, "total": len(leads)}


@router.put("/pipeline/{lid}")
async def move_stage(lid: str, body: StageIn, principal: dict = Depends(require("pipeline:edit"))):
    if body.stage not in PIPELINE_STAGES:
        raise HTTPException(status_code=400, detail="Invalid stage")
    lead = await db.leads.find_one({"id": lid, "companyId": COMPANY_ID}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.get("is_client") and body.stage != "Won":
        raise HTTPException(status_code=400, detail="Client leads must remain in Won")
    if lead.get("disposition_id"):
        disp = await db.dispositions.find_one(
            {"id": lead["disposition_id"], "companyId": COMPANY_ID}, {"_id": 0}
        )
        mapped = _mapped_stage_for_disposition(disp) if disp else None
        if mapped and mapped != body.stage:
            raise HTTPException(
                status_code=400,
                detail=f"Lead response '{disp['name']}' maps to {mapped}; log a matching response to move",
            )
    res = await db.leads.update_one({"id": lid, "companyId": COMPANY_ID},
                                    {"$set": {"pipeline_stage": body.stage, "updated_at": now_iso()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found")
    await audit(principal, "move_stage", "lead", lid, {"stage": body.stage})
    return {"ok": True}


# ---------------- Follow-ups ----------------
FOLLOWUP_PAGE_SIZE_MAX = 100
FOLLOWUP_BUCKETS = {"all", "overdue", "today", "upcoming"}


def _followup_at_clause(bucket: Optional[str]) -> dict:
    """IST calendar bounds for follow_up_at. Unknown bucket → all."""
    key = (bucket or "all").strip().lower()
    if key not in FOLLOWUP_BUCKETS:
        key = "all"
    clause: dict = {"$ne": None}
    if key == "all":
        return clause
    today = ist_today()
    lo, hi = date_bounds_iso(today, today)
    if key == "overdue":
        clause["$lt"] = lo
    elif key == "today":
        clause["$gte"] = lo
        clause["$lte"] = hi
    else:
        clause["$gt"] = hi
    return clause


@router.get("/followups")
async def followups(page: int = 1, page_size: int = 25, bucket: Optional[str] = None,
                    principal: dict = Depends(require("followups:view"))):
    page = max(1, page)
    page_size = min(FOLLOWUP_PAGE_SIZE_MAX, max(1, page_size))
    q = {
        "companyId": COMPANY_ID,
        "follow_up_at": _followup_at_clause(bucket),
        "is_client": {"$ne": True},
        "status": {"$ne": "converted"},
        **await scope_filter(principal, "assigned_to"),
    }
    total = await db.leads.count_documents(q)
    skip = (page - 1) * page_size
    leads = await db.leads.find(q, {"_id": 0}).sort("follow_up_at", 1).skip(skip).limit(page_size).to_list(page_size)
    return {"followups": leads, "total": total, "page": page, "page_size": page_size}


class FollowupIn(BaseModel):
    follow_up_at: Optional[str] = None


@router.put("/followups/{lid}")
async def set_followup(lid: str, body: FollowupIn, principal: dict = Depends(require("followups:edit"))):
    res = await db.leads.update_one({"id": lid, "companyId": COMPANY_ID},
                                    {"$set": {"follow_up_at": body.follow_up_at, "updated_at": now_iso()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found")
    await audit(principal, "set_followup", "lead", lid)
    return {"ok": True}
