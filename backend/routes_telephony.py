"""Cloud telephony API: softphone tokens, originate, webhooks, DID/IVR admin."""
from __future__ import annotations

import hmac
import json
import os
import uuid
from typing import Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Header, Request, Response
from fastapi.responses import JSONResponse
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


class ReconcileIn(BaseModel):
    call_id: Optional[str] = None
    provider_call_id: Optional[str] = None


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
    if provider == "stringee":
        return bool(
            (os.environ.get("STRINGEE_API_SID") or "").strip()
            and (os.environ.get("STRINGEE_API_SECRET") or "").strip()
        )
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


def _inactive_reason(provider: str) -> str:
    if provider == "stringee":
        return (
            "Set TELEPHONY_PROVIDER=stringee with STRINGEE_API_SID and STRINGEE_API_SECRET "
            "(and STRINGEE_FROM_NUMBER or Phone Numbers for outbound CLI)"
        )
    return (
        "Complete Udyam/Plivo registration and set LIVEKIT_* (+ TELEPHONY_PROVIDER=plivo_livekit) "
        "or TELEPHONY_PROVIDER=stringee with STRINGEE_* keys"
    )


def _stringee_dial_mode() -> str:
    mode = (os.environ.get("STRINGEE_DIAL_MODE") or "pcc").strip().lower()
    return mode if mode in ("pcc", "web_sdk") else "pcc"


async def _active_from_numbers() -> list[dict]:
    rows = await db.did_numbers.find(
        {"companyId": COMPANY_ID, "active": True},
        {"_id": 0, "e164": 1, "label": 1, "is_default": 1},
    ).sort("created_at", 1).to_list(200)
    return [
        {
            "e164": r.get("e164") or "",
            "label": r.get("label") or r.get("e164") or "",
            "is_default": bool(r.get("is_default")),
        }
        for r in rows
        if r.get("e164")
    ]


async def _resolve_cli(body_from: Optional[str], *, provider: str) -> tuple[str, list[dict]]:
    """Resolve outbound CLI from body → default DID → env; return (cli, from_numbers)."""
    from_numbers = await _active_from_numbers()
    env_did = (
        os.environ.get("STRINGEE_FROM_NUMBER")
        if provider == "stringee"
        else os.environ.get("PLIVO_DID_E164")
    ) or ""
    default_e164 = ""
    for n in from_numbers:
        if n.get("is_default"):
            default_e164 = n["e164"]
            break
    if not default_e164 and from_numbers:
        default_e164 = from_numbers[0]["e164"]
    requested = normalize_phone(body_from) if body_from else None
    if requested and from_numbers:
        allowed = {n["e164"] for n in from_numbers}
        # also allow digit-equivalent match
        allowed_digits = {n["e164"].lstrip("+") for n in from_numbers}
        if requested not in allowed and requested.lstrip("+") not in allowed_digits:
            raise HTTPException(status_code=400, detail="from_number is not an active DID")
        # normalize to stored e164
        for n in from_numbers:
            if n["e164"] == requested or n["e164"].lstrip("+") == requested.lstrip("+"):
                return n["e164"], from_numbers
    cli = requested or default_e164 or env_did or ""
    return cli, from_numbers


async def _resolve_stringee_identity(principal: dict) -> tuple[str, dict]:
    """Return (stringee_user_id, user_doc) for softphone JWT / PCC agentUserId."""
    user = await db.users.find_one(
        {"id": principal["id"], "companyId": COMPANY_ID},
        {"_id": 0, "id": 1, "name": 1, "user_type": 1, "stringee_user_id": 1, "stringee_enabled": 1, "active": 1},
    )
    if not user or not user.get("active", True):
        raise HTTPException(status_code=403, detail="User not found or inactive")
    if user.get("stringee_enabled") is False:
        raise HTTPException(status_code=403, detail="Stringee calling is disabled for this user")
    sid = (user.get("stringee_user_id") or "").strip() or f"agent-{user['id']}"
    return sid, user


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
    stringee_configured = bool(
        (os.environ.get("STRINGEE_API_SID") or "").strip()
        and (os.environ.get("STRINGEE_API_SECRET") or "").strip()
    )
    ready = telephony_ready()
    from_numbers = await _active_from_numbers() if provider == "stringee" else []
    did = ""
    if provider == "stringee":
        for n in from_numbers:
            if n.get("is_default"):
                did = n["e164"]
                break
        if not did and from_numbers:
            did = from_numbers[0]["e164"]
        did = did or (os.environ.get("STRINGEE_FROM_NUMBER") or "")
    else:
        did = os.environ.get("PLIVO_DID_E164") or ""
    dial_mode = _stringee_dial_mode() if provider == "stringee" else None
    return {
        "provider": provider,
        "adapter": adapter.name,
        "active_calls": active,
        "max_concurrent": tel_svc.max_concurrent(),
        "did": did,
        "from_numbers": from_numbers,
        "dial_mode": dial_mode,
        "livekit_configured": livekit_configured,
        "stringee_configured": stringee_configured,
        "enabled": ready,
        "ui_enabled": ready,
        "inactive_reason": None if ready else _inactive_reason(provider),
    }


@router.post("/softphone/session")
async def softphone_session(body: SoftphoneIn, principal: dict = Depends(require("today_calls:view"))):
    _require_telephony_ready()
    room = body.room_name or f"agent-{principal['id']}-{uuid.uuid4().hex[:8]}"
    adapter = get_adapter()
    identity = f"agent-{principal['id']}"
    stringee_user_id = None
    from_number = os.environ.get("PLIVO_DID_E164") or ""
    from_numbers: list[dict] = []
    dial_mode = None
    if adapter.name == "stringee":
        stringee_user_id, _user = await _resolve_stringee_identity(principal)
        identity = stringee_user_id
        from_number, from_numbers = await _resolve_cli(None, provider="stringee")
        dial_mode = getattr(adapter, "dial_mode", None) or _stringee_dial_mode()
    session = await adapter.create_softphone_session(
        identity=identity,
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
        "stringee_user_id": stringee_user_id,
        "from_number": from_number,
        "from_numbers": from_numbers,
        "dial_mode": dial_mode,
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

    adapter = get_adapter()
    provider = adapter.name
    from_number, from_numbers = await _resolve_cli(
        body.from_number,
        provider="stringee" if provider == "stringee" else "plivo",
    )
    if provider == "stringee" and from_numbers and not from_number:
        raise HTTPException(status_code=400, detail="No active DID configured")
    if provider == "stringee" and not from_number:
        raise HTTPException(
            status_code=400,
            detail="from_number required — add Phone Numbers or set STRINGEE_FROM_NUMBER",
        )

    room = body.room_name or f"call-{uuid.uuid4().hex[:12]}"
    agent_identity = f"agent-{principal['id']}"
    if adapter.name == "stringee":
        agent_identity, _ = await _resolve_stringee_identity(principal)
    try:
        result = await adapter.originate(
            to_number=to_number,
            from_number=from_number,
            room_name=room,
            agent_identity=agent_identity,
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
        "dial_mode": getattr(adapter, "dial_mode", None),
        "from_number": from_number,
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
                        "lead_phone_country": lead.get("phone_country") or "IN",
                        "outcome": "missed",
                    }},
                )

    return {"ok": True, "call_id": call["id"], "status": event["status"]}


class BindCallIn(BaseModel):
    pending_provider_call_id: str
    provider_call_id: str
    lead_id: Optional[str] = None


@router.post("/stringee/bind-call")
async def stringee_bind_call(body: BindCallIn, principal: dict = Depends(require("today_calls:log"))):
    """Replace pending CRM call id with real Stringee callId from Web SDK."""
    pending = (body.pending_provider_call_id or "").strip()
    real = (body.provider_call_id or "").strip()
    if not pending or not real:
        raise HTTPException(status_code=400, detail="pending_provider_call_id and provider_call_id required")
    existing = await db.calls.find_one(
        {"companyId": COMPANY_ID, "provider_call_id": pending},
        {"_id": 0},
    )
    if not existing:
        call = await tel_svc.upsert_provider_call(
            provider="stringee",
            provider_call_id=real,
            direction="outbound",
            status="ringing",
            lead_id=body.lead_id,
            agent_id=principal["id"],
            agent_name=principal.get("name"),
        )
        return {"ok": True, "call_id": call["id"], "provider_call_id": real}
    await db.calls.update_one(
        {"id": existing["id"]},
        {"$set": {"provider_call_id": real, "updated_at": now_iso()}},
    )
    return {"ok": True, "call_id": existing["id"], "provider_call_id": real}


@router.post("/stringee/reconcile")
async def stringee_reconcile(body: ReconcileIn, principal: dict = Depends(require("today_calls:log"))):
    """Pull CDR/recording from StringeeX history (or Call log) into CRM call row."""
    _require_telephony_ready()
    from telephony.stringee import StringeeAdapter

    adapter = get_adapter()
    if not isinstance(adapter, StringeeAdapter):
        adapter = StringeeAdapter()
    if not adapter.configured():
        raise HTTPException(status_code=503, detail="Stringee not configured")

    q: dict = {"companyId": COMPANY_ID, "provider": "stringee"}
    if body.call_id:
        q["id"] = body.call_id
    elif body.provider_call_id:
        q["provider_call_id"] = body.provider_call_id
    else:
        raise HTTPException(status_code=400, detail="call_id or provider_call_id required")

    existing = await db.calls.find_one(q, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Call not found")
    if principal.get("data_scope") == "OWN" and existing.get("agent_id") and existing.get("agent_id") != principal["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    meta = existing.get("telephony_meta") or {}
    customer = existing.get("to_number") or meta.get("customer_number") or ""
    cli = existing.get("from_number") or existing.get("did") or meta.get("stringee_number") or ""
    try:
        mapped = await adapter.reconcile_call(
            provider_call_id=existing.get("provider_call_id") or "",
            customer_number=customer,
            stringee_number=cli,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    if not mapped:
        return {
            "ok": True,
            "call_id": existing["id"],
            "provider_call_id": existing.get("provider_call_id"),
            "status": existing.get("status"),
            "reconciled": False,
        }

    real_id = mapped.get("provider_call_id") or existing.get("provider_call_id")
    # If we discovered the real Stringee call id, update the CRM row key
    if real_id and real_id != existing.get("provider_call_id"):
        await db.calls.update_one(
            {"id": existing["id"]},
            {"$set": {"provider_call_id": real_id, "updated_at": now_iso()}},
        )

    call = await tel_svc.upsert_provider_call(
        provider="stringee",
        provider_call_id=real_id,
        direction=mapped.get("direction") or existing.get("direction") or "outbound",
        status=mapped.get("status") or existing.get("status") or "completed",
        from_number=mapped.get("from_number") or existing.get("from_number") or "",
        to_number=mapped.get("to_number") or existing.get("to_number") or "",
        did=existing.get("did") or mapped.get("from_number") or "",
        talk_sec=mapped.get("talk_sec") or 0,
        recording_url=mapped.get("recording_url") or existing.get("recording_url") or "",
        lead_id=existing.get("lead_id"),
        agent_id=existing.get("agent_id") or principal["id"],
        agent_name=existing.get("agent_name") or principal.get("name"),
        started_at=mapped.get("started_at") or "",
        answered_at=mapped.get("answered_at") or "",
        ended_at=mapped.get("ended_at") or "",
        extra=mapped.get("telephony_meta"),
    )
    return {
        "ok": True,
        "call_id": call["id"],
        "provider_call_id": call.get("provider_call_id"),
        "status": call.get("status"),
        "talk_sec": call.get("talk_sec") or 0,
        "recording_url": call.get("recording_url") or "",
        "reconciled": True,
    }


@router.get("/stringee/answer")
async def stringee_answer(request: Request):
    """Answer URL — returns SCCO for Stringee (record then connect)."""
    adapter = get_adapter()
    if adapter.name != "stringee":
        # Still serve SCCO if keys present (dashboard may hit during provider switch)
        from telephony.stringee import StringeeAdapter
        adapter = StringeeAdapter()
    params = dict(request.query_params)
    from_number = unquote(params.get("from") or "")
    to_number = unquote(params.get("to") or "")
    custom = unquote(params.get("custom") or "")
    call_id = params.get("callId") or params.get("call_id") or ""
    user_id = params.get("userId") or ""
    from_internal = str(params.get("fromInternal", "true")).lower() in ("1", "true", "yes")

    lead_id = None
    room_name = ""
    if custom:
        try:
            parsed = json.loads(custom) if custom.startswith("{") else {}
            if isinstance(parsed, dict):
                lead_id = parsed.get("lead_id")
                room_name = parsed.get("room_name") or ""
        except json.JSONDecodeError:
            pass

    agent = await tel_svc.find_agent_by_stringee_user_id(user_id) if user_id else None
    if call_id:
        await tel_svc.upsert_provider_call(
            provider="stringee",
            provider_call_id=call_id,
            direction="outbound" if from_internal else "inbound",
            status="ringing",
            from_number=from_number,
            to_number=to_number,
            did=from_number if from_internal else to_number,
            room_name=room_name,
            lead_id=lead_id,
            agent_id=(agent or {}).get("id"),
            agent_name=(agent or {}).get("name"),
            started_at=now_iso(),
            extra={
                "event": "answer_url",
                "request_from_user_id": user_id,
                "project_id": params.get("projectId"),
                "client_custom_data": custom,
            },
        )

    scco = adapter.build_answer_scco(
        from_number=from_number or (os.environ.get("STRINGEE_FROM_NUMBER") or ""),
        to_number=to_number,
        from_internal=from_internal,
        custom=custom,
        record=True,
    )
    return JSONResponse(content=scco)


@router.post("/stringee/event")
async def stringee_event(request: Request):
    """Event URL — call lifecycle + recording webhooks from Stringee."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON body required")

    from telephony.stringee import StringeeAdapter
    adapter = get_adapter()
    if not isinstance(adapter, StringeeAdapter):
        adapter = StringeeAdapter()

    event = adapter.normalize_webhook(payload, dict(request.headers))
    provider_call_id = event.get("provider_call_id") or ""
    if not provider_call_id:
        raise HTTPException(status_code=400, detail="call_id missing")

    lead_id = event.get("lead_id") or (event.get("telephony_meta") or {}).get("lead_id")
    agent_id = None
    agent_name = None
    req_uid = event.get("request_from_user_id") or (event.get("telephony_meta") or {}).get("request_from_user_id")
    if req_uid:
        agent = await tel_svc.find_agent_by_stringee_user_id(str(req_uid))
        if agent:
            agent_id = agent["id"]
            agent_name = agent.get("name")

    direction = event.get("direction") or "outbound"
    from_n = event.get("from_number") or ""
    to_n = event.get("to_number") or ""
    if not lead_id:
        phone = from_n if direction == "inbound" else to_n
        lead = await tel_svc.find_lead_by_phone(phone)
        if lead:
            lead_id = lead["id"]

    call = await tel_svc.upsert_provider_call(
        provider="stringee",
        provider_call_id=provider_call_id,
        direction=direction if direction != "unknown" else "outbound",
        status=event.get("status") or "unknown",
        from_number=from_n,
        to_number=to_n,
        talk_sec=event.get("talk_sec") or 0,
        recording_url=event.get("recording_url") or "",
        room_name=event.get("room_name") or "",
        lead_id=lead_id,
        agent_id=agent_id,
        agent_name=agent_name,
        started_at=event.get("started_at") or "",
        ringing_at=event.get("ringing_at") or "",
        answered_at=event.get("answered_at") or "",
        ended_at=event.get("ended_at") or "",
        extra=event.get("telephony_meta") or {"event": event.get("event")},
    )

    # Reconcile authoritative timestamps from Call Log after end
    if event.get("event") in ("ended", "agentended", "recording") or event.get("status") in ("completed", "missed", "failed"):
        try:
            row = await adapter.fetch_call_log(provider_call_id)
            if row:
                mapped = adapter.apply_call_log_row(row)
                await tel_svc.upsert_provider_call(
                    provider="stringee",
                    provider_call_id=provider_call_id,
                    direction=direction if direction != "unknown" else "outbound",
                    status=event.get("status") or call.get("status") or "completed",
                    from_number=mapped.get("from_number") or from_n,
                    to_number=mapped.get("to_number") or to_n,
                    talk_sec=mapped.get("talk_sec") or 0,
                    recording_url=mapped.get("recording_url") or event.get("recording_url") or "",
                    started_at=mapped.get("started_at") or "",
                    answered_at=mapped.get("answered_at") or "",
                    ended_at=mapped.get("ended_at") or "",
                    lead_id=lead_id,
                    agent_id=agent_id,
                    agent_name=agent_name,
                    extra=mapped.get("telephony_meta"),
                )
        except Exception:
            pass

    if direction == "inbound" and event.get("status") == "missed":
        did = to_n or os.environ.get("STRINGEE_FROM_NUMBER") or ""
        lead = await tel_svc.ensure_missed_inbound_lead(from_n, did)
        if lead and not call.get("lead_id"):
            await db.calls.update_one(
                {"id": call["id"]},
                {"$set": {
                    "lead_id": lead["id"],
                    "lead_name": lead.get("name"),
                    "lead_phone": lead.get("phone"),
                    "lead_phone_country": lead.get("phone_country") or "IN",
                    "outcome": "missed",
                }},
            )

    return {"ok": True, "call_id": call["id"], "status": event.get("status")}


@router.get("/recordings/{call_id}")
async def play_recording(call_id: str, principal: dict = Depends(require("today_calls:view", "call_history:view"))):
    """Proxy / redirect to playable Stringee recording (auth required)."""
    call = await db.calls.find_one({"id": call_id, "companyId": COMPANY_ID}, {"_id": 0})
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    # OWN scope: agent may only hear own calls
    if principal.get("data_scope") == "OWN" and call.get("agent_id") and call.get("agent_id") != principal["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    recording_url = (call.get("recording_url") or "").strip()
    if not recording_url:
        raise HTTPException(status_code=404, detail="No recording")

    if call.get("provider") == "stringee" or "stringee.com" in recording_url or "stringeex.com" in recording_url:
        from telephony.stringee import StringeeAdapter
        se = StringeeAdapter()
        if not se.configured():
            raise HTTPException(status_code=503, detail="Stringee not configured")
        # Refresh StringeeX play URL with live auth_token when needed
        if "recordfile/play" in recording_url or "stringeex.com" in recording_url:
            try:
                tok = await se.stringeex_login()
                cid = call.get("provider_call_id") or ""
                if "callId=" in recording_url:
                    from urllib.parse import parse_qs, urlparse
                    qs = parse_qs(urlparse(recording_url).query)
                    cid = (qs.get("callId") or [cid])[0]
                play = se.stringeex_recording_play_url(cid, tok) or se.recording_play_url(recording_url)
            except Exception:
                play = se.recording_play_url(recording_url)
        else:
            play = se.recording_play_url(recording_url)
        return Response(status_code=302, headers={"Location": play})

    # Non-Stringee: stream or redirect
    if recording_url.startswith("http"):
        return Response(status_code=302, headers={"Location": recording_url})
    raise HTTPException(status_code=404, detail="No recording")


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
