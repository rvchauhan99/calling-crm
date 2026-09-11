"""Telephony adapter interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class OriginateResult:
    provider_call_id: str
    room_name: str
    status: str = "ringing"
    meta: dict = field(default_factory=dict)


@dataclass
class SoftphoneSession:
    token: str
    url: str
    room_name: str
    identity: str
    provider: str
    mock: bool = False


class TelephonyAdapter(ABC):
    name: str = "base"

    @abstractmethod
    async def create_softphone_session(
        self,
        *,
        identity: str,
        room_name: str,
        agent_name: str = "",
    ) -> SoftphoneSession:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    async def hangup(self, provider_call_id: str) -> None:
        raise NotImplementedError

    def normalize_webhook(self, payload: dict, headers: Optional[dict] = None) -> dict[str, Any]:
        """Return canonical event: event, provider_call_id, status, direction, from, to, talk_sec, recording_url."""
        return {
            "event": payload.get("event") or payload.get("CallStatus") or "unknown",
            "provider_call_id": payload.get("provider_call_id") or payload.get("CallUUID") or "",
            "status": payload.get("status") or "unknown",
            "direction": payload.get("direction") or "unknown",
            "from_number": payload.get("from_number") or payload.get("From") or "",
            "to_number": payload.get("to_number") or payload.get("To") or "",
            "talk_sec": int(payload.get("talk_sec") or payload.get("Duration") or 0),
            "recording_url": payload.get("recording_url") or payload.get("RecordUrl") or "",
            "room_name": payload.get("room_name") or "",
            "raw": payload,
        }
