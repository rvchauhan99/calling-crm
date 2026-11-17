"""Chunked CSV lead import with original-column error records."""
import asyncio
import csv
import io
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional

from pymongo import UpdateOne

from core import COMPANY_ID, db, invalid_phone_reason, new_id, now_iso, parse_phone
from lead_sources import source_names

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_IMPORT_ROWS = 50_000
CHUNK_SIZE = 500

NAME_ALIASES = ("name", "full name")
PHONE_ALIASES = ("phone", "mobile", "number")
EMAIL_ALIASES = ("email",)
CITY_ALIASES = ("city",)
SOURCE_ALIASES = ("source",)

LEAD_IMPORT_TEMPLATE_HEADERS = ["name", "phone", "email", "city", "source", "remarks"]

# Valid sample rows only (safe if uploaded as-is). remarks is teaching text — not imported as a lead field.
LEAD_IMPORT_TEMPLATE_ROWS = [
    {
        "name": "READ ME — delete sample rows before real import",
        "phone": "9876543200",
        "email": "sample@example.com",
        "city": "Mumbai",
        "source": "Import",
        "remarks": (
            "GOLDEN RULES: (1) Numbers without + are treated as India (+91). "
            "(2) Non-India phones MUST start with + and the country code "
            "(UAE +9715… not 9715…). (3) Never keep the local trunk 0 after the country code "
            "(UK use +447… not +4407…). (4) source must match an active Lead Source. "
            "(5) Delete these sample rows before importing your real list."
        ),
    },
    {
        "name": "Sample India local 10-digit",
        "phone": "9876543210",
        "email": "sample@example.com",
        "city": "Mumbai",
        "source": "Website",
        "remarks": "India only: 10 digits without + are OK and become +91. Do NOT use this style for UAE/UK/US.",
    },
    {
        "name": "Sample India E.164",
        "phone": "+919876543211",
        "email": "sample@example.com",
        "city": "Delhi",
        "source": "Facebook Ads",
        "remarks": "Preferred: +91 plus 10 Indian mobile digits starting with 6-9.",
    },
    {
        "name": "Sample UAE mobile",
        "phone": "+971501234567",
        "email": "sample@example.com",
        "city": "Dubai",
        "source": "Google Ads",
        "remarks": "UAE: always +971 then the mobile (usually starts with 5). Bare 9715xxxxxxxx WITHOUT + fails (parsed as India).",
    },
    {
        "name": "Sample UK mobile",
        "phone": "+447426717733",
        "email": "sample@example.com",
        "city": "London",
        "source": "Referral",
        "remarks": "UK: +44 plus national digits with NO 0 after +44. Wrong: +4407426717733 (trunk 0).",
    },
    {
        "name": "Sample US mobile",
        "phone": "+14155552671",
        "email": "sample@example.com",
        "city": "San Francisco",
        "source": "Cold List",
        "remarks": "US/Canada: always +1 then 10 digits.",
    },
    {
        "name": "Sample Pakistan mobile",
        "phone": "+923001234567",
        "email": "sample@example.com",
        "city": "Karachi",
        "source": "Webinar",
        "remarks": "Pakistan: always +92 + national mobile digits. Without + it is treated as India and fails.",
    },
    {
        "name": "Sample Saudi mobile",
        "phone": "+966501234567",
        "email": "sample@example.com",
        "city": "Riyadh",
        "source": "Manual",
        "remarks": "Saudi Arabia: always +966 + national mobile digits.",
    },
    {
        "name": "Sample Bangladesh mobile",
        "phone": "+8801712345678",
        "email": "sample@example.com",
        "city": "Dhaka",
        "source": "Import",
        "remarks": "Bangladesh: always +880 + national mobile digits.",
    },
    {
        "name": "Sample Meta phone prefix",
        "phone": "p:+918847490594",
        "email": "sample@example.com",
        "city": "Bengaluru",
        "source": "Import",
        "remarks": "Supported: leading p: is stripped (Meta-style). Still use +countryCode for non-India.",
    },
]


def build_lead_import_template_csv() -> str:
    """CSV sample guide for lead import (valid phones + teaching remarks)."""
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=LEAD_IMPORT_TEMPLATE_HEADERS,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in LEAD_IMPORT_TEMPLATE_ROWS:
        writer.writerow({h: row.get(h, "") for h in LEAD_IMPORT_TEMPLATE_HEADERS})
    return buf.getvalue()


@dataclass
class ImportErrorRow:
    row: int
    reason: str
    row_data: dict


IMPORT_SOURCE_NAME = "Import"


@dataclass
class ImportProgress:
    total: int = 0
    processed: int = 0
    created: int = 0
    duplicates: int = 0
    updated: int = 0
    invalid: int = 0
    skipped: int = 0


@dataclass
class ImportResult:
    created: int = 0
    duplicates: int = 0
    updated: int = 0
    invalid: int = 0
    skipped: int = 0
    total: int = 0
    original_headers: List[str] = field(default_factory=list)
    error_rows: List[ImportErrorRow] = field(default_factory=list)


ProgressCallback = Optional[Callable[[ImportProgress], Awaitable[None]]]


class ImportValidationError(ValueError):
    """Raised when a file cannot be accepted (empty, missing headers, over cap)."""


def _original_headers(fieldnames) -> List[str]:
    headers = []
    seen = set()
    for raw in fieldnames or []:
        name = (raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        headers.append(name)
    return headers


def _row_data(row: dict, headers: List[str], fieldnames) -> dict:
    raw_by_stripped = {}
    for orig in fieldnames or []:
        stripped = (orig or "").strip()
        if not stripped:
            continue
        val = row.get(orig)
        raw_by_stripped[stripped] = "" if val is None else str(val)
    return {h: raw_by_stripped.get(h, "") for h in headers}


def _cell(row_data: dict, header_lookup: dict, aliases: tuple) -> str:
    for alias in aliases:
        key = header_lookup.get(alias)
        if key is None:
            continue
        return (row_data.get(key) or "").strip()
    return ""


def _is_empty_row(row_data: dict) -> bool:
    return not any((v or "").strip() for v in row_data.values())


def _lead_doc(
    name: str,
    phone: str,
    email: str,
    source: str,
    city: str,
    phone_country: str = "IN",
    *,
    created_by: str = None,
    created_by_name: str = None,
) -> dict:
    ts = now_iso()
    return {
        "id": new_id(),
        "companyId": COMPANY_ID,
        "name": name,
        "phone": phone,
        "phone_country": phone_country,
        "email": email,
        "source": source,
        "city": city,
        "status": "active",
        "assigned_to": None,
        "assigned_name": None,
        "owner_id": None,
        "disposition_id": None,
        "disposition_name": None,
        "carry_forward": True,
        "pipeline_stage": "New",
        "custom_fields": {},
        "follow_up_at": None,
        "is_client": False,
        "client_id": None,
        "assigned_date": None,
        "last_notes": None,
        "last_notes_at": None,
        "created_by": created_by,
        "created_by_name": created_by_name,
        "created_at": ts,
        "updated_at": ts,
    }


def parse_lead_csv(content: str) -> tuple:
    """Return (headers, rows as (excel_row, row_data)). Raises ImportValidationError."""
    reader = csv.DictReader(io.StringIO(content))
    headers = _original_headers(reader.fieldnames)
    if not headers:
        raise ImportValidationError("CSV is missing a header row")
    rows = []
    for index, row in enumerate(reader, start=2):
        if index - 1 > MAX_IMPORT_ROWS:
            raise ImportValidationError(f"CSV exceeds the {MAX_IMPORT_ROWS} row limit")
        rows.append((index, _row_data(row, headers, reader.fieldnames)))
    if len(rows) > MAX_IMPORT_ROWS:
        raise ImportValidationError(f"CSV exceeds the {MAX_IMPORT_ROWS} row limit")
    return headers, rows


def count_csv_data_rows(content: str) -> int:
    reader = csv.DictReader(io.StringIO(content))
    if not _original_headers(reader.fieldnames):
        raise ImportValidationError("CSV is missing a header row")
    n = 0
    for _ in reader:
        n += 1
        if n > MAX_IMPORT_ROWS:
            raise ImportValidationError(f"CSV exceeds the {MAX_IMPORT_ROWS} row limit")
    return n


def build_error_csv(headers: List[str], error_rows: List[ImportErrorRow]) -> str:
    fieldnames = list(headers) + ["error_reason"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for err in error_rows:
        out = {h: (err.row_data or {}).get(h, "") for h in headers}
        out["error_reason"] = err.reason
        writer.writerow(out)
    return buf.getvalue()


def decode_import_bytes(raw: bytes) -> str:
    if not raw:
        raise ImportValidationError("CSV file is empty")
    if len(raw) > MAX_FILE_BYTES:
        raise ImportValidationError("File exceeds the 10 MB limit")
    text = raw.decode("utf-8", errors="ignore")
    if not text.strip():
        raise ImportValidationError("CSV file is empty")
    return text


async def run_lead_import(
    raw: bytes,
    on_progress: ProgressCallback = None,
    *,
    created_by: str = None,
    created_by_name: str = None,
) -> ImportResult:
    text = decode_import_bytes(raw)
    headers, rows = parse_lead_csv(text)
    header_lookup = {h.lower(): h for h in headers}
    result = ImportResult(total=len(rows), original_headers=headers)
    progress = ImportProgress(total=len(rows))

    async def emit():
        if on_progress:
            await on_progress(ImportProgress(
                total=progress.total,
                processed=progress.processed,
                created=progress.created,
                duplicates=progress.duplicates,
                updated=progress.updated,
                invalid=progress.invalid,
                skipped=progress.skipped,
            ))

    candidates = []
    seen_phones = set()
    allowed_sources = set(await source_names(active_only=True, creatable_only=False))

    for excel_row, row_data in rows:
        if _is_empty_row(row_data):
            progress.skipped += 1
            progress.processed += 1
            result.skipped += 1
            continue
        name = _cell(row_data, header_lookup, NAME_ALIASES)
        if not name:
            progress.invalid += 1
            progress.processed += 1
            result.invalid += 1
            result.error_rows.append(ImportErrorRow(excel_row, "Name is required", row_data))
            continue
        raw_phone = _cell(row_data, header_lookup, PHONE_ALIASES)
        try:
            phone, phone_country = parse_phone(raw_phone)
        except ValueError:
            progress.invalid += 1
            progress.processed += 1
            result.invalid += 1
            result.error_rows.append(
                ImportErrorRow(excel_row, invalid_phone_reason(raw_phone), row_data)
            )
            continue
        source = _cell(row_data, header_lookup, SOURCE_ALIASES) or "Import"
        if source not in allowed_sources:
            progress.invalid += 1
            progress.processed += 1
            result.invalid += 1
            result.error_rows.append(ImportErrorRow(excel_row, "Invalid source", row_data))
            continue
        if phone in seen_phones:
            progress.duplicates += 1
            progress.processed += 1
            result.duplicates += 1
            result.error_rows.append(ImportErrorRow(excel_row, "Duplicate phone", row_data))
            continue
        seen_phones.add(phone)
        candidates.append({
            "row": excel_row,
            "row_data": row_data,
            "name": name,
            "phone": phone,
            "phone_country": phone_country,
            "email": _cell(row_data, header_lookup, EMAIL_ALIASES),
            "source": source,
            "city": _cell(row_data, header_lookup, CITY_ALIASES),
        })

    await emit()

    for offset in range(0, len(candidates), CHUNK_SIZE):
        chunk = candidates[offset:offset + CHUNK_SIZE]
        phones = [item["phone"] for item in chunk]
        existing_by_phone = {}
        if phones:
            cursor = db.leads.find(
                {"companyId": COMPANY_ID, "phone": {"$in": phones}},
                {"_id": 0, "id": 1, "phone": 1, "source": 1},
            )
            async for doc in cursor:
                phone = doc.get("phone")
                if phone and phone not in existing_by_phone:
                    existing_by_phone[phone] = doc
        to_insert = []
        source_updates = []
        for item in chunk:
            existing = existing_by_phone.get(item["phone"])
            if existing:
                progress.duplicates += 1
                result.duplicates += 1
                existing_source = (existing.get("source") or "").strip()
                csv_source = item["source"]
                if (
                    existing_source == IMPORT_SOURCE_NAME
                    and csv_source != IMPORT_SOURCE_NAME
                    and existing.get("id")
                ):
                    source_updates.append({
                        "id": existing["id"],
                        "phone": item["phone"],
                        "source": csv_source,
                        "row": item["row"],
                        "row_data": item["row_data"],
                    })
                else:
                    result.error_rows.append(
                        ImportErrorRow(item["row"], "Duplicate phone", item["row_data"])
                    )
            else:
                to_insert.append(_lead_doc(
                    item["name"], item["phone"], item["email"], item["source"], item["city"],
                    phone_country=item["phone_country"],
                    created_by=created_by,
                    created_by_name=created_by_name,
                ))
                existing_by_phone[item["phone"]] = {
                    "id": None,
                    "phone": item["phone"],
                    "source": item["source"],
                }
            progress.processed += 1
        if source_updates:
            ts = now_iso()
            ops = [
                UpdateOne(
                    {"companyId": COMPANY_ID, "id": upd["id"]},
                    {"$set": {"source": upd["source"], "updated_at": ts}},
                )
                for upd in source_updates
            ]
            await db.leads.bulk_write(ops, ordered=False)
            for upd in source_updates:
                existing_by_phone[upd["phone"]] = {
                    "id": upd["id"],
                    "phone": upd["phone"],
                    "source": upd["source"],
                }
                progress.updated += 1
                result.updated += 1
                result.error_rows.append(
                    ImportErrorRow(
                        upd["row"],
                        "Duplicate phone; source updated",
                        upd["row_data"],
                    )
                )
        if to_insert:
            await db.leads.insert_many(to_insert)
            progress.created += len(to_insert)
            result.created += len(to_insert)
        await emit()
        await asyncio.sleep(0)

    result.total = progress.total
    return result
