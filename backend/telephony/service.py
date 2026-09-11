"""Call record helpers for telephony webhooks / originate."""
from __future__ import annotations

import os
from typing import Any, Optional

from core import COMPANY_ID, db, new_id, now_iso, normalize_phone


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
    extra: Optional[dict] = None,
) -> dict[str, Any]:
    if not provider_call_id:
        provider_call_id = new_id()

    existing = await db.calls.find_one(
        {"companyId": COMPANY_ID, "provider_call_id": provider_call_id},
        {"_id": 0},
    )
    now = now_iso()
    fields = {
        "provider": provider,
        "provider_call_id": provider_call_id,
        "direction": direction,
        "status": status,
        "from_number": from_number,
        "to_number": to_number,
        "did": did or from_number if direction == "outbound" else (did or to_number),
        "talk_sec": talk_sec,
        "recording_url": recording_url,
        "room_name": room_name,
        "updated_at": now,
    }
    if ivr_digits:
        fields["ivr_digits"] = ivr_digits
    if lead_id:
        fields["lead_id"] = lead_id
    if agent_id:
        fields["agent_id"] = agent_id
    if agent_name:
        fields["agent_name"] = agent_name
    if extra:
        fields["telephony_meta"] = extra

    # duration alias for existing Call History UI
    if talk_sec:
        fields["duration"] = talk_sec

    if existing:
        await db.calls.update_one(
            {"companyId": COMPANY_ID, "provider_call_id": provider_call_id},
            {"$set": fields},
        )
        existing.update(fields)
        return existing

    doc = {
        "id": new_id(),
        "companyId": COMPANY_ID,
        "lead_id": lead_id,
        "lead_name": "",
        "lead_phone": normalize_phone(to_number or from_number) or (to_number or from_number),
        "agent_id": agent_id,
        "agent_name": agent_name or "",
        "disposition_id": None,
        "disposition_name": None,
        "outcome": status,
        "notes": "",
        "duration": talk_sec or 0,
        "follow_up_at": None,
        "created_at": now,
        **fields,
    }
    if lead_id:
        lead = await db.leads.find_one({"id": lead_id, "companyId": COMPANY_ID}, {"_id": 0})
        if lead:
            doc["lead_name"] = lead.get("name") or ""
            doc["lead_phone"] = lead.get("phone") or doc["lead_phone"]
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
    phone = normalize_phone(from_number) or from_number
    doc = {
        "id": lid,
        "companyId": COMPANY_ID,
        "name": f"Missed {phone}",
        "phone": phone,
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
