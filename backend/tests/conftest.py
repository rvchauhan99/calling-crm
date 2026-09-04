import os
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
frontend_env = dotenv_values(ROOT / "frontend" / ".env")
backend_env = dotenv_values(ROOT / "backend" / ".env")

base_url = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or frontend_env.get("REACT_APP_BACKEND_URL")
    or "http://localhost:8000"
)
BASE_URL = base_url.rstrip("/")

admin_email = (
    os.environ.get("ADMIN_EMAIL")
    or backend_env.get("ADMIN_EMAIL")
    or "admin@localhost"
)
admin_password = (
    os.environ.get("ADMIN_PASSWORD")
    or backend_env.get("ADMIN_PASSWORD")
    or "ChangeMe_Admin_123!"
)
demo_password = (
    os.environ.get("DEMO_PASSWORD")
    or backend_env.get("DEMO_PASSWORD")
    or "Passw0rd!"
)

CREDS = {
    "admin": (admin_email.lower(), admin_password),
    "supervisor": ("supervisor@callingcrm.com", demo_password),
    "agent": ("rohan@callingcrm.com", demo_password),
    "affiliate": ("affiliate@callingcrm.com", demo_password),
}


def login(role):
    email, password = CREDS[role]
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    if r.status_code != 200:
        pytest.fail(f"Login failed for {role}: {r.status_code} {r.text[:300]}")
    data = r.json()
    token = data.get("access_token")
    if not token:
        pytest.fail(f"No access_token for {role}: {data}")
    return token, data.get("user", {})


def client_for(role):
    token, user = login(role)
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    s.user = user
    return s


@pytest.fixture(scope="session")
def anon():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin():
    return client_for("admin")


@pytest.fixture(scope="session")
def supervisor():
    return client_for("supervisor")


@pytest.fixture(scope="session")
def agent():
    return client_for("agent")


@pytest.fixture(scope="session")
def affiliate():
    return client_for("affiliate")


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL
