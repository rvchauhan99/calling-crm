"""Cloud telephony API: softphone tokens, originate, webhooks, DID/IVR admin."""
from __future__ import annotations

import hmac
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel, Field

from core import COMPANY_ID, db, new_id, now_iso, normalize_phone, require, get_principal
from telephony import get_adapter
from telephony import service as tel_svc

router = APIRouter(prefix="/api/telephony", tags=["telephony"])


class SoftphoneIn(BaseModel):
    room_name: Optional[str] = None
    lead_id: Optional[str] = None


class OriginateIn(BaseModel):
    to_number: str
    lead_id: Optional[str] = None
    from_number: Optional[str] = None
    room_name: Optional[str] = None


class HangupIn(BaseModel):
    provider_call_id: str


class DidNumberIn(BaseModel):
    e164: str
    label: str = ""
    team_id: Optional[str] = None
    active: bool = True
    is_default: bool = False


class IvrConfigIn(BaseModel):
    did_id: str
    greeting_text: str = "Thank you for calling. Press 1 for sales, 2 for support."
    menu: list[dict] = Field(default_factory=lambda: [
        {"digit": "1", "label": "Sales", "action": "queue", "target": "sales"},
        {"digit": "2", "label": "Support", "action": "queue", "target": "support"},
    ])
    office_hours_enabled: bool = False
    missed_create_lead: bool = True
    active: bool = True


def _webhook_secret_ok(provided: Optional[str]) -> bool:
    expected = os.environ.get("TELEPHONY_WEBHOOK_SECRET") or ""
    if not expected:
        return True
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)


def telephony_ready() -> bool:
    """True only when live provider keys are present (UI + dial APIs unlock)."""
    if os.environ.get("TELEPHONY_UI_FORCE", "").strip().lower() in ("1", "true", "yes"):
        return True
    provider = (os.environ.get("TELEPHONY_PROVIDER") or "mock").strip().lower()
    if provider in ("", "mock"):
        return False
    return bool(
        (os.environ.get("LIVEKIT_URL") or "").strip()
        and (os.environ.get("LIVEKIT_API_KEY") or "").strip()
        and (os.environ.get("LIVEKIT_API_SECRET") or "").strip()
    )


def _require_telephony_ready():
    """Block live dial/admin when provider is not mock and keys are missing."""
    provider = (os.environ.get("TELEPHONY_PROVIDER") or "mock").strip().lower()
    if provider in ("", "mock"):
        return
    if not telephony_ready():
        raise HTTPException(
            status_code=503,
            detail="Cloud calling is inactive until registration and provider keys are configured",
        )


@router.get("/status")
async def telephony_status(principal: dict = Depends(require("today_calls:view"))):
    adapter = get_adapter()
    provider = (os.environ.get("TELEPHONY_PROVIDER") or "mock").strip().lower()
    active = await tel_svc.count_active_calls()
    livekit_configured = bool(
        (os.environ.get("LIVEKIT_URL") or "").strip()
        and (os.environ.get("LIVEKIT_API_KEY") or "").strip()
        and (os.environ.get("LIVEKIT_API_SECRET") or "").strip()
    )
    ready = telephony_ready()
    return {
        "provider": provider,
        "adapter": adapter.name,
        "active_calls": active,
        "max_concurrent": tel_svc.max_concurrent(),
        "did": os.environ.get("PLIVO_DID_E164") or "",
        "livekit_configured": livekit_configured,
        "enabled": ready,
        "ui_enabled": ready,
        "inactive_reason": None if ready else (
            "Complete Udyam/Plivo registration and set LIVEKIT_* (+ TELEPHONY_PROVIDER=plivo_livekit) to enable cloud calling"
        ),
    }


@router.post("/softphone/session")
async def softphone_session(body: SoftphoneIn, principal: dict = Depends(require("today_calls:view"))):
    _require_telephony_ready()
    room = body.room_name or f"agent-{principal['id']}-{uuid.uuid4().hex[:8]}"
    adapter = get_adapter()
    session = await adapter.create_softphone_session(
        identity=f"agent-{principal['id']}",
        room_name=room,
        agent_name=principal.get("name") or "",
    )
    return {
        "token": session.token,
        "url": session.url,
        "room_name": session.room_name,
        "identity": session.identity,
        "provider": session.provider,
        "mock": session.mock,
        "lead_id": body.lead_id,
    }


@router.post("/originate")
async def originate_call(body: OriginateIn, principal: dict = Depends(require("today_calls:log"))):
    _require_telephony_ready()
    to_number = normalize_phone(body.to_number) or body.to_number.strip()
    if not to_number:
        raise HTTPException(status_code=400, detail="to_number required")

    active = await tel_svc.count_active_calls()
    if active >= tel_svc.max_concurrent():
        raise HTTPException(status_code=429, detail="Concurrent call limit reached")

    if body.lead_id:
        lead = await db.leads.find_one({"id": body.lead_id, "companyId": COMPANY_ID}, {"_id": 0})
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

    default_did = await db.did_numbers.find_one(
        {"companyId": COMPANY_ID, "active": True, "is_default": True},
        {"_id": 0},
    )
    from_number = (
        normalize_phone(body.from_number) if body.from_number else None
    ) or (default_did or {}).get("e164") or os.environ.get("PLIVO_DID_E164") or ""

    room = body.room_name or f"call-{uuid.uuid4().hex[:12]}"
    adapter = get_adapter()
    try:
        result = await adapter.originate(
            to_number=to_number,
            from_number=from_number,
            room_name=room,
            agent_identity=f"agent-{principal['id']}",
            lead_id=body.lead_id,
            metadata={"agent_id": principal["id"]},
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    call = await tel_svc.upsert_provider_call(
        provider=adapter.name,
        provider_call_id=result.provider_call_id,
        direction="outbound",
        status=result.status,
        from_number=from_number,
        to_number=to_number,
        did=from_number,
        room_name=room,
        lead_id=body.lead_id,
        agent_id=principal["id"],
        agent_name=principal.get("name"),
        extra=result.meta,
    )
    return {
        "call_id": call["id"],
        "provider_call_id": result.provider_call_id,
        "room_name": room,
        "status": result.status,
        "mock": adapter.name == "mock",
    }


@router.post("/hangup")
async def hangup_call(body: HangupIn, principal: dict = Depends(require("today_calls:log"))):
    _require_telephony_ready()
    adapter = get_adapter()
    await adapter.hangup(body.provider_call_id)
    await tel_svc.upsert_provider_call(
        provider=adapter.name,
        provider_call_id=body.provider_call_id,
        direction="outbound",
        status="completed",
        agent_id=principal["id"],
        agent_name=principal.get("name"),
    )
    return {"ok": True}


@router.post("/webhooks/plivo")
@router.post("/webhooks/mock")
async def telephony_webhook(
    request: Request,
    x_telephony_secret: Optional[str] = Header(None, alias="X-Telephony-Secret"),
):
    if not _webhook_secret_ok(x_telephony_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        payload = await request.json()
    else:
        form = await request.form()
        payload = dict(form)

    adapter = get_adapter()
    event = adapter.normalize_webhook(payload, dict(request.headers))
    if not event.get("provider_call_id"):
        raise HTTPException(status_code=400, detail="provider_call_id missing")

    lead_id = payload.get("lead_id")
    direction = event["direction"]
    from_n = event["from_number"]
    to_n = event["to_number"]

    if not lead_id:
        phone = from_n if direction == "inbound" else to_n
        lead = await tel_svc.find_lead_by_phone(phone)
        if lead:
            lead_id = lead["id"]

    call = await tel_svc.upsert_provider_call(
        provider=adapter.name,
        provider_call_id=event["provider_call_id"],
        direction=direction,
        status=event["status"],
        from_number=from_n,
        to_number=to_n,
        talk_sec=event.get("talk_sec") or 0,
        recording_url=event.get("recording_url") or "",
        room_name=event.get("room_name") or "",
        lead_id=lead_id,
        ivr_digits=event.get("ivr_digits") or "",
        extra={"event": event.get("event")},
    )

    if direction == "inbound" and event["status"] == "missed":
        ivr = await db.ivr_configs.find_one(
            {"companyId": COMPANY_ID, "active": True},
            {"_id": 0},
        )
        if not ivr or ivr.get("missed_create_lead", True):
            did = to_n or os.environ.get("PLIVO_DID_E164") or ""
            lead = await tel_svc.ensure_missed_inbound_lead(from_n, did)
            if lead and not call.get("lead_id"):
                await db.calls.update_one(
                    {"id": call["id"]},
                    {"$set": {
                        "lead_id": lead["id"],
                        "lead_name": lead.get("name"),
                        "lead_phone": lead.get("phone"),
                        "outcome": "missed",
                    }},
                )

    return {"ok": True, "call_id": call["id"], "status": event["status"]}


@router.get("/numbers")
async def list_numbers(principal: dict = Depends(require("telephony_numbers:view"))):
    rows = await db.did_numbers.find({"companyId": COMPANY_ID}, {"_id": 0}).sort("created_at", 1).to_list(200)
    return {"numbers": rows}


@router.post("/numbers")
async def create_number(body: DidNumberIn, principal: dict = Depends(require("telephony_numbers:create"))):
    _require_telephony_ready()
    e164 = normalize_phone(body.e164) or body.e164.strip()
    if not e164:
        raise HTTPException(status_code=400, detail="e164 required")
    dup = await db.did_numbers.find_one({"companyId": COMPANY_ID, "e164": e164})
    if dup:
        raise HTTPException(status_code=409, detail="DID already exists")
    if body.is_default:
        await db.did_numbers.update_many(
            {"companyId": COMPANY_ID},
            {"$set": {"is_default": False}},
        )
    doc = {
        "id": new_id(),
        "companyId": COMPANY_ID,
        "e164": e164,
        "label": (body.label or "").strip() or e164,
        "team_id": body.team_id,
        "active": body.active,
        "is_default": body.is_default,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": principal["id"],
    }
    await db.did_numbers.insert_one(dict(doc))
    return doc


@router.put("/numbers/{nid}")
async def update_number(nid: str, body: DidNumberIn, principal: dict = Depends(require("telephony_numbers:edit"))):
    _require_telephony_ready()
    existing = await db.did_numbers.find_one({"id": nid, "companyId": COMPANY_ID}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Number not found")
    e164 = normalize_phone(body.e164) or body.e164.strip()
    if body.is_default:
        await db.did_numbers.update_many(
            {"companyId": COMPANY_ID, "id": {"$ne": nid}},
            {"$set": {"is_default": False}},
        )
    upd = {
        "e164": e164,
        "label": (body.label or "").strip() or e164,
        "team_id": body.team_id,
        "active": body.active,
        "is_default": body.is_default,
        "updated_at": now_iso(),
    }
    await db.did_numbers.update_one({"id": nid}, {"$set": upd})
    existing.update(upd)
    return existing


@router.delete("/numbers/{nid}")
async def delete_number(nid: str, principal: dict = Depends(require("telephony_numbers:delete"))):
    _require_telephony_ready()
    res = await db.did_numbers.delete_one({"id": nid, "companyId": COMPANY_ID})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Number not found")
    await db.ivr_configs.delete_many({"companyId": COMPANY_ID, "did_id": nid})
    return {"ok": True}


@router.get("/ivr")
async def list_ivr(principal: dict = Depends(require("telephony_numbers:view"))):
    rows = await db.ivr_configs.find({"companyId": COMPANY_ID}, {"_id": 0}).to_list(100)
    return {"ivr": rows}


@router.get("/ivr/{did_id}")
async def get_ivr(did_id: str, principal: dict = Depends(require("telephony_numbers:view"))):
    row = await db.ivr_configs.find_one({"companyId": COMPANY_ID, "did_id": did_id}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="IVR not found")
    return row


@router.put("/ivr")
async def upsert_ivr(body: IvrConfigIn, principal: dict = Depends(require("telephony_numbers:edit"))):
    _require_telephony_ready()
    did = await db.did_numbers.find_one({"id": body.did_id, "companyId": COMPANY_ID}, {"_id": 0})
    if not did:
        raise HTTPException(status_code=404, detail="DID not found")
    if not body.menu:
        raise HTTPException(status_code=400, detail="menu required")
    for item in body.menu:
        if not item.get("digit"):
            raise HTTPException(status_code=400, detail="Each menu item needs digit")

    existing = await db.ivr_configs.find_one({"companyId": COMPANY_ID, "did_id": body.did_id}, {"_id": 0})
    now = now_iso()
    doc = {
        "did_id": body.did_id,
        "did_e164": did["e164"],
        "greeting_text": body.greeting_text.strip(),
        "menu": body.menu,
        "office_hours_enabled": body.office_hours_enabled,
        "missed_create_lead": body.missed_create_lead,
        "active": body.active,
        "updated_at": now,
        "updated_by": principal["id"],
        "companyId": COMPANY_ID,
    }
    if existing:
        await db.ivr_configs.update_one({"id": existing["id"]}, {"$set": doc})
        existing.update(doc)
        return existing
    doc["id"] = new_id()
    doc["created_at"] = now
    await db.ivr_configs.insert_one(dict(doc))
    return doc


class IvrResolveIn(BaseModel):
    did_e164: str
    digit: str


@router.post("/ivr/resolve")
async def resolve_ivr_digit(body: IvrResolveIn, principal: dict = Depends(get_principal)):
    """Map DTMF digit to queue/target for inbound routing."""
    did = await db.did_numbers.find_one(
        {"companyId": COMPANY_ID, "e164": normalize_phone(body.did_e164) or body.did_e164},
        {"_id": 0},
    )
    if not did:
        raise HTTPException(status_code=404, detail="DID not found")
    ivr = await db.ivr_configs.find_one(
        {"companyId": COMPANY_ID, "did_id": did["id"], "active": True},
        {"_id": 0},
    )
    if not ivr:
        return {"action": "queue", "target": "default", "label": "Default"}
    for item in ivr.get("menu") or []:
        if str(item.get("digit")) == str(body.digit):
            return {
                "action": item.get("action") or "queue",
                "target": item.get("target") or "default",
                "label": item.get("label") or "",
            }
    raise HTTPException(status_code=404, detail="Digit not mapped")
