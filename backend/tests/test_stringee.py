"""Stringee adapter, answer/event webhooks, per-user JWT, recording proxy."""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import jwt
import pytest
import requests

from conftest import BASE_URL, client_for

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="module")
def admin():
    return client_for("admin")


@pytest.fixture(scope="module")
def agent():
    return client_for("agent")


class TestStringeeAdapterUnit:
    def test_mint_client_and_rest_jwt(self, monkeypatch):
        monkeypatch.setenv("STRINGEE_API_SID", "SK.test.sid")
        monkeypatch.setenv("STRINGEE_API_SECRET", "test-secret-key")
        from telephony.stringee import StringeeAdapter
        ad = StringeeAdapter()
        client_tok = ad.mint_client_token("agent_alpha")
        rest_tok = ad.mint_rest_token()
        c = jwt.decode(client_tok, "test-secret-key", algorithms=["HS256"])
        r = jwt.decode(rest_tok, "test-secret-key", algorithms=["HS256"])
        assert c["userId"] == "agent_alpha"
        assert c["iss"] == "SK.test.sid"
        assert r.get("rest_api") is True
        assert "userId" not in r

    def test_answer_scco_record_before_connect(self, monkeypatch):
        monkeypatch.setenv("STRINGEE_API_SID", "SK.test.sid")
        monkeypatch.setenv("STRINGEE_API_SECRET", "test-secret-key")
        monkeypatch.setenv("STRINGEE_PUBLIC_API_BASE", "https://crm.example.com")
        from telephony.stringee import StringeeAdapter
        ad = StringeeAdapter()
        scco = ad.build_answer_scco(
            from_number="+91111",
            to_number="+919999999999",
            from_internal=True,
            custom='{"lead_id":"L1"}',
            record=True,
        )
        assert scco[0]["action"] == "record"
        assert scco[0]["format"] == "mp3"
        assert "stringee/event" in scco[0]["eventUrl"]
        assert scco[1]["action"] == "connect"
        assert scco[1]["peerToPeerCall"] is False
        assert scco[1]["to"]["type"] == "external"

    def test_normalize_call_events_and_recording(self, monkeypatch):
        monkeypatch.setenv("STRINGEE_API_SID", "SK.test.sid")
        monkeypatch.setenv("STRINGEE_API_SECRET", "test-secret-key")
        from telephony.stringee import StringeeAdapter
        ad = StringeeAdapter()

        ringing = ad.normalize_webhook({
            "call_status": "ringing",
            "call_id": "call-vn-1-ABC",
            "timestamp_ms": 1700000001000,
            "request_from_user_id": "agent_a",
            "clientCustomData": '{"lead_id":"lead-9","room_name":"r1"}',
            "type": "stringee_call",
            "from": {"number": "+911", "type": "internal"},
            "to": {"number": "+912", "type": "external"},
        })
        assert ringing["status"] == "ringing"
        assert ringing["provider_call_id"] == "call-vn-1-ABC"
        assert ringing["lead_id"] == "lead-9"
        assert ringing["ringing_at"]

        ended = ad.normalize_webhook({
            "call_status": "ended",
            "call_id": "call-vn-1-ABC",
            "timestamp_ms": 1700000010000,
            "duration": 40,
            "answerDuration": 25,
            "endCallCause": "USER_END_CALL",
            "endedBy": "INTERNAL",
            "callCreatedReason": "CLIENT_MAKE_CALL",
            "callType": "CALL",
            "type": "stringee_call",
            "from": {"number": "+911", "type": "internal"},
            "to": {"number": "+912", "type": "external"},
            "clientCustomData": '{"lead_id":"lead-9"}',
        })
        assert ended["status"] == "completed"
        assert ended["talk_sec"] == 25
        assert ended["ended_at"]
        assert ended["telephony_meta"]["end_call_cause"] == "USER_END_CALL"
        assert ended["telephony_meta"]["duration_total"] == 40

        missed = ad.normalize_webhook({
            "call_status": "ended",
            "call_id": "call-vn-1-MISS",
            "timestamp_ms": 1700000010000,
            "duration": 5,
            "answerDuration": 0,
            "endCallCause": "480 Temporarily Unavailable",
            "type": "stringee_call",
            "from": {"number": "+911", "type": "internal"},
            "to": {"number": "+912", "type": "external"},
        })
        assert missed["status"] == "failed"

        missed2 = ad.normalize_webhook({
            "call_status": "ended",
            "call_id": "call-vn-1-MISS2",
            "timestamp_ms": 1700000010000,
            "duration": 5,
            "answerDuration": 0,
            "endCallCause": "USER_END_CALL",
            "type": "stringee_call",
            "from": {"number": "+911", "type": "internal"},
            "to": {"number": "+912", "type": "external"},
        })
        assert missed2["status"] == "missed"

        rec = ad.normalize_webhook({
            "type": "recording",
            "call_id": "call-vn-1-ABC",
            "recording_url": "https://api.stringee.com/v1/call/recording/call-vn-1-ABC",
            "start_time": "1700000002000",
            "end_time": "1700000010000",
        })
        assert rec["event"] == "recording"
        assert rec["recording_url"].endswith("call-vn-1-ABC")
        assert rec["telephony_meta"]["recording_start_ms"]

    def test_apply_call_log_row(self, monkeypatch):
        monkeypatch.setenv("STRINGEE_API_SID", "SK.test.sid")
        monkeypatch.setenv("STRINGEE_API_SECRET", "test-secret-key")
        from telephony.stringee import StringeeAdapter
        ad = StringeeAdapter()
        mapped = ad.apply_call_log_row({
            "id": "call-vn-1-LOG",
            "start_time": 1700000001000,
            "answer_time": 1700000004000,
            "stop_time": 1700000010000,
            "answer_duration": 12,
            "from_number": "+911",
            "to_number": "+912",
            "recorded": 1,
            "record_path": "/x",
        })
        assert mapped["talk_sec"] == 12
        assert mapped["started_at"]
        assert mapped["answered_at"]
        assert mapped["ended_at"]
        assert "recording" in mapped["recording_url"]

    def test_pcc_originate_posts_callout(self, monkeypatch):
        monkeypatch.setenv("STRINGEE_API_SID", "SK.test.sid")
        monkeypatch.setenv("STRINGEE_API_SECRET", "test-secret-key")
        monkeypatch.setenv("STRINGEE_DIAL_MODE", "pcc")
        monkeypatch.setenv("STRINGEE_FROM_NUMBER", "+917971701163")
        from telephony.stringee import StringeeAdapter
        ad = StringeeAdapter()
        assert ad.dial_mode == "pcc"

        class FakeResp:
            status_code = 200
            text = '{"r":0}'
            content = b'{"r":0,"message":"success"}'

            def json(self):
                return {"r": 0, "message": "success"}

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None):
                assert "call/callout" in url
                assert json["agentUserId"] == "agent_nisha"
                assert json["toCustomerFromNumber"] == "917971701163"
                assert json["customerNumber"] == "919876543210"
                return FakeResp()

        with patch("telephony.stringee.httpx.AsyncClient", FakeClient):
            import asyncio
            result = asyncio.run(
                ad.originate(
                    to_number="+919876543210",
                    from_number="+917971701163",
                    room_name="r1",
                    agent_identity="agent_nisha",
                    lead_id="L1",
                )
            )
        assert result.meta["via"] == "pcc_callout"
        assert result.provider_call_id.startswith("stringee-pcc-")
        assert result.status == "ringing"

    def test_apply_stringeex_history_row(self, monkeypatch):
        monkeypatch.setenv("STRINGEE_API_SID", "SK.test.sid")
        monkeypatch.setenv("STRINGEE_API_SECRET", "test-secret-key")
        from telephony.stringee import StringeeAdapter
        ad = StringeeAdapter()
        mapped = ad.apply_stringeex_history_row({
            "id": "call-vn-1-SX",
            "customer_number": "919876543210",
            "stringee_number": "917971701163",
            "direction": 0,
            "start_time": 1700000001000,
            "answer_time": 1700000004000,
            "end_time": 1700000010000,
            "talk_duration": 15,
            "answer_duration": 15,
            "recorded": 1,
            "status": 1,
            "end_call_reason": "USER_END_CALL",
        })
        assert mapped["provider_call_id"] == "call-vn-1-SX"
        assert mapped["talk_sec"] == 15
        assert mapped["status"] == "completed"
        assert mapped["direction"] == "outbound"
        assert "recordfile/play" in mapped["recording_url"]

    def test_web_sdk_originate_still_pending(self, monkeypatch):
        monkeypatch.setenv("STRINGEE_API_SID", "SK.test.sid")
        monkeypatch.setenv("STRINGEE_API_SECRET", "test-secret-key")
        monkeypatch.setenv("STRINGEE_DIAL_MODE", "web_sdk")
        monkeypatch.setenv("STRINGEE_FROM_NUMBER", "+91111")
        from telephony.stringee import StringeeAdapter
        import asyncio
        ad = StringeeAdapter()
        result = asyncio.run(
            ad.originate(
                to_number="+91222",
                from_number="+91111",
                room_name="r",
                agent_identity="a1",
            )
        )
        assert result.meta["via"] == "web_sdk"
        assert result.provider_call_id.startswith("stringee-pending-")


class TestStringeeHttp:
    created_user_ids = []
    created_call_ids = []

    @classmethod
    def teardown_class(cls):
        admin = client_for("admin")
        for uid in cls.created_user_ids:
            admin.delete(f"{BASE_URL}/api/users/{uid}", timeout=30)
        # Close any leftover active Stringee test calls so concurrent limit does not flake others
        for cid in cls.created_call_ids:
            try:
                admin.post(
                    f"{BASE_URL}/api/telephony/hangup",
                    json={"provider_call_id": cid},
                    timeout=15,
                )
            except Exception:
                pass
        # Hangup uses provider_call_id; also force-complete via event if CRM id stored
        try:
            import asyncio
            from pathlib import Path
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from core import db, COMPANY_ID

            async def _close():
                await db.calls.update_many(
                    {
                        "companyId": COMPANY_ID,
                        "provider": "stringee",
                        "status": {"$in": ["ringing", "answered", "in_progress"]},
                    },
                    {"$set": {"status": "completed"}},
                )
            asyncio.run(_close())
        except Exception:
            pass

    def test_answer_url_returns_scco(self, monkeypatch):
        # Answer URL is public; adapter may be mock — still builds via StringeeAdapter inside route
        call_id = f"call-vn-1-TEST-{uuid.uuid4().hex[:8]}"
        r = requests.get(
            f"{BASE_URL}/api/telephony/stringee/answer",
            params={
                "from": "+911111111111",
                "to": "919876543210",
                "fromInternal": "true",
                "userId": "agent_test",
                "projectId": "1",
                "custom": '{"lead_id":"x"}',
                "callId": call_id,
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text
        scco = r.json()
        assert isinstance(scco, list) and len(scco) >= 1
        actions = [a.get("action") for a in scco]
        assert "connect" in actions
        if "record" in actions:
            assert actions.index("record") < actions.index("connect")
        # Answer upserts ringing — complete so concurrent limit does not flake suite
        requests.post(
            f"{BASE_URL}/api/telephony/stringee/event",
            json={
                "call_status": "ended",
                "call_id": call_id,
                "timestamp_ms": 1700000020000,
                "duration": 1,
                "answerDuration": 0,
                "endCallCause": "USER_END_CALL",
                "type": "stringee_call",
                "from": {"number": "+911111111111", "type": "internal"},
                "to": {"number": "919876543210", "type": "external"},
            },
            timeout=30,
        )
        self.created_call_ids.append(call_id)

    def test_event_webhook_ended_and_recording(self, admin):
        call_id = f"call-vn-1-EVT-{uuid.uuid4().hex[:10]}"
        r1 = requests.post(
            f"{BASE_URL}/api/telephony/stringee/event",
            json={
                "call_status": "answered",
                "call_id": call_id,
                "timestamp_ms": 1700000005000,
                "request_from_user_id": "agent-unknown",
                "type": "stringee_call",
                "from": {"number": "+911111111111", "type": "internal"},
                "to": {"number": "+919999990099", "type": "external"},
                "clientCustomData": "{}",
            },
            timeout=30,
        )
        assert r1.status_code == 200, r1.text
        assert r1.json()["status"] == "answered"

        with patch("telephony.stringee.StringeeAdapter.fetch_call_log", return_value=None):
            r2 = requests.post(
                f"{BASE_URL}/api/telephony/stringee/event",
                json={
                    "call_status": "ended",
                    "call_id": call_id,
                    "timestamp_ms": 1700000020000,
                    "duration": 30,
                    "answerDuration": 18,
                    "endCallCause": "USER_END_CALL",
                    "endedBy": "INTERNAL",
                    "callCreatedReason": "CLIENT_MAKE_CALL",
                    "callType": "CALL",
                    "type": "stringee_call",
                    "from": {"number": "+911111111111", "type": "internal"},
                    "to": {"number": "+919999990099", "type": "external"},
                    "clientCustomData": "{}",
                },
                timeout=30,
            )
        assert r2.status_code == 200, r2.text
        assert r2.json()["status"] == "completed"
        self.created_call_ids.append(call_id)

        r3 = requests.post(
            f"{BASE_URL}/api/telephony/stringee/event",
            json={
                "type": "recording",
                "call_id": call_id,
                "recording_url": f"https://api.stringee.com/v1/call/recording/{call_id}",
                "start_time": "1700000006000",
                "end_time": "1700000020000",
            },
            timeout=30,
        )
        assert r3.status_code == 200, r3.text

    def test_user_stringee_fields_and_unique(self, admin):
        roles = admin.get(f"{BASE_URL}/api/roles", timeout=30).json()["roles"]
        agent_role = next(
            (r["id"] for r in roles if "agent" in r["name"].lower() or "caller" in r["name"].lower()),
            roles[0]["id"] if roles else None,
        )
        assert agent_role
        sid = f"se_user_{uuid.uuid4().hex[:8]}"
        email = f"test_stringee_{uuid.uuid4().hex[:6]}@example.com"
        cr = admin.post(f"{BASE_URL}/api/users", json={
            "name": "TEST_StringeeCaller",
            "email": email,
            "password": "Test@1234",
            "role_id": agent_role,
            "user_type": "caller",
            "daily_quota": 10,
            "stringee_user_id": sid,
            "stringee_enabled": True,
        }, timeout=30)
        assert cr.status_code in (200, 201), cr.text
        user = cr.json()["user"]
        self.created_user_ids.append(user["id"])
        assert user["stringee_user_id"] == sid
        assert user["stringee_enabled"] is True

        # duplicate stringee_user_id denied
        dup = admin.post(f"{BASE_URL}/api/users", json={
            "name": "TEST_StringeeDup",
            "email": f"test_stringee_dup_{uuid.uuid4().hex[:6]}@example.com",
            "password": "Test@1234",
            "role_id": agent_role,
            "user_type": "caller",
            "daily_quota": 5,
            "stringee_user_id": sid,
            "stringee_enabled": True,
        }, timeout=30)
        assert dup.status_code == 400, dup.text

    def test_recording_proxy_auth_deny_and_404(self, agent, admin):
        # no recording
        r = agent.get(f"{BASE_URL}/api/telephony/recordings/does-not-exist", timeout=30)
        assert r.status_code == 404, r.text

        # affiliate denied
        aff = client_for("affiliate")
        r2 = aff.get(f"{BASE_URL}/api/telephony/recordings/x", timeout=30)
        assert r2.status_code in (401, 403), r2.text

    def test_status_accepts_stringee_adapter_name(self, admin):
        r = admin.get(f"{BASE_URL}/api/telephony/status", timeout=30)
        assert r.status_code == 200
        assert r.json()["adapter"] in ("mock", "plivo_livekit", "stringee")
        assert "stringee_configured" in r.json() or r.json()["adapter"] != "stringee"

    def test_reconcile_auth_and_missing_call(self, agent, admin):
        # missing body
        r = agent.post(f"{BASE_URL}/api/telephony/stringee/reconcile", json={}, timeout=30)
        # 503 if stringee not ready, else 400
        assert r.status_code in (400, 503), r.text

        aff = client_for("affiliate")
        r2 = aff.post(
            f"{BASE_URL}/api/telephony/stringee/reconcile",
            json={"call_id": "x"},
            timeout=30,
        )
        assert r2.status_code in (401, 403, 503), r2.text

    def test_did_crud_lists_for_multi_cli(self, admin):
        """Phone Numbers inventory supports multiple Stringee DIDs."""
        e164 = f"+91797{str(uuid.uuid4().int % 10**7).zfill(7)}"
        # May 503 when provider not ready — skip create assert in that case
        cr = admin.post(
            f"{BASE_URL}/api/telephony/numbers",
            json={"e164": e164, "label": "TEST_SE_DID", "active": True, "is_default": False},
            timeout=30,
        )
        if cr.status_code == 503:
            pytest.skip("telephony not ready for DID create")
        assert cr.status_code in (200, 201), cr.text
        nid = cr.json().get("id") or cr.json().get("number", {}).get("id")
        lst = admin.get(f"{BASE_URL}/api/telephony/numbers", timeout=30)
        assert lst.status_code == 200
        assert any(n.get("e164") == e164 for n in lst.json().get("numbers") or [])
        if nid:
            admin.delete(f"{BASE_URL}/api/telephony/numbers/{nid}", timeout=30)
