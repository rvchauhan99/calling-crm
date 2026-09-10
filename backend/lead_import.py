"""Chunked CSV lead import with original-column error records."""
import asyncio
import csv
import io
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional

from core import COMPANY_ID, db, new_id, now_iso, normalize_and_validate_phone
from lead_sources import source_names

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_IMPORT_ROWS = 50_000
CHUNK_SIZE = 500

NAME_ALIASES = ("name", "full name")
PHONE_ALIASES = ("phone", "mobile", "number")
EMAIL_ALIASES = ("email",)
CITY_ALIASES = ("city",)
SOURCE_ALIASES = ("source",)


@dataclass
class ImportErrorRow:
    row: int
    reason: str
    row_data: dict


@dataclass
class ImportProgress:
    total: int = 0
    processed: int = 0
    created: int = 0
    duplicates: int = 0
    invalid: int = 0
    skipped: int = 0


@dataclass
class ImportResult:
    created: int = 0
    duplicates: int = 0
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


def _lead_doc(name: str, phone: str, email: str, source: str, city: str) -> dict:
    ts = now_iso()
    return {
        "id": new_id(),
        "companyId": COMPANY_ID,
        "name": name,
        "phone": phone,
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


async def run_lead_import(raw: bytes, on_progress: ProgressCallback = None) -> ImportResult:
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
            phone = normalize_and_validate_phone(raw_phone)
        except ValueError as exc:
            progress.invalid += 1
            progress.processed += 1
            result.invalid += 1
            result.error_rows.append(ImportErrorRow(excel_row, str(exc), row_data))
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
            "email": _cell(row_data, header_lookup, EMAIL_ALIASES),
            "source": source,
            "city": _cell(row_data, header_lookup, CITY_ALIASES),
        })

    await emit()

    for offset in range(0, len(candidates), CHUNK_SIZE):
        chunk = candidates[offset:offset + CHUNK_SIZE]
        phones = [item["phone"] for item in chunk]
        existing = set()
        if phones:
            cursor = db.leads.find(
                {"companyId": COMPANY_ID, "phone": {"$in": phones}},
                {"_id": 0, "phone": 1},
            )
            existing = {doc["phone"] async for doc in cursor if doc.get("phone")}
        to_insert = []
        for item in chunk:
            if item["phone"] in existing:
                progress.duplicates += 1
                result.duplicates += 1
                result.error_rows.append(
                    ImportErrorRow(item["row"], "Duplicate phone", item["row_data"])
                )
            else:
                to_insert.append(_lead_doc(
                    item["name"], item["phone"], item["email"], item["source"], item["city"],
                ))
                existing.add(item["phone"])
            progress.processed += 1
        if to_insert:
            await db.leads.insert_many(to_insert)
            progress.created += len(to_insert)
            result.created += len(to_insert)
        await emit()
        await asyncio.sleep(0)

    result.total = progress.total
    return result
