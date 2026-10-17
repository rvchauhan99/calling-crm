"""Call record helpers for telephony webhooks / originate."""
from __future__ import annotations

import os
from typing import Any, Optional

from core import COMPANY_ID, db, new_id, now_iso, normalize_phone, parse_phone


def _country_or_in(raw: str) -> str:
    try:
        return parse_phone(raw)[1]
    except ValueError:
        return "IN"


def max_concurrent() -> int:
    try:
        return max(1, int(os.environ.get("TELEPHONY_MAX_CONCURRENT") or "5"))
    except ValueError:
        return 5


async def count_active_calls() -> int:
    return await db.calls.count_documents({
        "companyId": COMPANY_ID,
        "status": {"$in": ["ringing", "answered"]},
        "provider": {"$exists": True},
    })


async def find_agent_by_stringee_user_id(stringee_user_id: str) -> Optional[dict]:
    sid = (stringee_user_id or "").strip()
    if not sid:
        return None
    return await db.users.find_one(
        {"companyId": COMPANY_ID, "stringee_user_id": sid},
        {"_id": 0, "id": 1, "name": 1, "stringee_user_id": 1},
    )


async def upsert_provider_call(
    *,
    provider: str,
    provider_call_id: str,
    direction: str,
    status: str,
    from_number: str = "",
    to_number: str = "",
    did: str = "",
    talk_sec: int = 0,
    recording_url: str = "",
    room_name: str = "",
    lead_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    ivr_digits: str = "",
    started_at: str = "",
    ringing_at: str = "",
    answered_at: str = "",
    ended_at: str = "",
    extra: Optional[dict] = None,
    merge_meta: bool = True,
) -> dict[str, Any]:
    if not provider_call_id:
        provider_call_id = new_id()

    existing = await db.calls.find_one(
        {"companyId": COMPANY_ID, "provider_call_id": provider_call_id},
        {"_id": 0},
    )
    now = now_iso()
    fields: dict[str, Any] = {
        "provider": provider,
        "provider_call_id": provider_call_id,
        "updated_at": now,
    }
    if direction and direction != "unknown":
        fields["direction"] = direction
    if status and status != "unknown":
        fields["status"] = status
        fields["outcome"] = status
    if from_number:
        fields["from_number"] = from_number
    if to_number:
        fields["to_number"] = to_number
    if did or from_number or to_number:
        direction_eff = fields.get("direction") or (existing or {}).get("direction") or direction
        fields["did"] = did or (
            from_number if direction_eff == "outbound" else (did or to_number)
        )
    if talk_sec:
        fields["talk_sec"] = talk_sec
        fields["duration"] = talk_sec
    if recording_url:
        fields["recording_url"] = recording_url
    if room_name:
        fields["room_name"] = room_name
    if ivr_digits:
        fields["ivr_digits"] = ivr_digits
    if lead_id:
        fields["lead_id"] = lead_id
    if agent_id:
        fields["agent_id"] = agent_id
    if agent_name:
        fields["agent_name"] = agent_name
    if started_at:
        fields["started_at"] = started_at
    if ringing_at:
        fields["ringing_at"] = ringing_at
    if answered_at:
        fields["answered_at"] = answered_at
    if ended_at:
        fields["ended_at"] = ended_at

    if extra:
        if merge_meta and existing and isinstance(existing.get("telephony_meta"), dict):
            merged = dict(existing["telephony_meta"])
            merged.update({k: v for k, v in extra.items() if v is not None})
            fields["telephony_meta"] = merged
        else:
            fields["telephony_meta"] = extra

    if existing:
        # Avoid clearing talk_sec/recording with zeros when status-only updates arrive
        if "talk_sec" not in fields and existing.get("talk_sec"):
            pass
        await db.calls.update_one(
            {"companyId": COMPANY_ID, "provider_call_id": provider_call_id},
            {"$set": fields},
        )
        existing.update(fields)
        if lead_id and not existing.get("lead_name"):
            lead = await db.leads.find_one({"id": lead_id, "companyId": COMPANY_ID}, {"_id": 0})
            if lead:
                await db.calls.update_one(
                    {"id": existing["id"]},
                    {"$set": {
                        "lead_name": lead.get("name") or "",
                        "lead_phone": lead.get("phone") or existing.get("lead_phone"),
                        "lead_phone_country": lead.get("phone_country") or existing.get("lead_phone_country") or "IN",
                    }},
                )
                existing["lead_name"] = lead.get("name") or ""
        return existing

    doc = {
        "id": new_id(),
        "companyId": COMPANY_ID,
        "lead_id": lead_id,
        "lead_name": "",
        "lead_phone": normalize_phone(to_number or from_number) or (to_number or from_number),
        "lead_phone_country": _country_or_in(to_number or from_number or ""),
        "agent_id": agent_id,
        "agent_name": agent_name or "",
        "disposition_id": None,
        "disposition_name": None,
        "outcome": status,
        "notes": "",
        "duration": talk_sec or 0,
        "talk_sec": talk_sec or 0,
        "follow_up_at": None,
        "created_at": now,
        "direction": direction if direction != "unknown" else "outbound",
        "status": status if status != "unknown" else "ringing",
        "from_number": from_number,
        "to_number": to_number,
        "did": did or from_number,
        "recording_url": recording_url or "",
        "room_name": room_name or "",
        "provider": provider,
        "provider_call_id": provider_call_id,
        "updated_at": now,
    }
    if started_at:
        doc["started_at"] = started_at
    if ringing_at:
        doc["ringing_at"] = ringing_at
    if answered_at:
        doc["answered_at"] = answered_at
    if ended_at:
        doc["ended_at"] = ended_at
    if extra:
        doc["telephony_meta"] = extra
    if lead_id:
        lead = await db.leads.find_one({"id": lead_id, "companyId": COMPANY_ID}, {"_id": 0})
        if lead:
            doc["lead_name"] = lead.get("name") or ""
            doc["lead_phone"] = lead.get("phone") or doc["lead_phone"]
            doc["lead_phone_country"] = lead.get("phone_country") or "IN"
    await db.calls.insert_one(dict(doc))
    return doc


async def find_lead_by_phone(phone: str) -> Optional[dict]:
    norm = normalize_phone(phone)
    if not norm:
        return None
    return await db.leads.find_one(
        {"companyId": COMPANY_ID, "phone": norm},
        {"_id": 0},
    )


async def ensure_missed_inbound_lead(from_number: str, did: str) -> Optional[dict]:
    """Create or return lead for missed inbound caller."""
    lead = await find_lead_by_phone(from_number)
    if lead:
        return lead
    from core import new_id as nid
    lid = nid()
    try:
        phone, phone_country = parse_phone(from_number)
    except ValueError:
        phone = normalize_phone(from_number) or from_number
        phone_country = "IN"
    doc = {
        "id": lid,
        "companyId": COMPANY_ID,
        "name": f"Missed {phone}",
        "phone": phone,
        "phone_country": phone_country,
        "email": "",
        "source": "Manual",
        "status": "active",
        "carry_forward": True,
        "pipeline_stage": "New",
        "assigned_to": None,
        "notes": f"Missed inbound on DID {did}",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.leads.insert_one(dict(doc))
    return doc


def attach_recording_play_url(call: dict) -> dict:
    """Add browser-playable recording_play_url (Stringee needs signed play URL)."""
    if not call:
        return call
    raw = (call.get("recording_url") or "").strip()
    if not raw:
        return call
    if call.get("provider") == "stringee" or "stringee.com" in raw:
        try:
            from telephony.stringee import StringeeAdapter
            se = StringeeAdapter()
            if se.configured():
                call["recording_play_url"] = se.recording_play_url(raw)
                return call
        except Exception:
            pass
    call["recording_play_url"] = raw
    return call
