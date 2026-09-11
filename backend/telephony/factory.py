"""Adapter factory."""
from __future__ import annotations

import os

from telephony.base import TelephonyAdapter
from telephony.mock import MockTelephonyAdapter


def get_adapter() -> TelephonyAdapter:
    provider = (os.environ.get("TELEPHONY_PROVIDER") or "mock").strip().lower()
    if provider in ("plivo_livekit", "livekit", "plivo"):
        from telephony.livekit_plivo import LiveKitPlivoAdapter
        return LiveKitPlivoAdapter()
    return MockTelephonyAdapter()
