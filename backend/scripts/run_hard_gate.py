#!/usr/bin/env python3
"""Hard local gate: hit heavy endpoints against a seeded local DB; record latency + RSS.

Requires API running at REACT_APP_BACKEND_URL (default http://localhost:8000).
Uses admin creds from tests/conftest CREDS / env.
"""
from __future__ import annotations

import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from conftest import BASE_URL, CREDS  # noqa: E402


def _rss_mb(pid: int) -> float | None:
    try:
        import subprocess
        out = subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)], text=True).strip()
        # rss is KB on macOS
        return round(int(out) / 1024.0, 1)
    except Exception:
        return None


def _find_api_pid() -> int | None:
    try:
        import subprocess
        out = subprocess.check_output(["pgrep", "-f", "uvicorn|server:app|python server.py"], text=True)
        pids = [int(x) for x in out.split() if x.strip()]
        return pids[0] if pids else None
    except Exception:
        return None


def login(email: str, password: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=60)
    r.raise_for_status()
    return s


def timed(session: requests.Session, path: str, timeout: int = 180) -> tuple[int, float, dict | None]:
    t0 = time.perf_counter()
    r = session.get(f"{BASE_URL}{path}", timeout=timeout)
    ms = (time.perf_counter() - t0) * 1000
    body = None
    try:
        body = r.json()
    except Exception:
        pass
    return r.status_code, ms, body


def main():
    admin = login(*CREDS["admin"])
    pid = _find_api_pid()
    rss_before = _rss_mb(pid) if pid else None
    results = []

    # Health
    code, ms, _ = timed(admin, "/api/health", timeout=30)
    results.append(("health", code, ms))
    assert code == 200, "health failed"

    # Shape freeze
    code, ms, dash = timed(admin, "/api/dashboard", timeout=180)
    results.append(("dashboard", code, ms))
    assert code == 200 and dash and "kpis" in dash and "aging_sla" in dash
    dash_keys = set(dash.keys())

    code, ms, caller = timed(admin, "/api/reports/caller", timeout=180)
    results.append(("reports_caller", code, ms))
    assert code == 200 and caller and "rows" in caller
    caller_keys = set(caller.keys())

    for label, path in [
        ("pipeline", "/api/pipeline?page_size=50"),
        ("pipeline_counts", "/api/pipeline/counts"),
        ("today_calls", "/api/today-calls?page_size=50"),
        ("today_calls_counts", "/api/today-calls/counts"),
        ("leads_clamp", "/api/leads?page_size=50000"),
        ("company", "/api/reports/company"),
        ("affiliate", "/api/reports/affiliate"),
    ]:
        code, ms, body = timed(admin, path, timeout=180)
        results.append((label, code, ms))
        assert code == 200, f"{label} -> {code}"
        if label == "leads_clamp":
            assert body["page_size"] == 100
        if label == "pipeline":
            assert body.get("page_size") == 50
            assert "board" in body and "has_more" in body
            for stage, col in (body.get("board") or {}).items():
                assert len(col) <= 50
        if label == "pipeline_counts":
            assert "counts" in body and "total" in body
        if label == "today_calls":
            assert body.get("page_size") == 50
            assert "items" in body and "total" in body
        if label == "today_calls_counts":
            assert "counts" in body and "tab_counts" in body

    # Repeat dashboard for RSS drift
    dash_times = []
    for _ in range(5):
        code, ms, body = timed(admin, "/api/dashboard", timeout=180)
        assert code == 200
        assert set(body.keys()) == dash_keys
        dash_times.append(ms)
    results.append(("dashboard_x5_avg", 200, statistics.mean(dash_times)))

    # Concurrent
    def hit(path):
        return timed(admin, path, timeout=180)

    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(hit, "/api/dashboard") for _ in range(5)]
        futs += [ex.submit(hit, "/api/leads?page_size=50") for _ in range(5)]
        for f in as_completed(futs):
            code, ms, _ = f.result()
            assert code == 200, code
    code, ms, _ = timed(admin, "/api/health", timeout=30)
    results.append(("health_after_concurrent", code, ms))
    assert code == 200

    rss_after = _rss_mb(pid) if pid else None
    print("=== Hard local gate results ===")
    for name, code, ms in results:
        print(f"  {name}: status={code} latency_ms={ms:.0f}")
    print(f"  API pid={pid} RSS_before_MB={rss_before} RSS_after_MB={rss_after}")
    if rss_after is not None and rss_after > 900:
        print("WARNING: RSS after > 900 MB (1GB plan proxy)")
        sys.exit(2)
    print("PASS")


if __name__ == "__main__":
    main()
