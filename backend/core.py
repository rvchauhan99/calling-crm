"""Core: config, db, auth utils, RBAC dependencies, helpers."""
import os
import re
from typing import Optional

import jwt
import bcrypt
import uuid
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from fastapi import Request, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
COMPANY_ID = os.environ.get("COMPANY_ID", "default")
JWT_ALGORITHM = "HS256"
DEFAULT_FRONTEND_ORIGIN = "http://localhost:3000"
_IPV4_HOST = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def _www_apex_sibling(origin: str) -> str | None:
    """Return www↔apex sibling origin, or None for localhost / IPs / unparseable."""
    parsed = urlparse(origin)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    host = parsed.hostname.lower()
    if host in ("localhost", "127.0.0.1", "::1") or _IPV4_HOST.match(host):
        return None
    port = f":{parsed.port}" if parsed.port else ""
    if host.startswith("www."):
        sibling_host = host[4:]
        if not sibling_host:
            return None
    else:
        sibling_host = f"www.{host}"
    return f"{parsed.scheme}://{sibling_host}{port}"


def parse_frontend_origins(value: str | None = None) -> list[str]:
    """Parse FRONTEND_URL as one or more comma-separated CORS origins.

    Trims whitespace and trailing slashes (browsers send Origin without a path).
    Also allows the www / non-www sibling for each http(s) host so apex and www
    both work when either is configured. Falls back to DEFAULT_FRONTEND_ORIGIN
    when unset or empty.
    """
    raw = os.environ.get("FRONTEND_URL") if value is None else value
    if raw is None or not str(raw).strip():
        return [DEFAULT_FRONTEND_ORIGIN]
    origins: list[str] = []
    seen: set[str] = set()
    for part in str(raw).split(","):
        origin = part.strip()
        while origin.endswith("/") and not origin.endswith("://"):
            origin = origin[:-1]
        if not origin or origin in seen:
            continue
        origins.append(origin)
        seen.add(origin)
        sibling = _www_apex_sibling(origin)
        if sibling and sibling not in seen:
            origins.append(sibling)
            seen.add(sibling)
    return origins or [DEFAULT_FRONTEND_ORIGIN]


def primary_frontend_url() -> str:
    """First configured FRONTEND_URL origin (before www sibling) for reset links."""
    raw = os.environ.get("FRONTEND_URL")
    if raw is None or not str(raw).strip():
        return DEFAULT_FRONTEND_ORIGIN
    for part in str(raw).split(","):
        origin = part.strip()
        while origin.endswith("/") and not origin.endswith("://"):
            origin = origin[:-1]
        if origin:
            return origin
    return DEFAULT_FRONTEND_ORIGIN

client = AsyncIOMotorClient(
    MONGO_URL,
    serverSelectionTimeoutMS=8000,
    maxPoolSize=20,
    minPoolSize=0,
    maxIdleTimeMS=30000,
)
db = client[DB_NAME]

# Global list pagination ceiling (matches followups); prevents huge page_size OOM.
PAGE_SIZE_MAX = 100
LEADS_PAGE_SIZE_MAX = 1000


def clamp_page_size(page_size: int, default: int = 25, *, max_size: int = PAGE_SIZE_MAX) -> int:
    """Clamp page_size into [1, max_size]; invalid/missing falls back to default then clamp."""
    try:
        n = int(page_size)
    except (TypeError, ValueError):
        n = default
    if n < 1:
        n = default
    return min(max_size, max(1, n))


def now_utc():
    return datetime.now(timezone.utc)


def now_iso():
    return now_utc().isoformat()


def new_id():
    return str(uuid.uuid4())


# ---------- Password ----------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ---------- JWT ----------
def create_access_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email,
               "exp": now_utc() + timedelta(hours=12), "type": "access"}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {"sub": user_id, "exp": now_utc() + timedelta(days=7), "type": "refresh"}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def set_auth_cookies(response, access_token, refresh_token):
    # secure=False for local HTTP; set COOKIE_SECURE=true in production HTTPS
    secure = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
    samesite = "none" if secure else "lax"
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=secure,
        samesite=samesite,
        max_age=43200,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=secure,
        samesite=samesite,
        max_age=604800,
        path="/",
    )


# ---------- Phone normalization (E.164; India when no +) ----------
def normalize_phone(raw: str, default_cc: str = "91") -> str:
    if not raw:
        return ""
    s = str(raw).strip()
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not digits:
        return ""
    if plus:
        return "+" + digits
    if len(digits) == 10:
        return "+" + default_cc + digits
    if digits.startswith(default_cc):
        return "+" + digits
    if digits.startswith("0"):
        return "+" + default_cc + digits.lstrip("0")
    return "+" + digits


def _strip_phone_prefix(raw: str) -> str:
    """Normalize spreadsheet/Meta wrappers; does not change valid E.164 upload format."""
    s = str(raw or "").strip()
    # Zero-width / BOM left by editors or CSV text markers
    s = s.lstrip("\ufeff\u200b\u200e\u200f")
    s = s.strip()
    # Excel/Numbers sometimes keep a leading apostrophe for text cells
    if s.startswith("'") and len(s) > 1:
        s = s[1:].strip()
    # Excel formula-style text: ="..." or ="+971..."
    if len(s) >= 3 and s[0] == "=" and s[1] == '"' and s.endswith('"'):
        s = s[2:-1].strip()
    elif s.startswith("=") and len(s) > 1 and s[1] in "+0123456789pP":
        s = s[1:].strip()
    s = re.sub(r"^[pP]:\s*", "", s)
    return s.strip()


def invalid_phone_reason(raw: str) -> str:
    """Why parse_phone rejected this value. Always starts with 'Invalid phone number.'"""
    import phonenumbers
    from phonenumbers import NumberParseException

    original = _strip_phone_prefix(raw)
    if not original:
        return "Invalid phone number. Phone is empty."
    try:
        num = phonenumbers.parse(original, None if original.startswith("+") else "IN")
    except NumberParseException:
        return "Invalid phone number. Could not parse this value as a phone number."
    if phonenumbers.is_valid_number(num):
        return "Invalid phone number."
    cc = str(num.country_code or "")
    region = phonenumbers.region_code_for_number(num) or ""
    digits = re.sub(r"\D", "", original)
    national = digits[len(cc):] if cc and digits.startswith(cc) else digits
    labels = {
        "GB": "UK",
        "IN": "India",
        "PK": "Pakistan",
        "UA": "Ukraine",
        "CN": "China",
        "RU": "Russia",
        "KZ": "Kazakhstan",
        "US": "US",
    }
    label = labels.get(region) or (f"+{cc}" if cc else "this country")
    if cc and national.startswith("0"):
        if cc == "44":
            return (
                "Invalid phone number. UK (+44) numbers must drop the leading 0 after the country code "
                "(use +447426717733, not +440742671773)."
            )
        return (
            f"Invalid phone number. {label} (+{cc}) numbers must drop the extra 0 after +{cc}. "
            "The national trunk 0 is not part of E.164."
        )
    if cc == "44" or region == "GB":
        return (
            "Invalid phone number. Not a valid UK (+44) number. "
            "Use +44 plus 10 national digits with no 0 after +44."
        )
    if cc == "91" or region == "IN":
        return (
            "Invalid phone number. Not a valid India (+91) number. "
            "Indian mobiles are +91 plus 10 digits starting with 6-9."
        )
    if cc:
        where = f"{label} (+{cc})" if region else f"+{cc}"
        return (
            f"Invalid phone number. Not a valid {where} number. "
            "Check the country code, length, and digits."
        )
    return (
        "Invalid phone number. Not a valid E.164 number. "
        "Check the country code, length, and digits."
    )


def parse_phone(raw: str) -> tuple[str, str]:
    """Return (E.164, ISO 3166-1 alpha-2). Numbers without + are parsed as India."""
    import phonenumbers
    from phonenumbers import NumberParseException, PhoneNumberFormat

    original = _strip_phone_prefix(raw)
    if not original:
        raise ValueError(invalid_phone_reason(raw))
    try:
        if original.startswith("+"):
            num = phonenumbers.parse(original, None)
        else:
            num = phonenumbers.parse(original, "IN")
    except NumberParseException:
        raise ValueError(invalid_phone_reason(raw))
    if not phonenumbers.is_valid_number(num):
        raise ValueError(invalid_phone_reason(raw))
    e164 = phonenumbers.format_number(num, PhoneNumberFormat.E164)
    region = phonenumbers.region_code_for_number(num) or "IN"
    return e164, region


def normalize_and_validate_phone(raw: str, default_cc: str = "91") -> str:
    """Normalize then validate E.164; raises ValueError with user-facing message."""
    return parse_phone(raw)[0]


def country_filter_code(country: Optional[str]) -> str:
    """ISO2 filter value, or empty when the caller wants every country."""
    code = (country or "").strip().upper()
    if not code or code == "ALL":
        return ""
    if not re.fullmatch(r"[A-Z]{2}", code):
        raise ValueError("Invalid country")
    return code


def apply_country_filter(q: dict, country: Optional[str], field: str = "phone_country") -> dict:
    code = country_filter_code(country)
    if code:
        q[field] = code
    return q


EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def validate_email_optional(email: str) -> str:
    """Return trimmed email; empty is OK; non-empty must be valid."""
    e = (email or "").strip()
    if e and not EMAIL_RE.match(e):
        raise ValueError("Invalid email address")
    return e


def escape_regex(text: str) -> str:
    """Escape user search text for safe MongoDB $regex (literal match)."""
    return re.escape(text or "")


# ---------- Auth principal ----------
async def _decode_token(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_principal(request: Request) -> dict:
    """Server-derived principal enriched with live role permissions + data scope."""
    payload = await _decode_token(request)
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0})
    if not user or not user.get("active", True):
        raise HTTPException(status_code=401, detail="User not found or inactive")
    role = await db.roles.find_one({"id": user.get("role_id")}, {"_id": 0})
    if role:
        user["permissions"] = role.get("permissions", [])
        user["menus"] = role.get("menus", [])
        user["data_scope"] = role.get("data_scope", "OWN")
        user["role_name"] = role.get("name")
    else:
        user["permissions"], user["menus"], user["data_scope"] = [], [], "OWN"
    user.pop("password_hash", None)
    # IP allowlist: empty active list = open; otherwise client IP must match
    from ip_access import enforce_ip_access
    await enforce_ip_access(request)
    return user


def require(*permissions: str):
    """Deny-by-default permission dependency. Passes if user has ANY of the given perms."""
    async def dep(request: Request):
        principal = await get_principal(request)
        perms = set(principal.get("permissions", []))
        if not any(p in perms for p in permissions):
            raise HTTPException(status_code=403, detail="Permission denied")
        return principal
    return dep


async def team_member_ids(principal: dict) -> list:
    """Ids visible under TEAM scope: self + teams where principal is supervisor/member."""
    ids = {principal["id"]}
    teams = await db.teams.find(
        {"companyId": COMPANY_ID,
         "$or": [{"supervisor_id": principal["id"]}, {"member_ids": principal["id"]}]},
        {"_id": 0}).to_list(1000)
    for t in teams:
        ids.add(t.get("supervisor_id"))
        for m in t.get("member_ids", []):
            ids.add(m)
    ids.discard(None)
    return list(ids)


async def scope_filter(principal: dict, field: str = "assigned_to") -> dict:
    """Return a Mongo filter fragment enforcing the principal's data scope."""
    scope = principal.get("data_scope", "OWN")
    if scope == "ALL":
        return {}
    if scope == "TEAM":
        return {field: {"$in": await team_member_ids(principal)}}
    return {field: principal["id"]}


async def lead_scope_filter(principal: dict) -> dict:
    """Leads visible to principal: TEAM = team-assigned OR unassigned uploads by self."""
    scope = principal.get("data_scope", "OWN")
    if scope == "ALL":
        return {}
    if scope == "TEAM":
        return {
            "$or": [
                {"assigned_to": {"$in": await team_member_ids(principal)}},
                {"assigned_to": None, "created_by": principal["id"]},
            ]
        }
    return {"assigned_to": principal["id"]}


def and_filter(q: dict, clause: dict) -> dict:
    """Append a clause under $and without clobbering an existing $or/$and."""
    if not clause:
        return q
    q.setdefault("$and", []).append(clause)
    return q


async def merge_assignment_scope(
    q: dict,
    principal: dict,
    *,
    assigned_to: Optional[str] = None,
    assignment_status: Optional[str] = None,
    skip_assignment_status: bool = False,
) -> dict:
    """Apply assignment filters without replacing TEAM/OWN scope with a company-wide pool."""
    if skip_assignment_status and not assigned_to:
        return q
    scope = principal.get("data_scope", "OWN")
    if scope == "OWN":
        return q
    if scope == "ALL":
        if assigned_to:
            q["assigned_to"] = assigned_to
        elif assignment_status == "unassigned":
            q["assigned_to"] = None
        elif assignment_status == "assigned":
            q["assigned_to"] = {"$ne": None}
        return q
    # TEAM
    team_ids = await team_member_ids(principal)
    if assigned_to:
        if assigned_to not in team_ids:
            raise HTTPException(status_code=403, detail="Agent not in your team")
        and_filter(q, {"assigned_to": assigned_to})
        return q
    if assignment_status == "unassigned":
        and_filter(q, {"assigned_to": None, "created_by": principal["id"]})
        return q
    if assignment_status == "assigned":
        and_filter(q, {"assigned_to": {"$in": team_ids}})
        return q
    return q


async def assert_assigned_to_in_scope(principal: dict, user_id: Optional[str]) -> None:
    """Ensure assign target is visible under principal scope."""
    if not user_id:
        raise HTTPException(status_code=400, detail="Agent is required")
    scope = principal.get("data_scope", "OWN")
    if scope == "ALL":
        return
    if scope == "OWN":
        if user_id != principal["id"]:
            raise HTTPException(status_code=403, detail="Agent not in scope")
        return
    if user_id not in await team_member_ids(principal):
        raise HTTPException(status_code=403, detail="Agent not in your team")


def _lead_visible_to(principal: dict, lead: dict, team_ids: Optional[list]) -> bool:
    scope = principal.get("data_scope", "OWN")
    if scope == "ALL":
        return True
    assigned = lead.get("assigned_to")
    if scope == "OWN":
        return assigned == principal["id"]
    if assigned and team_ids is not None and assigned in team_ids:
        return True
    if assigned is None and lead.get("created_by") == principal["id"]:
        return True
    return False


async def assert_lead_in_scope(principal: dict, lead: Optional[dict]) -> dict:
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    scope = principal.get("data_scope", "OWN")
    if scope == "ALL":
        return lead
    team_ids = await team_member_ids(principal) if scope == "TEAM" else None
    if not _lead_visible_to(principal, lead, team_ids):
        raise HTTPException(status_code=403, detail="Lead not in scope")
    return lead


async def assert_client_in_scope(principal: dict, client: Optional[dict]) -> dict:
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if principal.get("user_type") == "affiliate":
        if client.get("affiliate_id") != principal["id"]:
            raise HTTPException(status_code=403, detail="Client not in scope")
        return client
    scope = principal.get("data_scope", "OWN")
    if scope == "ALL":
        return client
    owner = client.get("owner_id")
    if scope == "OWN":
        if owner != principal["id"]:
            raise HTTPException(status_code=403, detail="Client not in scope")
        return client
    if owner not in await team_member_ids(principal):
        raise HTTPException(status_code=403, detail="Client not in scope")
    return client


async def assert_call_in_scope(principal: dict, call: Optional[dict]) -> dict:
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    scope = principal.get("data_scope", "OWN")
    if scope == "ALL":
        return call
    agent_id = call.get("agent_id")
    if scope == "OWN":
        if agent_id and agent_id != principal["id"]:
            raise HTTPException(status_code=403, detail="Call not in scope")
        return call
    if agent_id and agent_id not in await team_member_ids(principal):
        raise HTTPException(status_code=403, detail="Call not in scope")
    return call


async def client_scope_filter(principal: dict) -> dict:
    """Role-aware client scope: affiliates own via affiliate_id, others via owner_id."""
    if principal.get("user_type") == "affiliate":
        return {"affiliate_id": principal["id"]}
    return await scope_filter(principal, "owner_id")


async def sheet_scope_filter(principal: dict) -> dict:
    """Sheet sources visible to principal: ALL unrestricted; else owner or legacy creator."""
    if principal.get("data_scope") == "ALL":
        return {}
    pid = principal["id"]
    return {
        "$or": [
            {"owner_id": pid},
            {"owner_id": None, "created_by": pid},
            {"owner_id": {"$exists": False}, "created_by": pid},
        ]
    }


def sheet_visible_to(principal: dict, sheet: dict) -> bool:
    if principal.get("data_scope") == "ALL":
        return True
    pid = principal["id"]
    owner = sheet.get("owner_id")
    if owner == pid:
        return True
    if not owner and sheet.get("created_by") == pid:
        return True
    return False


async def assert_sheet_in_scope(principal: dict, sheet: Optional[dict]) -> dict:
    if not sheet:
        raise HTTPException(status_code=404, detail="Sheet source not found")
    if not sheet_visible_to(principal, sheet):
        raise HTTPException(status_code=403, detail="Sheet source not in scope")
    return sheet


async def resolve_sheet_lead_attribution(source: dict) -> tuple:
    """Return (created_by, created_by_name) for leads from a sheet sync.

    Prefers sheet owner_id; falls back to sheet created_by.
    """
    uid = source.get("owner_id") or source.get("created_by")
    if not uid:
        return None, None
    name = source.get("owner_name") if source.get("owner_id") else source.get("created_by_name")
    if not name:
        user = await db.users.find_one({"id": uid}, {"_id": 0, "name": 1})
        name = (user or {}).get("name")
    return uid, name


def live_client_filter() -> dict:
    """Exclude soft-deleted clients (missing deleted_at counts as live)."""
    return {"deleted_at": None}


def live_ledger_filter() -> dict:
    """Exclude soft-deleted ledger entries (missing deleted_at counts as live)."""
    return {"deleted_at": None}


def reportable_calls_filter() -> dict:
    """Exclude calls voided when a conversion was undone."""
    return {"excluded_from_reports": {"$ne": True}}


# ---------- Audit ----------
async def audit(actor: dict, action: str, entity: str, entity_id: str = None, meta: dict = None):
    await db.audit_logs.insert_one({
        "id": new_id(),
        "companyId": COMPANY_ID,
        "actor_id": actor.get("id") if actor else None,
        "actor_name": actor.get("name") if actor else "system",
        "actor_email": actor.get("email") if actor else None,
        "action": action,
        "entity": entity,
        "entity_id": entity_id,
        "meta": meta or {},
        "created_at": now_iso(),
    })


def dedupe_menus_by_key(menus: list) -> list:
    """Keep first menu row per key (catalog sorted by order before calling)."""
    seen = set()
    out = []
    for menu in menus:
        key = menu.get("key")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(menu)
    return out


def dedupe_roles_by_name(roles: list) -> list:
    """Keep first role row per name (list should be stably ordered before calling)."""
    seen = set()
    out = []
    for role in roles:
        name = role.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(role)
    return out
