"""Core: config, db, auth utils, RBAC dependencies, helpers."""
import os
import re
import jwt
import bcrypt
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import Request, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
COMPANY_ID = os.environ.get("COMPANY_ID", "default")
JWT_ALGORITHM = "HS256"

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]


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


# ---------- Phone normalization (E.164 / +91 default) ----------
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


async def client_scope_filter(principal: dict) -> dict:
    """Role-aware client scope: affiliates own via affiliate_id, others via owner_id."""
    if principal.get("user_type") == "affiliate":
        return {"affiliate_id": principal["id"]}
    return await scope_filter(principal, "owner_id")


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
