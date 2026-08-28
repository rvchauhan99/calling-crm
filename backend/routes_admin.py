"""Admin routes: users, roles, menus, teams."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from core import (db, COMPANY_ID, require, hash_password, new_id, now_iso, audit)

router = APIRouter(prefix="/api", tags=["admin"])


# ---------------- Users ----------------
class UserIn(BaseModel):
    name: str
    email: EmailStr
    password: Optional[str] = None
    role_id: str
    user_type: str = "caller"
    team_id: Optional[str] = None
    daily_quota: int = 0
    active: bool = True


async def _role_name(role_id):
    r = await db.roles.find_one({"id": role_id}, {"_id": 0, "name": 1})
    return r["name"] if r else None


@router.get("/users")
async def list_users(user_type: Optional[str] = None, principal: dict = Depends(require("users:view"))):
    q = {"companyId": COMPANY_ID}
    if user_type:
        q["user_type"] = user_type
    users = await db.users.find(q, {"_id": 0, "password_hash": 0}).sort("created_at", -1).to_list(1000)
    roles = {r["id"]: r["name"] for r in await db.roles.find({"companyId": COMPANY_ID}, {"_id": 0}).to_list(100)}
    for u in users:
        u["role_name"] = roles.get(u.get("role_id"))
    return {"users": users}


@router.post("/users")
async def create_user(body: UserIn, principal: dict = Depends(require("users:create"))):
    if await db.users.find_one({"email": body.email.lower()}):
        raise HTTPException(status_code=400, detail="Email already exists")
    if not body.password:
        raise HTTPException(status_code=400, detail="Password is required")
    uid = new_id()
    doc = {"id": uid, "companyId": COMPANY_ID, "name": body.name, "email": body.email.lower(),
           "password_hash": hash_password(body.password), "role_id": body.role_id,
           "user_type": body.user_type, "team_id": body.team_id,
           "daily_quota": body.daily_quota, "active": body.active,
           "acw_pending_lead_id": None, "created_at": now_iso()}
    await db.users.insert_one(dict(doc))
    await audit(principal, "create", "user", uid, {"email": body.email})
    doc.pop("password_hash", None)
    return {"user": doc}


@router.put("/users/{uid}")
async def update_user(uid: str, body: UserIn, principal: dict = Depends(require("users:edit"))):
    upd = {"name": body.name, "email": body.email.lower(), "role_id": body.role_id,
           "user_type": body.user_type, "team_id": body.team_id,
           "daily_quota": body.daily_quota, "active": body.active}
    if body.password:
        upd["password_hash"] = hash_password(body.password)
    res = await db.users.update_one({"id": uid, "companyId": COMPANY_ID}, {"$set": upd})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    await audit(principal, "update", "user", uid)
    return {"ok": True}


@router.delete("/users/{uid}")
async def delete_user(uid: str, principal: dict = Depends(require("users:delete"))):
    if uid == principal["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    await db.users.update_one({"id": uid}, {"$set": {"active": False}})
    await audit(principal, "deactivate", "user", uid)
    return {"ok": True}


# ---------------- Roles ----------------
class RoleIn(BaseModel):
    name: str
    description: str = ""
    permissions: List[str] = []
    menus: List[str] = []
    data_scope: str = "OWN"


@router.get("/roles")
async def list_roles(principal: dict = Depends(require("roles_menus:view", "users:view"))):
    roles = await db.roles.find({"companyId": COMPANY_ID}, {"_id": 0}).to_list(100)
    for r in roles:
        r["user_count"] = await db.users.count_documents({"role_id": r["id"], "active": True})
    return {"roles": roles}


@router.post("/roles")
async def create_role(body: RoleIn, principal: dict = Depends(require("roles_menus:create"))):
    rid = new_id()
    doc = {"id": rid, "companyId": COMPANY_ID, "name": body.name, "description": body.description,
           "permissions": body.permissions, "menus": body.menus, "data_scope": body.data_scope,
           "is_system": False, "created_at": now_iso()}
    await db.roles.insert_one(dict(doc))
    await audit(principal, "create", "role", rid, {"name": body.name})
    return {"role": doc}


@router.put("/roles/{rid}")
async def update_role(rid: str, body: RoleIn, principal: dict = Depends(require("roles_menus:edit"))):
    role = await db.roles.find_one({"id": rid, "companyId": COMPANY_ID})
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    upd = {"description": body.description, "permissions": body.permissions,
           "menus": body.menus, "data_scope": body.data_scope}
    if not role.get("is_system"):
        upd["name"] = body.name
    await db.roles.update_one({"id": rid}, {"$set": upd})
    await audit(principal, "update", "role", rid, {"permissions": len(body.permissions)})
    return {"ok": True}


@router.delete("/roles/{rid}")
async def delete_role(rid: str, principal: dict = Depends(require("roles_menus:delete"))):
    role = await db.roles.find_one({"id": rid, "companyId": COMPANY_ID})
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.get("is_system"):
        raise HTTPException(status_code=400, detail="System roles cannot be deleted")
    if await db.users.count_documents({"role_id": rid, "active": True}) > 0:
        raise HTTPException(status_code=400, detail="Role is assigned to active users")
    await db.roles.delete_one({"id": rid})
    await audit(principal, "delete", "role", rid)
    return {"ok": True}


@router.get("/menus/catalog")
async def menu_catalog(principal: dict = Depends(require("roles_menus:view"))):
    menus = await db.menus.find({"companyId": COMPANY_ID}, {"_id": 0}).sort("order", 1).to_list(100)
    return {"menus": menus}


# ---------------- Teams ----------------
class TeamIn(BaseModel):
    name: str
    supervisor_id: Optional[str] = None
    member_ids: List[str] = []


@router.get("/teams")
async def list_teams(principal: dict = Depends(require("teams:view"))):
    teams = await db.teams.find({"companyId": COMPANY_ID}, {"_id": 0}).to_list(100)
    umap = {u["id"]: u["name"] for u in await db.users.find({"companyId": COMPANY_ID}, {"_id": 0}).to_list(1000)}
    for t in teams:
        t["supervisor_name"] = umap.get(t.get("supervisor_id"))
        t["member_names"] = [umap.get(m) for m in t.get("member_ids", [])]
    return {"teams": teams}


@router.post("/teams")
async def create_team(body: TeamIn, principal: dict = Depends(require("teams:create"))):
    tid = new_id()
    doc = {"id": tid, "companyId": COMPANY_ID, "name": body.name,
           "supervisor_id": body.supervisor_id, "member_ids": body.member_ids, "created_at": now_iso()}
    await db.teams.insert_one(dict(doc))
    for m in body.member_ids:
        await db.users.update_one({"id": m}, {"$set": {"team_id": tid}})
    await audit(principal, "create", "team", tid, {"name": body.name})
    return {"team": doc}


@router.put("/teams/{tid}")
async def update_team(tid: str, body: TeamIn, principal: dict = Depends(require("teams:edit"))):
    res = await db.teams.update_one({"id": tid, "companyId": COMPANY_ID}, {"$set": {
        "name": body.name, "supervisor_id": body.supervisor_id, "member_ids": body.member_ids}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Team not found")
    for m in body.member_ids:
        await db.users.update_one({"id": m}, {"$set": {"team_id": tid}})
    await audit(principal, "update", "team", tid)
    return {"ok": True}


@router.delete("/teams/{tid}")
async def delete_team(tid: str, principal: dict = Depends(require("teams:delete"))):
    await db.teams.delete_one({"id": tid, "companyId": COMPANY_ID})
    await db.users.update_many({"team_id": tid}, {"$set": {"team_id": None}})
    await audit(principal, "delete", "team", tid)
    return {"ok": True}
