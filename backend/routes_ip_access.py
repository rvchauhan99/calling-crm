"""IP Access master: CRUD + my-ip helper."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import audit, db, get_principal, require
from ip_access import (
    build_entry,
    find_by_cidr,
    find_by_id,
    list_ip_access,
    normalize_cidr,
    resolve_client_ip,
)

router = APIRouter(prefix="/api/ip-access", tags=["ip-access"])


class IpAccessIn(BaseModel):
    cidr: str = Field(..., min_length=1)
    label: str = ""
    active: bool = True


@router.get("/my-ip")
async def my_ip(request: Request, principal: dict = Depends(require("ip_access:view"))):
    ip = resolve_client_ip(request)
    return {"ip": ip, "user_id": principal.get("id")}


@router.get("")
async def get_ip_access(principal: dict = Depends(require("ip_access:view"))):
    docs = await list_ip_access()
    return {"ip_access": docs, "allow_all": not any(d.get("active") for d in docs)}


@router.post("")
async def create_ip_access(body: IpAccessIn, principal: dict = Depends(require("ip_access:create"))):
    try:
        cidr = normalize_cidr(body.cidr)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if await find_by_cidr(cidr):
        raise HTTPException(status_code=400, detail="This IP/CIDR already exists")
    doc = build_entry(cidr=cidr, label=body.label, active=body.active)
    await db.ip_access_list.insert_one(dict(doc))
    await audit(principal, "create", "ip_access", doc["id"], {"cidr": cidr, "label": doc["label"]})
    return {"ip_access": doc}


@router.put("/{entry_id}")
async def update_ip_access(
    entry_id: str,
    body: IpAccessIn,
    principal: dict = Depends(require("ip_access:edit")),
):
    current = await find_by_id(entry_id)
    if not current:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        cidr = normalize_cidr(body.cidr)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    dup = await db.ip_access_list.find_one(
        {"companyId": current["companyId"], "cidr": cidr, "id": {"$ne": entry_id}},
        {"_id": 1},
    )
    if dup:
        raise HTTPException(status_code=400, detail="This IP/CIDR already exists")
    from core import COMPANY_ID, now_iso

    fields = {
        "cidr": cidr,
        "label": (body.label or "").strip() or cidr,
        "active": bool(body.active),
        "updated_at": now_iso(),
    }
    res = await db.ip_access_list.update_one(
        {"id": entry_id, "companyId": COMPANY_ID},
        {"$set": fields},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    await audit(principal, "update", "ip_access", entry_id, {"cidr": cidr})
    return {"ok": True}


@router.delete("/{entry_id}")
async def delete_ip_access(entry_id: str, principal: dict = Depends(require("ip_access:delete"))):
    from core import COMPANY_ID

    current = await find_by_id(entry_id)
    if not current:
        raise HTTPException(status_code=404, detail="Not found")
    await db.ip_access_list.delete_one({"id": entry_id, "companyId": COMPANY_ID})
    await audit(principal, "delete", "ip_access", entry_id, {"cidr": current.get("cidr")})
    return {"ok": True}
