"""LiveKit softphone + Plivo PSTN adapter (Agentive-style stack)."""
from __future__ import annotations

import os
import time
import uuid
from typing import Optional

import httpx
import jwt

from telephony.base import OriginateResult, SoftphoneSession, TelephonyAdapter


class LiveKitPlivoAdapter(TelephonyAdapter):
    name = "plivo_livekit"

    def __init__(self):
        self.livekit_url = (os.environ.get("LIVEKIT_URL") or "").rstrip("/")
        self.api_key = os.environ.get("LIVEKIT_API_KEY") or ""
        self.api_secret = os.environ.get("LIVEKIT_API_SECRET") or ""
        self.sip_host = os.environ.get("LIVEKIT_SIP_HOST") or ""
        self.plivo_auth_id = os.environ.get("PLIVO_AUTH_ID") or ""
        self.plivo_auth_token = os.environ.get("PLIVO_AUTH_TOKEN") or ""
        self.default_did = os.environ.get("PLIVO_DID_E164") or ""
        self.outbound_trunk_id = os.environ.get("LIVEKIT_OUTBOUND_TRUNK_ID") or ""

    def _require_livekit(self):
        if not self.livekit_url or not self.api_key or not self.api_secret:
            raise RuntimeError("LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET required")

    def _access_token(self, identity: str, room_name: str, name: str = "") -> str:
        self._require_livekit()
        now = int(time.time())
        payload = {
            "iss": self.api_key,
            "sub": identity,
            "nbf": now - 10,
            "exp": now + 3600,
            "name": name or identity,
            "video": {
                "roomJoin": True,
                "room": room_name,
                "canPublish": True,
                "canSubscribe": True,
                "canPublishData": True,
            },
        }
        return jwt.encode(payload, self.api_secret, algorithm="HS256")

    async def create_softphone_session(
        self,
        *,
        identity: str,
        room_name: str,
        agent_name: str = "",
    ) -> SoftphoneSession:
        token = self._access_token(identity, room_name, agent_name)
        return SoftphoneSession(
            token=token,
            url=self.livekit_url,
            room_name=room_name,
            identity=identity,
            provider=self.name,
            mock=False,
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
        self._require_livekit()
        cli = from_number or self.default_did
        if not cli:
            raise RuntimeError("from_number or PLIVO_DID_E164 required")

        # Prefer LiveKit SIP CreateSIPParticipant when trunk configured;
        # fall back to Plivo Call API bridging into room via SIP URI.
        call_id = f"lk-{uuid.uuid4()}"
        meta = metadata or {}
        meta.update({"lead_id": lead_id, "agent_identity": agent_identity})

        if self.outbound_trunk_id:
            await self._create_sip_participant(
                trunk_id=self.outbound_trunk_id,
                call_to=to_number,
                room_name=room_name,
                participant_identity=f"pstn-{to_number}",
                from_number=cli,
            )
            return OriginateResult(
                provider_call_id=call_id,
                room_name=room_name,
                status="ringing",
                meta={"via": "livekit_sip", **meta},
            )

        if self.plivo_auth_id and self.plivo_auth_token and self.sip_host:
            plivo_id = await self._plivo_click_to_call(
                from_number=cli,
                to_number=to_number,
                sip_uri=f"sip:{room_name}@{self.sip_host}",
            )
            return OriginateResult(
                provider_call_id=plivo_id or call_id,
                room_name=room_name,
                status="ringing",
                meta={"via": "plivo_api", **meta},
            )

        # Config incomplete — still return a trackable id for CRM wiring/tests
        return OriginateResult(
            provider_call_id=call_id,
            room_name=room_name,
            status="ringing",
            meta={"via": "pending_config", "warning": "SIP trunk or Plivo API not fully configured", **meta},
        )

    async def _create_sip_participant(
        self,
        *,
        trunk_id: str,
        call_to: str,
        room_name: str,
        participant_identity: str,
        from_number: str,
    ) -> None:
        # LiveKit Twirp API
        http_url = self.livekit_url.replace("wss://", "https://").replace("ws://", "http://")
        token = self._access_token("crm-api", room_name, "crm-api")
        body = {
            "sip_trunk_id": trunk_id,
            "sip_call_to": call_to,
            "room_name": room_name,
            "participant_identity": participant_identity,
            "participant_name": call_to,
            "play_ringtone": True,
            "hide_phone_number": False,
            "headers": {"X-From": from_number},
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{http_url}/twirp/livekit.SIP/CreateSIPParticipant",
                json=body,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            if r.status_code >= 400:
                raise RuntimeError(f"LiveKit SIP originate failed: {r.status_code} {r.text}")

    async def _plivo_click_to_call(self, *, from_number: str, to_number: str, sip_uri: str) -> str:
        url = f"https://api.plivo.com/v1/Account/{self.plivo_auth_id}/Call/"
        # Answer URL that bridges customer to SIP/LiveKit is operator-specific;
        # store intent; production should host an XML answer URL.
        answer_url = os.environ.get("PLIVO_ANSWER_URL") or ""
        data = {
            "from": from_number,
            "to": to_number,
            "answer_url": answer_url or "https://httpbin.org/status/200",
            "answer_method": "GET",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                url,
                data=data,
                auth=(self.plivo_auth_id, self.plivo_auth_token),
            )
            if r.status_code >= 400:
                raise RuntimeError(f"Plivo Call API failed: {r.status_code} {r.text}")
            payload = r.json() if r.content else {}
            return str(payload.get("request_uuid") or payload.get("call_uuid") or "")

    async def hangup(self, provider_call_id: str) -> None:
        if not self.plivo_auth_id or not provider_call_id:
            return
        if provider_call_id.startswith("lk-") or provider_call_id.startswith("mock-"):
            return
        url = f"https://api.plivo.com/v1/Account/{self.plivo_auth_id}/Call/{provider_call_id}/"
        async with httpx.AsyncClient(timeout=20.0) as client:
            await client.delete(url, auth=(self.plivo_auth_id, self.plivo_auth_token))

    def normalize_webhook(self, payload: dict, headers: Optional[dict] = None) -> dict:
        # Plivo-style + our canonical events
        event = (payload.get("Event") or payload.get("event") or payload.get("CallStatus") or "").lower()
        status_raw = (payload.get("CallStatus") or payload.get("status") or event).lower()
        status_map = {
            "ringing": "ringing",
            "in-progress": "answered",
            "answered": "answered",
            "completed": "completed",
            "hangup": "completed",
            "busy": "missed",
            "no-answer": "missed",
            "failed": "failed",
            "cancel": "missed",
        }
        direction = (payload.get("Direction") or payload.get("direction") or "outbound").lower()
        if direction in ("inbound", "incoming"):
            direction = "inbound"
        else:
            direction = "outbound"
        return {
            "event": event or status_raw,
            "provider_call_id": (
                payload.get("CallUUID")
                or payload.get("request_uuid")
                or payload.get("provider_call_id")
                or ""
            ),
            "status": status_map.get(status_raw, status_raw or "unknown"),
            "direction": direction,
            "from_number": payload.get("From") or payload.get("from_number") or "",
            "to_number": payload.get("To") or payload.get("to_number") or "",
            "talk_sec": int(float(payload.get("Duration") or payload.get("talk_sec") or 0)),
            "recording_url": payload.get("RecordUrl") or payload.get("recording_url") or "",
            "room_name": payload.get("room_name") or "",
            "ivr_digits": payload.get("Digits") or payload.get("ivr_digits") or "",
            "raw": payload,
        }
