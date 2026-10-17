"""Stringee Call API + PCC callout + StringeeX history (coexistence path)."""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
import jwt

from telephony.base import OriginateResult, SoftphoneSession, TelephonyAdapter

STRINGEE_API = "https://api.stringee.com"
DEFAULT_ICC_API = "https://icc-api.stringee.com"
DEFAULT_STRINGEEX_API = "https://api.stringeex.com"

# Module-level StringeeX auth cache (process-local)
_stringeex_token: str = ""
_stringeex_token_at: float = 0.0


def _ms_to_iso(ms: Any) -> str:
    try:
        val = int(ms)
    except (TypeError, ValueError):
        return ""
    if val <= 0:
        return ""
    if val < 1_000_000_000_000:
        val *= 1000
    return datetime.fromtimestamp(val / 1000.0, tz=timezone.utc).isoformat()


def digits_only(number: str) -> str:
    """Stringee PCC often expects national/E.164 without leading +."""
    return (number or "").replace("+", "").replace(" ", "").strip()


class StringeeAdapter(TelephonyAdapter):
    name = "stringee"

    def __init__(self):
        self.api_sid = (os.environ.get("STRINGEE_API_SID") or "").strip()
        self.api_secret = (os.environ.get("STRINGEE_API_SECRET") or "").strip()
        self.from_number = (os.environ.get("STRINGEE_FROM_NUMBER") or "").strip()
        self.public_base = (
            (os.environ.get("STRINGEE_PUBLIC_API_BASE") or "").strip().rstrip("/")
            or (os.environ.get("REACT_APP_BACKEND_URL") or "").strip().rstrip("/")
            or "http://localhost:8000"
        )
        mode = (os.environ.get("STRINGEE_DIAL_MODE") or "pcc").strip().lower()
        self.dial_mode = mode if mode in ("pcc", "web_sdk") else "pcc"
        self.icc_api = (
            (os.environ.get("STRINGEE_ICC_API_BASE") or "").strip().rstrip("/")
            or DEFAULT_ICC_API
        )
        self.stringeex_api = (
            (os.environ.get("STRINGEEX_API_BASE") or "").strip().rstrip("/")
            or DEFAULT_STRINGEEX_API
        )
        self.stringeex_email = (os.environ.get("STRINGEEX_API_EMAIL") or "").strip()
        self.stringeex_password = (os.environ.get("STRINGEEX_API_PASSWORD") or "").strip()

    def configured(self) -> bool:
        return bool(self.api_sid and self.api_secret)

    def _require(self):
        if not self.configured():
            raise RuntimeError("STRINGEE_API_SID / STRINGEE_API_SECRET required")

    def mint_client_token(self, user_id: str, ttl_sec: int = 3600) -> str:
        """JWT for Web SDK connect (userId claim)."""
        self._require()
        now = int(time.time())
        headers = {"typ": "JWT", "alg": "HS256", "cty": "stringee-api;v=1"}
        payload = {
            "jti": f"{self.api_sid}-{now}",
            "iss": self.api_sid,
            "exp": now + ttl_sec,
            "userId": user_id,
        }
        return jwt.encode(payload, self.api_secret, algorithm="HS256", headers=headers)

    def mint_rest_token(self, ttl_sec: int = 3600) -> str:
        """JWT for REST X-STRINGEE-AUTH (rest_api: true)."""
        self._require()
        now = int(time.time())
        headers = {"typ": "JWT", "alg": "HS256", "cty": "stringee-api;v=1"}
        payload = {
            "jti": f"{self.api_sid}-{now}",
            "iss": self.api_sid,
            "exp": now + ttl_sec,
            "rest_api": True,
        }
        return jwt.encode(payload, self.api_secret, algorithm="HS256", headers=headers)

    async def stringeex_login(self, force: bool = False) -> str:
        """Obtain StringeeX portal auth_token (cached)."""
        global _stringeex_token, _stringeex_token_at
        if not force and _stringeex_token and (time.time() - _stringeex_token_at) < 3500:
            return _stringeex_token
        if not self.stringeex_email or not self.stringeex_password:
            raise RuntimeError("STRINGEEX_API_EMAIL / STRINGEEX_API_PASSWORD required")
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                f"{self.stringeex_api}/v1/account",
                json={"email": self.stringeex_email, "password": self.stringeex_password},
            )
            data = res.json() if res.content else {}
            if res.status_code != 200 or int(data.get("r") or -1) != 0:
                raise RuntimeError(
                    f"StringeeX login failed: {data.get('msg') or data.get('message') or res.text}"
                )
            token = data.get("auth_token") or ""
            if not token:
                portals = data.get("portals") or []
                if portals and isinstance(portals[0], dict):
                    token = portals[0].get("auth_token") or ""
            if not token:
                raise RuntimeError("StringeeX login: no auth_token in response")
            _stringeex_token = token
            _stringeex_token_at = time.time()
            return token

    def recording_play_url(self, record_id_or_url: str, ttl_sec: int = 600) -> str:
        """Browser-playable URL with short-lived access_token (Call API)."""
        rid = record_id_or_url.rstrip("/").split("/")[-1]
        if not rid:
            return ""
        # StringeeX play URLs already include access_token
        if "recordfile/play" in (record_id_or_url or ""):
            return record_id_or_url
        token = self.mint_rest_token(ttl_sec=ttl_sec)
        return f"{STRINGEE_API}/v1/call/play/{rid}?{urlencode({'access_token': token})}"

    def stringeex_recording_play_url(self, call_id: str, auth_token: str) -> str:
        if not call_id or not auth_token:
            return ""
        return (
            f"{self.stringeex_api}/v1/recordfile/play?"
            f"{urlencode({'callId': call_id, 'access_token': auth_token})}"
        )

    async def create_softphone_session(
        self,
        *,
        identity: str,
        room_name: str,
        agent_name: str = "",
    ) -> SoftphoneSession:
        # PCC mode: no Web SDK token required for outbound click-to-call
        if self.dial_mode == "pcc":
            return SoftphoneSession(
                token="",
                url=self.icc_api,
                room_name=room_name,
                identity=identity,
                provider=self.name,
                mock=False,
            )
        token = self.mint_client_token(identity)
        return SoftphoneSession(
            token=token,
            url=STRINGEE_API,
            room_name=room_name,
            identity=identity,
            provider=self.name,
            mock=False,
        )

    async def _pcc_callout(
        self,
        *,
        agent_user_id: str,
        from_number: str,
        to_number: str,
    ) -> dict[str, Any]:
        self._require()
        if not agent_user_id:
            raise RuntimeError("agentUserId (stringee_user_id) required for PCC callout")
        cli = digits_only(from_number or self.from_number)
        customer = digits_only(to_number)
        if not cli:
            raise RuntimeError("from_number or STRINGEE_FROM_NUMBER required")
        if not customer:
            raise RuntimeError("to_number required")
        display = f"Call-out-from-{cli}"
        body = {
            "agentUserId": agent_user_id,
            "toAgentFromNumberDisplay": display,
            "toAgentFromNumberDisplayAlias": display,
            "toCustomerFromNumber": cli,
            "customerNumber": customer,
        }
        token = self.mint_rest_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                f"{self.icc_api}/v1/call/callout",
                headers={
                    "X-STRINGEE-AUTH": token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=body,
            )
            data = res.json() if res.content else {}
            if res.status_code >= 400 or int(data.get("r") if data.get("r") is not None else -1) != 0:
                msg = data.get("message") or data.get("msg") or res.text or "PCC callout failed"
                raise RuntimeError(f"PCC callout failed: {msg}")
            return data

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
        self._require()
        cli = from_number or self.from_number
        if not cli:
            raise RuntimeError("from_number or STRINGEE_FROM_NUMBER required")
        meta = dict(metadata or {})
        meta.update({
            "lead_id": lead_id,
            "agent_identity": agent_identity,
            "from_number": cli,
            "dial_mode": self.dial_mode,
        })

        if self.dial_mode == "pcc":
            data = await self._pcc_callout(
                agent_user_id=agent_identity,
                from_number=cli,
                to_number=to_number,
            )
            # Response often has no callId — bookkeep and reconcile via history
            call_id = (
                data.get("callId")
                or data.get("call_id")
                or (data.get("data") or {}).get("callId")
                or (data.get("data") or {}).get("call_id")
                or f"stringee-pcc-{uuid.uuid4().hex[:12]}"
            )
            meta["via"] = "pcc_callout"
            meta["pcc_response"] = {"r": data.get("r"), "message": data.get("message") or data.get("msg")}
            meta["customer_number"] = digits_only(to_number)
            meta["stringee_number"] = digits_only(cli)
            return OriginateResult(
                provider_call_id=str(call_id),
                room_name=room_name,
                status="ringing",
                meta=meta,
            )

        call_id = f"stringee-pending-{uuid.uuid4().hex[:12]}"
        meta["via"] = "web_sdk"
        return OriginateResult(
            provider_call_id=call_id,
            room_name=room_name,
            status="ringing",
            meta=meta,
        )

    async def hangup(self, provider_call_id: str) -> None:
        if not provider_call_id or provider_call_id.startswith("stringee-pending-"):
            return
        if provider_call_id.startswith("stringee-pcc-") and "call-vn-" not in provider_call_id:
            # Placeholder id until reconcile — try StringeeX stop anyway if looks real
            return
        self._require()
        token = self.mint_rest_token()
        async with httpx.AsyncClient(timeout=20.0) as client:
            await client.post(
                f"{STRINGEE_API}/v1/call2/stop",
                headers={
                    "X-STRINGEE-AUTH": token,
                    "Content-Type": "application/json",
                },
                json={"callId": provider_call_id},
            )
            # Also try StringeeX stop when credentials present
            if self.stringeex_email and self.stringeex_password:
                try:
                    sx = await self.stringeex_login()
                    await client.get(
                        f"{self.stringeex_api}/v1/call/stop",
                        headers={"X-STRINGEE-AUTH": sx, "Accept": "application/json"},
                        params={"callId": provider_call_id},
                    )
                except Exception:
                    pass

    async def fetch_call_log(self, call_id: str) -> Optional[dict[str, Any]]:
        """GET /v1/call/log and find one call by id (best-effort)."""
        if not call_id or not self.configured():
            return None
        token = self.mint_rest_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.get(
                f"{STRINGEE_API}/v1/call/log",
                headers={"X-STRINGEE-AUTH": token},
                params={"version": 2, "limit": 50, "sort_by": "start_time", "sort_order": "desc"},
            )
            if res.status_code != 200:
                return None
            data = res.json() or {}
            calls = ((data.get("data") or {}).get("calls")) or []
            for c in calls:
                if c.get("id") == call_id:
                    return c
        return None

    async def fetch_stringeex_history(
        self,
        *,
        call_id: str = "",
        customer_number: str = "",
        stringee_number: str = "",
        time_from_ms: Optional[int] = None,
        time_to_ms: Optional[int] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """GET StringeeX call history rows."""
        if not self.stringeex_email or not self.stringeex_password:
            return []
        token = await self.stringeex_login()
        params: dict[str, Any] = {"version": 2, "sort_by": "start_time", "sort_order": "desc"}
        if call_id and not call_id.startswith("stringee-pcc-") and not call_id.startswith("stringee-pending-"):
            params["call_id"] = call_id
        if customer_number:
            params["customer_number"] = digits_only(customer_number)
        if stringee_number:
            params["stringee_number"] = digits_only(stringee_number)
        if time_from_ms is not None and time_to_ms is not None:
            params["time"] = f"{time_from_ms}-{time_to_ms}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.get(
                f"{self.stringeex_api}/v1/call/history",
                headers={"X-STRINGEE-AUTH": token, "Accept": "application/json"},
                params=params,
            )
            if res.status_code == 401:
                token = await self.stringeex_login(force=True)
                res = await client.get(
                    f"{self.stringeex_api}/v1/call/history",
                    headers={"X-STRINGEE-AUTH": token, "Accept": "application/json"},
                    params=params,
                )
            if res.status_code != 200:
                return []
            data = res.json() or {}
            rows = ((data.get("data") or {}).get("rows")) or data.get("rows") or []
            return list(rows)[:limit]

    def apply_stringeex_history_row(self, row: dict) -> dict[str, Any]:
        """Map StringeeX history row into upsert-friendly fields."""
        call_id = row.get("id") or ""
        talk = int(row.get("talk_duration") or row.get("answer_duration") or 0)
        status_code = row.get("status")
        # 1 connected, 2 missed, 3 stop at IVR, 4 survey
        if status_code == 1 or talk > 0:
            status = "completed"
        elif status_code == 2:
            status = "missed"
        elif row.get("end_time") or row.get("end_call_reason"):
            status = "completed" if talk > 0 else "missed"
        else:
            status = "ringing"
        direction_code = row.get("direction")
        direction = "outbound"
        if direction_code == 1:
            direction = "inbound"
        elif direction_code == 2:
            direction = "internal"
        recorded = bool(row.get("recorded"))
        recording_url = ""
        if recorded and call_id:
            recording_url = f"{self.stringeex_api}/v1/recordfile/play?callId={call_id}"
        return {
            "provider_call_id": call_id,
            "from_number": row.get("stringee_number") or "",
            "to_number": row.get("customer_number") or "",
            "talk_sec": talk,
            "status": status,
            "direction": direction,
            "started_at": _ms_to_iso(row.get("start_time")),
            "answered_at": _ms_to_iso(row.get("answer_time")),
            "ended_at": _ms_to_iso(row.get("end_time")),
            "recording_url": recording_url,
            "telephony_meta": {
                "reconciled_from": "stringeex_history",
                "recorded": row.get("recorded"),
                "end_call_reason": row.get("end_call_reason"),
                "end_call_by": row.get("end_call_by"),
                "account": row.get("account"),
                "route_to_agent": row.get("route_to_agent"),
                "status_code": status_code,
            },
        }

    async def reconcile_call(
        self,
        *,
        provider_call_id: str = "",
        customer_number: str = "",
        stringee_number: str = "",
        started_after_ms: Optional[int] = None,
    ) -> Optional[dict[str, Any]]:
        """Best-effort CDR from StringeeX history, else Call API log."""
        now_ms = int(time.time() * 1000)
        t0 = started_after_ms or (now_ms - 2 * 60 * 60 * 1000)
        rows = await self.fetch_stringeex_history(
            call_id=provider_call_id,
            customer_number=customer_number,
            stringee_number=stringee_number,
            time_from_ms=t0,
            time_to_ms=now_ms + 60_000,
        )
        if rows:
            # Prefer exact call id; else newest matching customer
            chosen = None
            for r in rows:
                if provider_call_id and r.get("id") == provider_call_id:
                    chosen = r
                    break
            if not chosen:
                cust = digits_only(customer_number)
                for r in rows:
                    if cust and digits_only(str(r.get("customer_number") or "")) == cust:
                        chosen = r
                        break
            if not chosen:
                chosen = rows[0]
            mapped = self.apply_stringeex_history_row(chosen)
            # Attach playable URL with fresh token when recorded
            if mapped.get("recording_url") and self.stringeex_email:
                try:
                    tok = await self.stringeex_login()
                    mapped["recording_url"] = self.stringeex_recording_play_url(
                        mapped["provider_call_id"], tok
                    )
                except Exception:
                    pass
            return mapped

        if provider_call_id and not provider_call_id.startswith("stringee-pcc-"):
            row = await self.fetch_call_log(provider_call_id)
            if row:
                return self.apply_call_log_row(row)
        return None

    def build_answer_scco(
        self,
        *,
        from_number: str,
        to_number: str,
        from_internal: bool = True,
        custom: str = "",
        record: bool = True,
    ) -> list[dict]:
        event_url = f"{self.public_base}/api/telephony/stringee/event"
        to_type = "external"
        if to_number and not to_number.replace("+", "").isdigit():
            to_type = "internal"
        connect = {
            "action": "connect",
            "from": {
                "type": "internal" if from_internal else "external",
                "number": from_number,
                "alias": from_number,
            },
            "to": {
                "type": to_type,
                "number": to_number,
                "alias": to_number,
            },
            "customData": custom or "",
            "timeout": 45,
            "maxConnectTime": -1,
            "peerToPeerCall": False,
        }
        if not record:
            return [connect]
        return [
            {
                "action": "record",
                "eventUrl": event_url,
                "format": "mp3",
            },
            connect,
        ]

    def normalize_webhook(self, payload: dict, headers: Optional[dict] = None) -> dict[str, Any]:
        if (payload.get("type") or "").lower() == "recording" or payload.get("recording_url"):
            call_id = payload.get("call_id") or ""
            return {
                "event": "recording",
                "provider_call_id": call_id,
                "status": "completed",
                "direction": "unknown",
                "from_number": "",
                "to_number": "",
                "talk_sec": 0,
                "recording_url": payload.get("recording_url") or "",
                "room_name": "",
                "started_at": _ms_to_iso(payload.get("start_time")),
                "ended_at": _ms_to_iso(payload.get("end_time")),
                "telephony_meta": {
                    "type": "recording",
                    "recording_start_ms": payload.get("start_time"),
                    "recording_end_ms": payload.get("end_time"),
                    "recordMessage": payload.get("recordMessage"),
                    "project_id": payload.get("project_id"),
                },
                "raw": payload,
            }

        call_status = (payload.get("call_status") or payload.get("event") or "").lower()
        status_map = {
            "created": "ringing",
            "started": "ringing",
            "ringing": "ringing",
            "answered": "answered",
            "ended": "completed",
            "agentended": "completed",
            "connect_failed": "failed",
        }
        status = status_map.get(call_status, call_status or "unknown")
        answer_dur = int(payload.get("answerDuration") or payload.get("answer_duration") or 0)
        total_dur = int(payload.get("duration") or 0)
        if call_status == "ended" and answer_dur == 0 and status == "completed":
            cause = (payload.get("endCallCause") or "").upper()
            if "CAN_NOT" in cause or cause.startswith("4") or cause.startswith("5"):
                status = "failed"
            else:
                status = "missed"

        from_obj = payload.get("from") or {}
        to_obj = payload.get("to") or {}
        from_n = from_obj.get("number") if isinstance(from_obj, dict) else ""
        to_n = to_obj.get("number") if isinstance(to_obj, dict) else ""
        from_type = (from_obj.get("type") if isinstance(from_obj, dict) else "") or ""
        to_type = (to_obj.get("type") if isinstance(to_obj, dict) else "") or ""

        direction = "outbound"
        if from_type == "external" and to_type == "internal":
            direction = "inbound"
        elif (payload.get("callCreatedReason") or "") == "EXTERNAL_CALL_IN":
            direction = "inbound"

        custom = payload.get("clientCustomData") or payload.get("custom") or ""
        lead_id = None
        room_name = ""
        if custom:
            try:
                parsed = json.loads(custom) if isinstance(custom, str) and custom.startswith("{") else {}
                if isinstance(parsed, dict):
                    lead_id = parsed.get("lead_id")
                    room_name = parsed.get("room_name") or ""
            except json.JSONDecodeError:
                pass

        ts = payload.get("timestamp_ms")
        timeline: dict[str, str] = {}
        if call_status in ("created", "started") and ts:
            timeline["started_at"] = _ms_to_iso(ts)
        if call_status == "ringing" and ts:
            timeline["ringing_at"] = _ms_to_iso(ts)
        if call_status == "answered" and ts:
            timeline["answered_at"] = _ms_to_iso(ts)
        if call_status in ("ended", "agentended") and ts:
            timeline["ended_at"] = _ms_to_iso(ts)

        meta = {
            "event": call_status,
            "last_event_ms": ts,
            "request_from_user_id": payload.get("request_from_user_id"),
            "project_id": payload.get("project_id"),
            "account_sid": payload.get("account_sid"),
            "type": payload.get("type"),
            "end_call_cause": payload.get("endCallCause"),
            "ended_by": payload.get("endedBy"),
            "call_created_reason": payload.get("callCreatedReason"),
            "call_type": payload.get("callType"),
            "duration_total": total_dur,
            "client_custom_data": custom,
        }
        if lead_id:
            meta["lead_id"] = lead_id

        return {
            "event": call_status or "stringee_call",
            "provider_call_id": payload.get("call_id") or "",
            "status": status,
            "direction": direction,
            "from_number": from_n or "",
            "to_number": to_n or "",
            "talk_sec": answer_dur,
            "recording_url": "",
            "room_name": room_name,
            "lead_id": lead_id,
            "request_from_user_id": payload.get("request_from_user_id"),
            "started_at": timeline.get("started_at", ""),
            "ringing_at": timeline.get("ringing_at", ""),
            "answered_at": timeline.get("answered_at", ""),
            "ended_at": timeline.get("ended_at", ""),
            "telephony_meta": meta,
            "raw": payload,
        }

    def apply_call_log_row(self, row: dict) -> dict[str, Any]:
        """Map Call Log REST row into upsert kwargs extras."""
        answer_dur = int(row.get("answer_duration") or 0)
        recording_url = ""
        if row.get("record_path") or row.get("recorded"):
            recording_url = f"{STRINGEE_API}/v1/call/recording/{row['id']}"
        return {
            "provider_call_id": row.get("id") or "",
            "from_number": row.get("from_number") or "",
            "to_number": row.get("to_number") or "",
            "talk_sec": answer_dur,
            "started_at": _ms_to_iso(row.get("start_time")),
            "answered_at": _ms_to_iso(row.get("answer_time")),
            "ended_at": _ms_to_iso(row.get("stop_time")),
            "recording_url": recording_url,
            "status": "completed" if answer_dur > 0 else "missed",
            "telephony_meta": {
                "reconciled_from": "call_log",
                "answer_duration_minutes": row.get("answer_duration_minutes"),
                "recorded": row.get("recorded"),
                "record_path": row.get("record_path"),
                "amount": row.get("amount"),
                "video_call": row.get("video_call"),
                "from_user_id": row.get("from_user_id"),
                "uuid": row.get("uuid"),
            },
        }
