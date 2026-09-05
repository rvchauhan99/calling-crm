"""Google Sheet lead sync: URL parse, CSV fetch, mapping, insert, scoped auto-assign."""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import timedelta
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import httpx

from core import (
    COMPANY_ID,
    db,
    new_id,
    normalize_and_validate_phone,
    now_iso,
    now_utc,
    validate_email_optional,
)
from lead_constants import LEAD_SOURCES

logger = logging.getLogger(__name__)

SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
MIN_POLL_SECONDS = 60
DEFAULT_POLL_SECONDS = 120
SYNC_LOCK_SECONDS = 300

META_COLUMN_MAP = {
    "name": "full_name",
    "phone": "phone_number",
    "email": "email",
    "city": "",
    "external_id": "id",
}

GENERIC_COLUMN_MAP = {
    "name": "name",
    "phone": "phone",
    "email": "email",
    "city": "city",
    "external_id": "id",
}

META_CUSTOM_FIELDS = [
    "campaign_name",
    "ad_name",
    "adset_name",
    "platform",
    "form_name",
    "created_time",
    "which_instrument_is_used_most_to_trade_?",
    "trading_volume",
    "is_organic",
    "ad_id",
    "adset_id",
    "campaign_id",
    "form_id",
]


class SheetAccessError(Exception):
    """Sheet is private or unreachable."""


class SheetParseError(Exception):
    """Invalid sheet URL or empty CSV."""


def parse_sheet_url(url: str) -> tuple[str, str]:
    """Extract spreadsheet_id and gid from a Google Sheets URL."""
    raw = (url or "").strip()
    if not raw:
        raise SheetParseError("Sheet URL is required")
    m = SHEET_ID_RE.search(raw)
    if not m:
        raise SheetParseError("Invalid Google Sheets URL — expected /spreadsheets/d/{id}")
    spreadsheet_id = m.group(1)
    gid = "0"
    parsed = urlparse(raw)
    qs = parse_qs(parsed.query)
    if "gid" in qs and qs["gid"]:
        gid = qs["gid"][0]
    if parsed.fragment:
        frag_qs = parse_qs(parsed.fragment)
        if "gid" in frag_qs and frag_qs["gid"]:
            gid = frag_qs["gid"][0]
    return spreadsheet_id, str(gid)


def csv_export_url(spreadsheet_id: str, gid: str = "0") -> str:
    return (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        f"/gviz/tq?tqx=out:csv&gid={gid}"
    )


NAME_ALIASES = ("full_name", "full name", "name", "customer name", "lead name")
PHONE_ALIASES = ("phone_number", "phone", "mobile", "number", "whatsapp")
EMAIL_ALIASES = ("email", "e-mail", "email_address", "mail")
CITY_ALIASES = ("city", "location")
EXTERNAL_ID_ALIASES = ("id", "lead_id", "lead_key", "external_id", "meta_id")


def default_column_map(preset: str) -> dict:
    if preset == "meta_lead_ads":
        return dict(META_COLUMN_MAP)
    return dict(GENERIC_COLUMN_MAP)


def _norm_header(h: str) -> str:
    return (h or "").strip().lower()


def normalize_column_map(raw: Optional[dict]) -> dict:
    """Normalize map keys/values; empty strings allowed for optional fields."""
    src = raw or {}
    out = {}
    for key in ("name", "phone", "email", "city", "external_id"):
        val = src.get(key, "")
        out[key] = _norm_header(val) if val else ""
    return out


def validate_column_map(raw: Optional[dict]) -> dict:
    """Require name + phone columns. Raises ValueError on bad input."""
    cmap = normalize_column_map(raw)
    if not cmap.get("name"):
        raise ValueError("Column map requires a Name column")
    if not cmap.get("phone"):
        raise ValueError("Column map requires a Phone column")
    return cmap


def _pick_alias(headers: set, aliases: tuple) -> str:
    for a in aliases:
        if _norm_header(a) in headers:
            return _norm_header(a)
    return ""


def suggest_column_map(headers: list, preset: str = "meta_lead_ads") -> dict:
    """
    Merge preset defaults with available headers.
    Keep default when header exists; otherwise alias-suggest; else empty for missing.
    """
    header_set = {_norm_header(h) for h in (headers or []) if h}
    base = default_column_map(preset)
    suggested = dict(base)

    def resolve(field: str, aliases: tuple) -> str:
        default = _norm_header(base.get(field) or "")
        if default and default in header_set:
            return default
        picked = _pick_alias(header_set, aliases)
        if picked:
            return picked
        # Default header missing and no alias — leave empty so admin must pick
        return ""

    suggested["name"] = resolve("name", NAME_ALIASES)
    suggested["phone"] = resolve("phone", PHONE_ALIASES)
    suggested["email"] = resolve("email", EMAIL_ALIASES)
    suggested["city"] = resolve("city", CITY_ALIASES)
    suggested["external_id"] = resolve("external_id", EXTERNAL_ID_ALIASES)
    return suggested


def _row_get(row: dict, key: str, *aliases: str) -> str:
    if not key:
        return ""
    keys = [key] + list(aliases)
    for k in keys:
        nk = _norm_header(k)
        if nk in row and row[nk]:
            return str(row[nk]).strip()
    return ""


def _cell(row: dict, col: str) -> str:
    """Exact header lookup (normalized)."""
    if not col:
        return ""
    return str(row.get(_norm_header(col)) or "").strip()


def _is_meta_test_row(row: dict, name: str, phone_raw: str, email: str) -> bool:
    email_l = (email or "").lower()
    if email_l == "test@meta.com":
        return True
    if "test lead" in (phone_raw or "").lower():
        return True
    if "test lead" in (name or "").lower():
        return True
    if "<test lead" in " ".join(str(v) for v in row.values()).lower():
        return True
    return False


def map_row(row: dict, column_map: dict, preset: str) -> Optional[dict]:
    """Map a normalized CSV row to lead fields, or None if skip/invalid."""
    cmap = normalize_column_map(column_map) if column_map else default_column_map(preset)
    name_col = cmap.get("name") or ""
    phone_col = cmap.get("phone") or ""
    email_col = cmap.get("email") or ""
    city_col = cmap.get("city") or ""
    ext_col = cmap.get("external_id") or ""

    # Exact mapped columns only (UI / suggested_map owns aliases)
    name = _cell(row, name_col)
    phone_raw = _cell(row, phone_col)
    email_raw = _cell(row, email_col)
    city = _cell(row, city_col)
    external_id = _cell(row, ext_col)

    if _is_meta_test_row(row, name, phone_raw, email_raw):
        return None

    if not name or not phone_raw:
        return None

    try:
        phone = normalize_and_validate_phone(phone_raw)
    except ValueError:
        return None

    try:
        email = validate_email_optional(email_raw)
    except ValueError:
        email = ""

    custom_fields: dict[str, Any] = {}
    if preset == "meta_lead_ads":
        for cf in META_CUSTOM_FIELDS:
            val = _row_get(row, cf)
            if val:
                custom_fields[cf] = val

    return {
        "name": name,
        "phone": phone,
        "email": email,
        "city": city,
        "external_id": external_id or None,
        "custom_fields": custom_fields,
    }


def parse_csv_rows(content: str) -> tuple[list[str], list[dict]]:
    """Parse CSV text into headers and normalized row dicts."""
    text = (content or "").strip()
    if not text:
        return [], []
    reader = csv.DictReader(io.StringIO(text))
    headers = [_norm_header(h) for h in (reader.fieldnames or [])]
    rows = []
    for raw in reader:
        row = {_norm_header(k): (v or "").strip() for k, v in raw.items() if k is not None}
        if any(row.values()):
            rows.append(row)
    return headers, rows


async def fetch_sheet_csv(spreadsheet_id: str, gid: str = "0", *, client: Optional[httpx.AsyncClient] = None) -> str:
    url = csv_export_url(spreadsheet_id, gid)
    own_client = client is None
    http = client or httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    try:
        resp = await http.get(url)
        if resp.status_code in (401, 403):
            raise SheetAccessError(
                "Cannot access sheet — share it as 'Anyone with the link can view'"
            )
        if resp.status_code >= 400:
            raise SheetAccessError(f"Google returned HTTP {resp.status_code}")
        content_type = (resp.headers.get("content-type") or "").lower()
        text = resp.text
        if "text/html" in content_type and "<html" in text[:500].lower():
            raise SheetAccessError(
                "Cannot access sheet — share it as 'Anyone with the link can view'"
            )
        return text
    finally:
        if own_client:
            await http.aclose()


async def auto_assign_lead_ids(lead_ids: list[str]) -> int:
    """Quota-walk assign only the given lead IDs (newly created). Returns assigned count."""
    if not lead_ids:
        return 0
    agents = await db.users.find(
        {"companyId": COMPANY_ID, "user_type": "caller", "active": True},
        {"_id": 0},
    ).to_list(100)
    if not agents:
        return 0
    today = now_utc().date().isoformat()
    pool = await db.leads.find(
        {
            "companyId": COMPANY_ID,
            "id": {"$in": lead_ids},
            "status": "active",
            "is_client": False,
            "assigned_to": None,
        },
        {"_id": 0},
    ).to_list(len(lead_ids))
    # Preserve insert order from lead_ids
    by_id = {l["id"]: l for l in pool}
    ordered = [by_id[lid] for lid in lead_ids if lid in by_id]
    idx = 0
    total = 0
    for agent in agents:
        quota = agent.get("daily_quota", 0) or 0
        assigned_today = await db.leads.count_documents(
            {"assigned_to": agent["id"], "assigned_date": today}
        )
        slots = max(0, quota - assigned_today)
        for _ in range(slots):
            if idx >= len(ordered):
                break
            lead = ordered[idx]
            idx += 1
            await db.leads.update_one(
                {"id": lead["id"]},
                {"$set": {
                    "assigned_to": agent["id"],
                    "assigned_name": agent["name"],
                    "owner_id": agent["id"],
                    "assigned_date": today,
                }},
            )
            total += 1
        if idx >= len(ordered):
            break
    return total


async def try_acquire_sync_lock(source_id: str) -> bool:
    """Atomic lock; returns True if this caller owns the sync."""
    now = now_utc()
    until = now + timedelta(seconds=SYNC_LOCK_SECONDS)
    result = await db.sheet_sources.update_one(
        {
            "id": source_id,
            "companyId": COMPANY_ID,
            "$or": [
                {"syncing": {"$ne": True}},
                {"sync_lock_until": {"$lte": now.isoformat()}},
                {"sync_lock_until": None},
                {"sync_lock_until": {"$exists": False}},
            ],
        },
        {"$set": {
            "syncing": True,
            "sync_lock_until": until.isoformat(),
        }},
    )
    return result.modified_count == 1


async def release_sync_lock(source_id: str) -> None:
    await db.sheet_sources.update_one(
        {"id": source_id, "companyId": COMPANY_ID},
        {"$set": {"syncing": False, "sync_lock_until": None}},
    )


async def preview_source(source: dict, *, csv_text: Optional[str] = None) -> dict:
    """Fetch and map first 5 rows without inserting."""
    if csv_text is None:
        csv_text = await fetch_sheet_csv(source["spreadsheet_id"], source.get("gid") or "0")
    headers, rows = parse_csv_rows(csv_text)
    preset = source.get("preset") or "generic"
    cmap = source.get("column_map") or default_column_map(preset)
    mapped = []
    skipped = 0
    for row in rows[:50]:
        m = map_row(row, cmap, preset)
        if m is None:
            skipped += 1
            continue
        mapped.append(m)
        if len(mapped) >= 5:
            break
    return {
        "headers": headers,
        "rows": mapped,
        "total_rows_scanned": min(len(rows), 50),
        "skipped_in_scan": skipped,
    }


async def inspect_sheet(
    sheet_url: str,
    *,
    preset: str = "meta_lead_ads",
    csv_text: Optional[str] = None,
) -> dict:
    """Parse URL, fetch headers, return suggested column_map for preset."""
    spreadsheet_id, gid = parse_sheet_url(sheet_url)
    if csv_text is None:
        csv_text = await fetch_sheet_csv(spreadsheet_id, gid)
    headers, _rows = parse_csv_rows(csv_text)
    suggested = suggest_column_map(headers, preset or "meta_lead_ads")
    return {
        "spreadsheet_id": spreadsheet_id,
        "gid": gid,
        "headers": headers,
        "suggested_map": suggested,
    }


async def preview_draft(
    *,
    sheet_url: str,
    preset: str = "meta_lead_ads",
    column_map: Optional[dict] = None,
    csv_text: Optional[str] = None,
) -> dict:
    """Preview mapped rows before a source is saved."""
    spreadsheet_id, gid = parse_sheet_url(sheet_url)
    source = {
        "spreadsheet_id": spreadsheet_id,
        "gid": gid,
        "preset": preset or "meta_lead_ads",
        "column_map": column_map or default_column_map(preset or "meta_lead_ads"),
    }
    return await preview_source(source, csv_text=csv_text)


async def sync_source(
    source: dict,
    *,
    csv_text: Optional[str] = None,
    acquire_lock: bool = True,
) -> dict:
    """Pull sheet rows and insert new leads. Returns result counts."""
    source_id = source["id"]
    if acquire_lock:
        got = await try_acquire_sync_lock(source_id)
        if not got:
            return {
                "created": 0,
                "duplicates": 0,
                "invalid": 0,
                "assigned": 0,
                "skipped": 0,
                "status": "skipped",
                "error": "Sync already in progress",
            }

    result = {
        "created": 0,
        "duplicates": 0,
        "invalid": 0,
        "assigned": 0,
        "skipped": 0,
        "status": "ok",
        "error": None,
    }
    created_ids: list[str] = []
    try:
        if csv_text is None:
            csv_text = await fetch_sheet_csv(
                source["spreadsheet_id"], source.get("gid") or "0"
            )
        headers, rows = parse_csv_rows(csv_text)
        if not headers and not rows:
            result["status"] = "ok"
            # empty sheet is fine
        else:
            preset = source.get("preset") or "generic"
            cmap = source.get("column_map") or default_column_map(preset)
            lead_source = source.get("source") or "Facebook Ads"
            if lead_source not in LEAD_SOURCES:
                lead_source = "Import"

            for row in rows:
                mapped = map_row(row, cmap, preset)
                if mapped is None:
                    # Distinguish empty trailing vs invalid
                    if not any(row.values()):
                        result["skipped"] += 1
                    else:
                        result["invalid"] += 1
                    continue

                external_id = mapped.get("external_id")
                if external_id:
                    existing_ext = await db.leads.find_one({
                        "companyId": COMPANY_ID,
                        "sheet_source_id": source_id,
                        "external_id": external_id,
                    })
                    if existing_ext:
                        result["duplicates"] += 1
                        continue

                if await db.leads.find_one({
                    "companyId": COMPANY_ID,
                    "phone": mapped["phone"],
                }):
                    result["duplicates"] += 1
                    continue

                lid = new_id()
                doc = {
                    "id": lid,
                    "companyId": COMPANY_ID,
                    "name": mapped["name"],
                    "phone": mapped["phone"],
                    "email": mapped["email"],
                    "source": lead_source,
                    "city": mapped.get("city") or "",
                    "status": "active",
                    "assigned_to": None,
                    "assigned_name": None,
                    "owner_id": None,
                    "disposition_id": None,
                    "disposition_name": None,
                    "carry_forward": True,
                    "pipeline_stage": "New",
                    "custom_fields": mapped.get("custom_fields") or {},
                    "follow_up_at": None,
                    "is_client": False,
                    "client_id": None,
                    "assigned_date": None,
                    "external_id": external_id,
                    "sheet_source_id": source_id,
                    "sheet_source_name": source.get("name"),
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                }
                await db.leads.insert_one(dict(doc))
                created_ids.append(lid)
                result["created"] += 1

            if source.get("auto_assign") and created_ids:
                result["assigned"] = await auto_assign_lead_ids(created_ids)

    except (SheetAccessError, SheetParseError) as e:
        result["status"] = "error"
        result["error"] = str(e)
        logger.warning("Sheet sync failed for %s: %s", source_id, e)
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"Sync failed: {e}"
        logger.exception("Sheet sync unexpected error for %s", source_id)
    finally:
        run_doc = {
            "id": new_id(),
            "companyId": COMPANY_ID,
            "sheet_source_id": source_id,
            "created": result["created"],
            "duplicates": result["duplicates"],
            "invalid": result["invalid"],
            "assigned": result["assigned"],
            "skipped": result["skipped"],
            "status": result["status"],
            "error": result["error"],
            "created_at": now_iso(),
        }
        await db.sheet_sync_runs.insert_one(dict(run_doc))
        await db.sheet_sources.update_one(
            {"id": source_id, "companyId": COMPANY_ID},
            {"$set": {
                "last_synced_at": now_iso(),
                "last_status": result["status"],
                "last_error": result["error"],
                "last_result": {
                    "created": result["created"],
                    "duplicates": result["duplicates"],
                    "invalid": result["invalid"],
                    "assigned": result["assigned"],
                    "skipped": result["skipped"],
                },
                "syncing": False,
                "sync_lock_until": None,
            }},
        )
    return result
