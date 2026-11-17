"""Lead import sample CSV: multi-country phones + remarks guide."""
import csv
import io
import sys
from pathlib import Path

import pytest


def _load_backend():
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def test_template_csv_phones_all_parse():
    _load_backend()
    from core import parse_phone
    from lead_import import LEAD_IMPORT_TEMPLATE_HEADERS, build_lead_import_template_csv

    text = build_lead_import_template_csv()
    reader = csv.DictReader(io.StringIO(text))
    assert reader.fieldnames == LEAD_IMPORT_TEMPLATE_HEADERS
    rows = list(reader)
    assert len(rows) >= 8
    phones = []
    for row in rows:
        phone = (row.get("phone") or "").strip()
        assert phone, f"missing phone on row {row.get('name')}"
        e164, country = parse_phone(phone)
        assert e164.startswith("+")
        assert len(country) == 2
        phones.append(e164)
        remarks = row.get("remarks") or ""
        assert remarks.strip(), f"missing remarks on {row.get('name')}"
    assert len(phones) == len(set(phones)), "template phones must be unique for safe upload"
    blob = text.lower()
    assert "+971" in text
    assert "uae" in blob
    assert "without +" in blob or "without +" in text
    assert "trunk" in blob or "+440" in text


def test_import_template_endpoint_auth_deny(anon):
    """RBAC: unauthenticated callers cannot download the template."""
    from conftest import BASE_URL

    r = anon.get(f"{BASE_URL}/api/leads/import/template", timeout=30)
    assert r.status_code in (401, 403)
