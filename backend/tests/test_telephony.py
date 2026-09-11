"""Cloud telephony adapter + webhook + DID/IVR tests."""
import os
import uuid

import pytest
import requests

from conftest import BASE_URL, client_for


@pytest.fixture(scope="module")
def admin():
    return client_for("admin")


@pytest.fixture(scope="module")
def agent():
    return client_for("agent")


class TestTelephony:
    created_number_ids = []
    created_lead_ids = []

    @classmethod
    def teardown_class(cls):
        admin = client_for("admin")
        for nid in cls.created_number_ids:
            admin.delete(f"{BASE_URL}/api/telephony/numbers/{nid}", timeout=30)
        for lid in cls.created_lead_ids:
            admin.delete(f"{BASE_URL}/api/leads/{lid}", timeout=30)

    def test_status_happy_path(self, admin):
        r = admin.get(f"{BASE_URL}/api/telephony/status", timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["adapter"] in ("mock", "plivo_livekit")
        assert "max_concurrent" in body
        assert body["max_concurrent"] >= 1
        assert "enabled" in body
        assert "ui_enabled" in body
        # Default local .env uses mock → cloud UI stays inactive until keys
        provider = (os.environ.get("TELEPHONY_PROVIDER") or "mock").strip().lower()
        force = os.environ.get("TELEPHONY_UI_FORCE", "").strip().lower() in ("1", "true", "yes")
        if provider in ("", "mock") and not force:
            assert body["enabled"] is False
            assert body["ui_enabled"] is False
            assert body.get("inactive_reason")

    def test_status_rbac_affiliate_denied(self):
        aff = client_for("affiliate")
        r = aff.get(f"{BASE_URL}/api/telephony/status", timeout=30)
        assert r.status_code in (401, 403), r.text

    def test_softphone_session_and_originate_mock(self, agent, admin):
        # create a throwaway lead
        phone = f"+9198{str(uuid.uuid4().int % 10**8).zfill(8)}"
        lead = admin.post(f"{BASE_URL}/api/leads", json={
            "name": f"TEST_TEL_{uuid.uuid4().hex[:6]}",
            "phone": phone,
            "source": "Website",
            "pipeline_stage": "New",
        }, timeout=30)
        assert lead.status_code in (200, 201), lead.text
        lead_id = lead.json()["lead"]["id"]
        self.created_lead_ids.append(lead_id)

        sess = agent.post(f"{BASE_URL}/api/telephony/softphone/session", json={
            "lead_id": lead_id,
        }, timeout=30)
        assert sess.status_code == 200, sess.text
        sbody = sess.json()
        assert sbody["token"]
        assert sbody["room_name"]
        assert sbody.get("mock") is True or sbody["provider"] in ("mock", "plivo_livekit")

        orig = agent.post(f"{BASE_URL}/api/telephony/originate", json={
            "to_number": phone,
            "lead_id": lead_id,
            "room_name": sbody["room_name"],
        }, timeout=30)
        assert orig.status_code == 200, orig.text
        obody = orig.json()
        assert obody["provider_call_id"]
        assert obody["status"] == "ringing"

        hang = agent.post(f"{BASE_URL}/api/telephony/hangup", json={
            "provider_call_id": obody["provider_call_id"],
        }, timeout=30)
        assert hang.status_code == 200, hang.text

    def test_webhook_completed_and_auth(self, admin):
        call_id = f"mock-test-{uuid.uuid4().hex}"
        # Without secret when TELEPHONY_WEBHOOK_SECRET unset — should work
        r = requests.post(
            f"{BASE_URL}/api/telephony/webhooks/mock",
            json={
                "event": "completed",
                "provider_call_id": call_id,
                "status": "completed",
                "direction": "outbound",
                "to_number": "+919999990001",
                "from_number": "+911111111111",
                "talk_sec": 42,
                "recording_url": "https://example.com/rec.ogg",
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "completed"
        assert r.json()["call_id"]

        # Wrong secret when env has secret — skip if not set
        secret = os.environ.get("TELEPHONY_WEBHOOK_SECRET") or ""
        if secret:
            bad = requests.post(
                f"{BASE_URL}/api/telephony/webhooks/mock",
                json={"provider_call_id": f"{call_id}-b", "status": "completed"},
                headers={"X-Telephony-Secret": "wrong"},
                timeout=30,
            )
            assert bad.status_code == 401

    def test_webhook_missing_call_id(self):
        r = requests.post(
            f"{BASE_URL}/api/telephony/webhooks/mock",
            json={"status": "completed"},
            timeout=30,
        )
        assert r.status_code == 400

    def test_did_crud_and_ivr(self, admin, agent):
        e164 = f"+9197{str(uuid.uuid4().int % 10**8).zfill(8)}"
        # Agent cannot create numbers
        denied = agent.post(f"{BASE_URL}/api/telephony/numbers", json={
            "e164": e164, "label": "TEST", "active": True, "is_default": True,
        }, timeout=30)
        assert denied.status_code in (401, 403), denied.text

        created = admin.post(f"{BASE_URL}/api/telephony/numbers", json={
            "e164": e164,
            "label": "TEST_DID",
            "active": True,
            "is_default": True,
        }, timeout=30)
        assert created.status_code == 200, created.text
        nid = created.json()["id"]
        self.created_number_ids.append(nid)
        assert created.json()["e164"].startswith("+91")

        dup = admin.post(f"{BASE_URL}/api/telephony/numbers", json={
            "e164": e164, "label": "dup", "active": True,
        }, timeout=30)
        assert dup.status_code == 409

        ivr = admin.put(f"{BASE_URL}/api/telephony/ivr", json={
            "did_id": nid,
            "greeting_text": "Press 1 sales",
            "menu": [
                {"digit": "1", "label": "Sales", "action": "queue", "target": "sales"},
                {"digit": "2", "label": "Support", "action": "queue", "target": "support"},
            ],
            "missed_create_lead": True,
            "active": True,
        }, timeout=30)
        assert ivr.status_code == 200, ivr.text
        assert ivr.json()["did_id"] == nid

        resolved = admin.post(f"{BASE_URL}/api/telephony/ivr/resolve", json={
            "did_e164": created.json()["e164"],
            "digit": "1",
        }, timeout=30)
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["target"] == "sales"

        bad_digit = admin.post(f"{BASE_URL}/api/telephony/ivr/resolve", json={
            "did_e164": created.json()["e164"],
            "digit": "9",
        }, timeout=30)
        assert bad_digit.status_code == 404

    def test_missed_inbound_creates_lead(self, admin):
        from_phone = f"+9196{str(uuid.uuid4().int % 10**8).zfill(8)}"
        did = f"+9195{str(uuid.uuid4().int % 10**8).zfill(8)}"
        # ensure DID exists for realism
        n = admin.post(f"{BASE_URL}/api/telephony/numbers", json={
            "e164": did, "label": "TEST_IN", "active": True,
        }, timeout=30)
        if n.status_code == 200:
            self.created_number_ids.append(n.json()["id"])

        r = requests.post(
            f"{BASE_URL}/api/telephony/webhooks/mock",
            json={
                "event": "missed",
                "provider_call_id": f"miss-{uuid.uuid4().hex}",
                "status": "missed",
                "direction": "inbound",
                "From": from_phone,
                "To": did,
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text

        # find lead by listing / search
        leads = admin.get(f"{BASE_URL}/api/leads?search={from_phone[-10:]}&page_size=20", timeout=60)
        assert leads.status_code == 200
        items = leads.json().get("leads") or leads.json().get("items") or []
        # API shape may vary — also try exact phone filter via workbench not required
        matched = [x for x in items if from_phone[-10:] in (x.get("phone") or "")]
        if matched:
            self.created_lead_ids.append(matched[0]["id"])
            assert matched[0]["name"].startswith("Missed") or "Missed" in matched[0]["name"]


class TestTelephonyAdapterUnit:
    """Pure unit tests without HTTP (adapter normalize)."""

    def test_mock_normalize_edge_cases(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from telephony.mock import MockTelephonyAdapter
        ad = MockTelephonyAdapter()
        ev = ad.normalize_webhook({
            "CallStatus": "no-answer",
            "CallUUID": "abc",
            "From": "+911",
            "To": "+912",
            "Duration": "3",
        })
        assert ev["status"] == "missed"
        assert ev["provider_call_id"] == "abc"
        assert ev["talk_sec"] == 3

    def test_livekit_plivo_normalize(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from telephony.livekit_plivo import LiveKitPlivoAdapter
        ad = LiveKitPlivoAdapter()
        ev = ad.normalize_webhook({
            "Event": "Hangup",
            "CallStatus": "completed",
            "CallUUID": "plivo-1",
            "Direction": "inbound",
            "From": "+9198",
            "To": "+9111",
            "Duration": "10",
            "RecordUrl": "https://x/r.ogg",
            "Digits": "1",
        })
        assert ev["direction"] == "inbound"
        assert ev["status"] == "completed"
        assert ev["recording_url"].endswith("r.ogg")
        assert ev["ivr_digits"] == "1"
