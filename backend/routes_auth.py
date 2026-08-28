"""Auth routes: login, logout, me, refresh, forgot/reset password, my menus."""
import os
import secrets
from datetime import timedelta
from fastapi import APIRouter, Request, Response, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from core import (db, COMPANY_ID, verify_password, hash_password, create_access_token,
                  create_refresh_token, set_auth_cookies, get_principal, now_utc,
                  now_iso, new_id, audit)
import jwt
from core import JWT_SECRET, JWT_ALGORITHM

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_FAILED = 5
LOCKOUT_MIN = 15


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str
    password: str


def public_user(u: dict) -> dict:
    u = dict(u)
    u.pop("password_hash", None)
    u.pop("_id", None)
    return u


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response):
    email = body.email.lower()
    ident = email
    rec = await db.login_attempts.find_one({"identifier": ident})
    if rec and rec.get("count", 0) >= MAX_FAILED:
        locked_until = rec.get("locked_until")
        if locked_until and now_utc().isoformat() < locked_until:
            raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
        # window expired -> reset counter
        await db.login_attempts.delete_one({"identifier": ident})

    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user["password_hash"]):
        await db.login_attempts.update_one(
            {"identifier": ident},
            {"$inc": {"count": 1},
             "$set": {"locked_until": (now_utc() + timedelta(minutes=LOCKOUT_MIN)).isoformat()}},
            upsert=True)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="Account is disabled")

    await db.login_attempts.delete_one({"identifier": ident})
    at = create_access_token(user["id"], user["email"])
    rt = create_refresh_token(user["id"])
    set_auth_cookies(response, at, rt)
    await audit(user, "login", "auth", user["id"])
    return {"user": public_user(user), "access_token": at}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"ok": True}


@router.get("/me")
async def me(principal: dict = Depends(get_principal)):
    return {"user": principal}


@router.post("/refresh")
async def refresh(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await db.users.find_one({"id": payload["sub"]})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    at = create_access_token(user["id"], user["email"])
    response.set_cookie("access_token", at, httponly=True, secure=True,
                        samesite="none", max_age=43200, path="/")
    return {"access_token": at}


@router.post("/forgot-password")
async def forgot_password(body: ForgotIn):
    user = await db.users.find_one({"email": body.email.lower()})
    if user:
        token = secrets.token_urlsafe(32)
        await db.password_reset_tokens.insert_one({
            "id": new_id(), "token": token, "user_id": user["id"],
            "expires_at": (now_utc() + timedelta(hours=1)).isoformat(),
            "used": False, "created_at": now_iso()})
        print(f"[PASSWORD RESET] {os.environ.get('FRONTEND_URL')}/reset-password?token={token}")
    return {"ok": True, "message": "If the email exists, a reset link was generated."}


@router.post("/reset-password")
async def reset_password(body: ResetIn):
    rec = await db.password_reset_tokens.find_one({"token": body.token})
    if not rec or rec.get("used") or rec["expires_at"] < now_iso():
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    await db.users.update_one({"id": rec["user_id"]},
                              {"$set": {"password_hash": hash_password(body.password)}})
    await db.password_reset_tokens.update_one({"token": body.token}, {"$set": {"used": True}})
    return {"ok": True}


@router.get("/menus")
async def my_menus(principal: dict = Depends(get_principal)):
    """Menu catalog filtered to menus the principal's role grants."""
    allowed = set(principal.get("menus", []))
    catalog = await db.menus.find({"companyId": COMPANY_ID}, {"_id": 0}).sort("order", 1).to_list(100)
    return {"menus": [m for m in catalog if m["key"] in allowed],
            "permissions": principal.get("permissions", []),
            "data_scope": principal.get("data_scope")}
