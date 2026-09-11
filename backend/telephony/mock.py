"""In-memory / local mock adapter for tests and offline softphone UX."""
from __future__ import annotations

import uuid
from typing import Optional

from telephony.base import OriginateResult, SoftphoneSession, TelephonyAdapter


class MockTelephonyAdapter(TelephonyAdapter):
    name = "mock"

    def __init__(self):
        self._calls: dict[str, dict] = {}

    async def create_softphone_session(
        self,
        *,
        identity: str,
        room_name: str,
        agent_name: str = "",
    ) -> SoftphoneSession:
        return SoftphoneSession(
            token=f"mock-token-{identity}",
            url="mock://local",
            room_name=room_name,
            identity=identity,
            provider=self.name,
            mock=True,
        )

    async def originate(
        self,
        *,
        to_number: str,
        from_number: str,
        room_name: str,
        agent_identity: str,
        lead_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> OriginateResult:
        cid = f"mock-{uuid.uuid4()}"
        self._calls[cid] = {
            "to": to_number,
            "from": from_number,
            "room_name": room_name,
            "agent_identity": agent_identity,
            "lead_id": lead_id,
            "status": "ringing",
            "metadata": metadata or {},
        }
        return OriginateResult(
            provider_call_id=cid,
            room_name=room_name,
            status="ringing",
            meta={"mock": True},
        )

    async def hangup(self, provider_call_id: str) -> None:
        if provider_call_id in self._calls:
            self._calls[provider_call_id]["status"] = "completed"

    def normalize_webhook(self, payload: dict, headers: Optional[dict] = None) -> dict:
        event = (payload.get("event") or payload.get("Event") or payload.get("CallStatus") or "call.status").lower()
        status_map = {
            "ringing": "ringing",
            "answered": "answered",
            "completed": "completed",
            "hangup": "completed",
            "no-answer": "missed",
            "busy": "missed",
            "failed": "failed",
            "missed": "missed",
            "cancel": "missed",
        }
        status_raw = (
            payload.get("status")
            or payload.get("CallStatus")
            or event.split(".")[-1]
            or ""
        ).lower()
        status = status_map.get(status_raw, status_raw or "unknown")
        return {
            "event": event,
            "provider_call_id": payload.get("provider_call_id") or payload.get("CallUUID") or "",
            "status": status,
            "direction": (payload.get("direction") or payload.get("Direction") or "outbound").lower(),
            "from_number": payload.get("from_number") or payload.get("From") or "",
            "to_number": payload.get("to_number") or payload.get("To") or "",
            "talk_sec": int(payload.get("talk_sec") or payload.get("Duration") or 0),
            "recording_url": payload.get("recording_url") or payload.get("RecordUrl") or "",
            "room_name": payload.get("room_name") or "",
            "ivr_digits": payload.get("ivr_digits") or payload.get("Digits") or "",
            "raw": payload,
        }
