"""FRONTEND_URL multi-origin parsing and CORS allow/deny."""
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
load_dotenv(_root / ".env")

from core import DEFAULT_FRONTEND_ORIGIN, parse_frontend_origins, primary_frontend_url


class TestParseFrontendOrigins:
    def test_single_origin(self):
        assert parse_frontend_origins("https://baazexcalling.vercel.app") == [
            "https://baazexcalling.vercel.app",
            "https://www.baazexcalling.vercel.app",
        ]

    def test_comma_separated_prod_shape(self):
        raw = "https://baazexcalling.vercel.app,https://baazexcall.com/"
        assert parse_frontend_origins(raw) == [
            "https://baazexcalling.vercel.app",
            "https://www.baazexcalling.vercel.app",
            "https://baazexcall.com",
            "https://www.baazexcall.com",
        ]

    def test_spaces_around_commas(self):
        raw = " https://a.example.com , https://b.example.com "
        assert parse_frontend_origins(raw) == [
            "https://a.example.com",
            "https://www.a.example.com",
            "https://b.example.com",
            "https://www.b.example.com",
        ]

    def test_trailing_slash_stripped(self):
        assert parse_frontend_origins("https://baazexcall.com/") == [
            "https://baazexcall.com",
            "https://www.baazexcall.com",
        ]

    def test_www_config_includes_apex(self):
        assert parse_frontend_origins("https://www.baazexcall.com") == [
            "https://www.baazexcall.com",
            "https://baazexcall.com",
        ]

    def test_localhost_no_www_sibling(self):
        assert parse_frontend_origins("http://localhost:3000") == [
            "http://localhost:3000"
        ]

    def test_empty_string_defaults(self):
        assert parse_frontend_origins("") == [DEFAULT_FRONTEND_ORIGIN]
        assert parse_frontend_origins("  ,  , ") == [DEFAULT_FRONTEND_ORIGIN]

    def test_none_uses_env_or_default(self, monkeypatch):
        monkeypatch.delenv("FRONTEND_URL", raising=False)
        assert parse_frontend_origins(None) == [DEFAULT_FRONTEND_ORIGIN]
        monkeypatch.setenv(
            "FRONTEND_URL",
            "https://baazexcalling.vercel.app, https://baazexcall.com/",
        )
        assert parse_frontend_origins(None) == [
            "https://baazexcalling.vercel.app",
            "https://www.baazexcalling.vercel.app",
            "https://baazexcall.com",
            "https://www.baazexcall.com",
        ]

    def test_primary_frontend_url_is_first_configured(self, monkeypatch):
        monkeypatch.setenv(
            "FRONTEND_URL",
            "https://baazexcalling.vercel.app,https://baazexcall.com/",
        )
        assert primary_frontend_url() == "https://baazexcalling.vercel.app"


def _cors_app(origins: list[str]) -> TestClient:
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"ok": True}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return TestClient(app)


class TestCorsAllowDeny:
    def test_second_listed_origin_allowed(self):
        origins = parse_frontend_origins(
            "https://baazexcalling.vercel.app,https://baazexcall.com/"
        )
        client = _cors_app(origins)
        r = client.get(
            "/api/health",
            headers={"Origin": "https://baazexcall.com"},
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "https://baazexcall.com"

    def test_apex_config_allows_www_origin(self):
        origins = parse_frontend_origins("https://baazexcall.com")
        client = _cors_app(origins)
        r = client.get(
            "/api/health",
            headers={"Origin": "https://www.baazexcall.com"},
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == (
            "https://www.baazexcall.com"
        )

    def test_www_config_allows_apex_origin(self):
        origins = parse_frontend_origins("https://www.baazexcall.com")
        client = _cors_app(origins)
        r = client.get(
            "/api/health",
            headers={"Origin": "https://baazexcall.com"},
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "https://baazexcall.com"

    def test_unmatched_origin_denied(self):
        origins = parse_frontend_origins(
            "https://baazexcalling.vercel.app,https://baazexcall.com/"
        )
        client = _cors_app(origins)
        r = client.get(
            "/api/health",
            headers={"Origin": "https://evil.example"},
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") is None
