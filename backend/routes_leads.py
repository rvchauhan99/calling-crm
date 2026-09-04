"""Leads, dispositions, calls (today/history), pipeline, follow-ups, lead 360."""
import io
import csv
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional, List
from core import (db, COMPANY_ID, require, get_principal, scope_filter, team_member_ids, new_id,
                  now_iso, now_utc, normalize_and_validate_phone, validate_email_optional, audit)
from lead_constants import LEAD_SOURCES, LEAD_SOURCES_CREATABLE

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


@router.get("/dispositions")
async def list_dispositions(principal: dict = Depends(get_principal)):
    docs = await db.dispositions.find({"companyId": COMPANY_ID}, {"_id": 0}).sort("order", 1).to_list(100)
    return {"dispositions": docs}


@router.post("/dispositions")
async def create_disposition(body: DispositionIn, principal: dict = Depends(require("dispositions:create"))):
    did = new_id()
    doc = {"id": did, "companyId": COMPANY_ID, **body.model_dump(), "order": body.slot, "created_at": now_iso()}
    await db.dispositions.insert_one(dict(doc))
    await audit(principal, "create", "disposition", did, {"name": body.name})
    return {"disposition": doc}


@router.put("/dispositions/{did}")
async def update_disposition(did: str, body: DispositionIn, principal: dict = Depends(require("dispositions:edit"))):
    res = await db.dispositions.update_one({"id": did, "companyId": COMPANY_ID},
                                           {"$set": {**body.model_dump(), "order": body.slot}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    await audit(principal, "update", "disposition", did)
    return {"ok": True}


@router.delete("/dispositions/{did}")
async def delete_disposition(did: str, principal: dict = Depends(require("dispositions:delete"))):
    await db.dispositions.delete_one({"id": did, "companyId": COMPANY_ID})
    await audit(principal, "delete", "disposition", did)
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


class AutoAssignIn(BaseModel):
    max_leads: Optional[int] = None


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


def _validate_lead_source(source: str, *, allow_import: bool = False) -> str:
    allowed = LEAD_SOURCES if allow_import else LEAD_SOURCES_CREATABLE
    s = (source or "Manual").strip()
    if s not in allowed:
        raise HTTPException(status_code=400, detail="Invalid source")
    return s


def _parse_lead_input(body: LeadIn, *, allow_import_source: bool = False) -> dict:
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
    source = _validate_lead_source(body.source, allow_import=allow_import_source)
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
        if assignment_status == "unassigned":
            q["assigned_to"] = None
        elif assignment_status == "assigned":
            q["assigned_to"] = {"$ne": None}
        elif assigned_to:
            q["assigned_to"] = assigned_to
    elif assigned_to:
        q["assigned_to"] = assigned_to
    if stage:
        q["pipeline_stage"] = stage
    if source:
        q["source"] = source
    return q


async def _auto_assign_plan(max_leads: Optional[int], dry_run: bool = False) -> dict:
    """Compute or execute quota-based auto-assign from the unassigned pool."""
    agents = await db.users.find({"companyId": COMPANY_ID, "user_type": "caller", "active": True},
                                 {"_id": 0}).to_list(100)
    if not agents:
        raise HTTPException(status_code=400, detail="No active callers")
    today = now_utc().date().isoformat()
    pool = await db.leads.find(
        {"companyId": COMPANY_ID, "status": "active", "is_client": False, "assigned_to": None},
        {"_id": 0}).to_list(5000)
    pool_size = len(pool)
    cap = min(max(0, max_leads), pool_size) if max_leads is not None else pool_size
    by_agent = []
    total_assigned = 0
    idx = 0
    for agent in agents:
        quota = agent.get("daily_quota", 0) or 0
        assigned_today = await db.leads.count_documents(
            {"assigned_to": agent["id"], "assigned_date": today})
        slots = max(0, quota - assigned_today)
        will_assign = 0
        for _ in range(slots):
            if idx >= len(pool) or total_assigned >= cap:
                break
            lead = pool[idx]
            idx += 1
            will_assign += 1
            total_assigned += 1
            if not dry_run:
                await db.leads.update_one({"id": lead["id"]}, {"$set": {
                    "assigned_to": agent["id"], "assigned_name": agent["name"],
                    "owner_id": agent["id"], "assigned_date": today}})
        by_agent.append({
            "agent_id": agent["id"],
            "agent_name": agent["name"],
            "assigned": will_assign,
            "quota": quota,
            "assigned_today_before": assigned_today,
            "slots_available": slots,
        })
        if total_assigned >= cap:
            break
    return {
        "assigned": total_assigned,
        "requested": max_leads,
        "available_in_pool": pool_size,
        "by_agent": [a for a in by_agent if a["slots_available"] > 0 or a["assigned"] > 0],
    }


@router.get("/leads")
async def list_leads(search: Optional[str] = None, status: Optional[str] = None,
                     disposition: Optional[str] = None, assigned_to: Optional[str] = None,
                     assignment_status: Optional[str] = None, stage: Optional[str] = None,
                     source: Optional[str] = None, page: int = 1, page_size: int = 25,
                     principal: dict = Depends(require("leads:view"))):
    q = await _scoped_leads_query(principal)
    skip_assignment = principal.get("data_scope") == "OWN"
    _apply_lead_filters(q, search=search, status=status, disposition=disposition,
                        assigned_to=assigned_to, assignment_status=assignment_status,
                        stage=stage, source=source, skip_assignment_status=skip_assignment)
    total = await db.leads.count_documents(q)
    skip = (page - 1) * page_size
    leads = await db.leads.find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(page_size).to_list(page_size)
    return {"leads": leads, "total": total, "page": page, "page_size": page_size}


@router.post("/leads")
async def create_lead(body: LeadIn, principal: dict = Depends(require("leads:create"))):
    parsed = _parse_lead_input(body)
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
    return {
        "stages": PIPELINE_STAGES,
        "sources": LEAD_SOURCES,
        "sources_creatable": LEAD_SOURCES_CREATABLE,
        "dispositions": dispositions,
    }


@router.get("/leads/auto-assign/preview")
async def auto_assign_preview(max_leads: Optional[int] = None,
                              principal: dict = Depends(require("leads:assign"))):
    result = await _auto_assign_plan(max_leads, dry_run=True)
    return result


@router.get("/leads/import/template")
async def import_template(principal: dict = Depends(require("leads:import"))):
    return Response(
        content=CSV_TEMPLATE,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="leads_import_template.csv"'},
    )


@router.get("/leads/{lid}")
async def lead_360(lid: str, principal: dict = Depends(require("leads:view"))):
    lead = await db.leads.find_one({"id": lid, "companyId": COMPANY_ID}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    calls = await db.calls.find({"lead_id": lid}, {"_id": 0}).sort("created_at", -1).to_list(200)
    client = await db.clients.find_one({"lead_id": lid}, {"_id": 0})
    return {"lead": lead, "calls": calls, "client": client}


@router.put("/leads/{lid}")
async def update_lead(lid: str, body: LeadIn, principal: dict = Depends(require("leads:edit"))):
    parsed = _parse_lead_input(body)
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
    result = await _auto_assign_plan(body.max_leads, dry_run=False)
    await audit(principal, "auto-assign", "lead", None, {"count": result["assigned"]})
    return result


@router.post("/leads/import")
async def import_leads(file: UploadFile = File(...), principal: dict = Depends(require("leads:import"))):
    content = (await file.read()).decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(content))
    created, dupes, invalid = 0, 0, 0
    for row in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        name = row.get("name") or row.get("full name") or ""
        raw_phone = row.get("phone") or row.get("mobile") or row.get("number") or ""
        if not name:
            invalid += 1
            continue
        try:
            phone = normalize_and_validate_phone(raw_phone)
        except ValueError:
            invalid += 1
            continue
        row_source = row.get("source") or "Import"
        if row_source not in LEAD_SOURCES:
            invalid += 1
            continue
        if await db.leads.find_one({"companyId": COMPANY_ID, "phone": phone}):
            dupes += 1
            continue
        doc = {"id": new_id(), "companyId": COMPANY_ID, "name": name, "phone": phone,
               "email": row.get("email", ""), "source": row_source,
               "city": row.get("city", ""), "status": "active", "assigned_to": None,
               "assigned_name": None, "owner_id": None, "disposition_id": None,
               "disposition_name": None, "carry_forward": True, "pipeline_stage": "New",
               "custom_fields": {}, "follow_up_at": None, "is_client": False,
               "client_id": None, "assigned_date": None,
               "created_at": now_iso(), "updated_at": now_iso()}
        await db.leads.insert_one(dict(doc))
        created += 1
    await audit(principal, "import", "lead", None, {"created": created, "dupes": dupes, "invalid": invalid})
    return {"created": created, "duplicates": dupes, "invalid": invalid}


# ---------------- Today Calls & disposition logging ----------------
class LogCallIn(BaseModel):
    lead_id: str
    disposition_id: str
    outcome: str = "connected"
    notes: str = ""
    duration: int = 0
    follow_up_at: Optional[str] = None
    pipeline_stage: Optional[str] = None


@router.get("/today-calls")
async def today_calls(principal: dict = Depends(require("today_calls:view"))):
    today = now_utc().date().isoformat()
    scope = await scope_filter(principal, "assigned_to")
    q = {"companyId": COMPANY_ID, "assigned_date": today, "status": "active",
         "is_client": False, **scope}
    leads = await db.leads.find(q, {"_id": 0}).sort("follow_up_at", 1).to_list(1000)
    acw = principal.get("acw_pending_lead_id")
    # re-read live acw flag
    fresh = await db.users.find_one({"id": principal["id"]}, {"_id": 0, "acw_pending_lead_id": 1})
    acw = fresh.get("acw_pending_lead_id") if fresh else acw
    return {"leads": leads, "acw_pending_lead_id": acw, "date": today}


@router.post("/calls/log")
async def log_call(body: LogCallIn, principal: dict = Depends(require("today_calls:log"))):
    lead = await db.leads.find_one({"id": body.lead_id, "companyId": COMPANY_ID}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    disp = await db.dispositions.find_one({"id": body.disposition_id, "companyId": COMPANY_ID}, {"_id": 0})
    if not disp:
        raise HTTPException(status_code=404, detail="Disposition not found")
    # ACW gate: if a prior ACW disposition is pending on a different lead, block
    fresh = await db.users.find_one({"id": principal["id"]}, {"_id": 0})
    pending = fresh.get("acw_pending_lead_id") if fresh else None
    if pending and pending != body.lead_id:
        raise HTTPException(status_code=409,
                            detail="After-call work pending on another lead. Resolve it first.")

    cid = new_id()
    call = {"id": cid, "companyId": COMPANY_ID, "lead_id": body.lead_id,
            "lead_name": lead["name"], "lead_phone": lead["phone"],
            "agent_id": principal["id"], "agent_name": principal["name"],
            "disposition_id": disp["id"], "disposition_name": disp["name"],
            "outcome": body.outcome, "notes": body.notes, "duration": body.duration,
            "follow_up_at": body.follow_up_at, "created_at": now_iso()}
    await db.calls.insert_one(dict(call))

    carry = disp["type"] == "carry_forward"
    lead_upd = {"disposition_id": disp["id"], "disposition_name": disp["name"],
                "carry_forward": carry, "follow_up_at": body.follow_up_at,
                "updated_at": now_iso()}
    if body.pipeline_stage:
        lead_upd["pipeline_stage"] = body.pipeline_stage
    if not carry:
        lead_upd["status"] = "inactive"  # leaves active queue, retained
    await db.leads.update_one({"id": body.lead_id}, {"$set": lead_upd})

    # ACW gating: set/clear pending
    if disp.get("requires_acw"):
        await db.users.update_one({"id": principal["id"]},
                                  {"$set": {"acw_pending_lead_id": body.lead_id}})
    else:
        await db.users.update_one({"id": principal["id"]},
                                  {"$set": {"acw_pending_lead_id": None}})
    await audit(principal, "log_call", "lead", body.lead_id, {"disposition": disp["name"]})
    return {"call": call, "carry_forward": carry, "acw": bool(disp.get("requires_acw"))}


@router.post("/calls/complete-acw")
async def complete_acw(principal: dict = Depends(require("today_calls:log"))):
    await db.users.update_one({"id": principal["id"]}, {"$set": {"acw_pending_lead_id": None}})
    return {"ok": True}


@router.get("/call-history")
async def call_history(search: Optional[str] = None, disposition: Optional[str] = None,
                       agent_id: Optional[str] = None, page: int = 1, page_size: int = 30,
                       principal: dict = Depends(require("call_history:view"))):
    q = {"companyId": COMPANY_ID, **await scope_filter(principal, "agent_id")}
    if search:
        q["$or"] = [{"lead_name": {"$regex": search, "$options": "i"}},
                    {"lead_phone": {"$regex": search, "$options": "i"}}]
    if disposition:
        q["disposition_name"] = disposition
    if agent_id:
        q["agent_id"] = agent_id
    total = await db.calls.count_documents(q)
    skip = (page - 1) * page_size
    calls = await db.calls.find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(page_size).to_list(page_size)
    return {"calls": calls, "total": total, "page": page, "page_size": page_size}


# ---------------- Pipeline ----------------
class StageIn(BaseModel):
    stage: str


@router.get("/pipeline")
async def pipeline(principal: dict = Depends(require("pipeline:view"))):
    q = {"companyId": COMPANY_ID, **await scope_filter(principal, "assigned_to")}
    leads = await db.leads.find(q, {"_id": 0}).sort("updated_at", -1).to_list(2000)
    board = {s: [] for s in PIPELINE_STAGES}
    for l in leads:
        s = l.get("pipeline_stage") or "New"
        board.setdefault(s, []).append(l)
    return {"stages": PIPELINE_STAGES, "board": board}


@router.put("/pipeline/{lid}")
async def move_stage(lid: str, body: StageIn, principal: dict = Depends(require("pipeline:edit"))):
    if body.stage not in PIPELINE_STAGES:
        raise HTTPException(status_code=400, detail="Invalid stage")
    res = await db.leads.update_one({"id": lid, "companyId": COMPANY_ID},
                                    {"$set": {"pipeline_stage": body.stage, "updated_at": now_iso()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found")
    await audit(principal, "move_stage", "lead", lid, {"stage": body.stage})
    return {"ok": True}


# ---------------- Follow-ups ----------------
@router.get("/followups")
async def followups(principal: dict = Depends(require("followups:view"))):
    q = {"companyId": COMPANY_ID, "follow_up_at": {"$ne": None}, **await scope_filter(principal, "assigned_to")}
    leads = await db.leads.find(q, {"_id": 0}).sort("follow_up_at", 1).to_list(1000)
    return {"followups": leads}


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
