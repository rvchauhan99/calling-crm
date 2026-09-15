"""IP access allowlist master: CIDR validate/normalize, enforce, ensure menu/RBAC."""
from __future__ import annotations

import ipaddress
import os
from typing import List, Optional

from fastapi import HTTPException, Request

from core import COMPANY_ID, db, new_id, now_iso

IP_ACCESS_MENU = (
    "ip_access",
    "IP Access",
    "Shield",
    "/ip-access",
    "Config",
    10,
    ["view", "create", "edit", "delete"],
)

# Private / loopback peers that may set X-Forwarded-For / X-Real-IP
_DEFAULT_TRUSTED_PROXY_CIDRS = (
    "127.0.0.1/32",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
)

_DENY_DETAIL = "Access denied from this network. Contact your administrator."

# Deploy-time defaults (seeded when IP_ACCESS_SEED_DEFAULTS=1). $setOnInsert only.
DEFAULT_IP_ACCESS_ENTRIES = (
    {"label": "Network 1 IPv4", "cidr": "86.98.8.178"},
    {"label": "Network 1 IPv6", "cidr": "2001:4860:7:142c::ff"},
    {"label": "Network 2 IPv4", "cidr": "103.228.146.230"},
    {"label": "Network 2 IPv6", "cidr": "2001:4860:7:805::d2"},
    {"label": "Network 3 IPv4", "cidr": "86.98.48.213"},
    {"label": "Network 3 IPv6", "cidr": "2001:4860:7:1732::ff"},
)


def ip_access_disabled() -> bool:
    return os.environ.get("IP_ACCESS_DISABLED", "").strip().lower() in ("1", "true", "yes")


def ip_access_seed_defaults_enabled() -> bool:
    return os.environ.get("IP_ACCESS_SEED_DEFAULTS", "").strip().lower() in ("1", "true", "yes")


def normalize_cidr(raw: str) -> str:
    """Accept a single IP or CIDR; return canonical network string (with prefix)."""
    s = (raw or "").strip()
    if not s:
        raise ValueError("IP or CIDR is required")
    try:
        network = ipaddress.ip_network(s, strict=False)
    except ValueError as e:
        raise ValueError("Invalid IP or CIDR") from e
    return str(network)


def _parse_trusted_proxy_cidrs() -> list:
    raw = os.environ.get("TRUSTED_PROXY_CIDRS", "").strip()
    parts = [p.strip() for p in raw.split(",")] if raw else list(_DEFAULT_TRUSTED_PROXY_CIDRS)
    nets = []
    for p in parts:
        if not p:
            continue
        try:
            nets.append(ipaddress.ip_network(p, strict=False))
        except ValueError:
            continue
    return nets or [ipaddress.ip_network(c, strict=False) for c in _DEFAULT_TRUSTED_PROXY_CIDRS]


def _peer_is_trusted(peer: str) -> bool:
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for net in _parse_trusted_proxy_cidrs():
        if addr in net:
            return True
    return False


def resolve_client_ip(request: Request) -> str:
    """Best-effort client IP. Trust forwarded headers only from trusted proxy peers."""
    peer = ""
    if request.client and request.client.host:
        peer = request.client.host
    if peer and _peer_is_trusted(peer):
        xff = (request.headers.get("x-forwarded-for") or "").strip()
        if xff:
            return xff.split(",")[0].strip()
        xri = (request.headers.get("x-real-ip") or "").strip()
        if xri:
            return xri
    return peer


async def ensure_ip_access_indexes():
    await db.ip_access_list.create_index([("companyId", 1), ("cidr", 1)], unique=True)
    await db.ip_access_list.create_index([("companyId", 1), ("id", 1)], unique=True)
    await db.ip_access_list.create_index([("companyId", 1), ("active", 1)])


async def ensure_ip_access():
    """Idempotent menu + Super Admin RBAC. Does not seed allowlist rows (empty = open)."""
    await ensure_ip_access_indexes()

    key, label, icon, path, group, order, actions = IP_ACCESS_MENU
    await db.menus.update_one(
        {"companyId": COMPANY_ID, "key": key},
        {"$set": {
            "key": key, "label": label, "icon": icon, "path": path,
            "group": group, "order": order, "actions": actions,
            "companyId": COMPANY_ID,
        }},
        upsert=True,
    )

    # Keep later Config/Finance orders consistent when ip_access sits at 10
    await db.menus.update_one(
        {"companyId": COMPANY_ID, "key": "clients"},
        {"$set": {"order": 11}},
    )
    await db.menus.update_one(
        {"companyId": COMPANY_ID, "key": "ledger"},
        {"$set": {"order": 12}},
    )
    await db.menus.update_one(
        {"companyId": COMPANY_ID, "key": "reports"},
        {"$set": {"order": 13}},
    )
    await db.menus.update_one(
        {"companyId": COMPANY_ID, "key": "users"},
        {"$set": {"order": 14}},
    )
    await db.menus.update_one(
        {"companyId": COMPANY_ID, "key": "teams"},
        {"$set": {"order": 15}},
    )
    await db.menus.update_one(
        {"companyId": COMPANY_ID, "key": "roles_menus"},
        {"$set": {"order": 16}},
    )
    await db.menus.update_one(
        {"companyId": COMPANY_ID, "key": "telephony_numbers"},
        {"$set": {"order": 17}},
    )
    await db.menus.update_one(
        {"companyId": COMPANY_ID, "key": "audit"},
        {"$set": {"order": 18}},
    )

    full_perms = [f"{key}:{a}" for a in actions]
    await db.roles.update_one(
        {"companyId": COMPANY_ID, "name": "Super Admin"},
        {
            "$addToSet": {
                "permissions": {"$each": full_perms},
                "menus": key,
            },
        },
    )


async def ensure_ip_access_defaults() -> dict:
    """Idempotent upsert of office/home allowlist rows when IP_ACCESS_SEED_DEFAULTS is on.

    Uses $setOnInsert so admin edits to label/active are never overwritten.
    Local/dev leaves the flag off so an empty list stays allow-all.
    """
    if not ip_access_seed_defaults_enabled():
        return {"seeded": False, "inserted": 0, "skipped": 0}

    await ensure_ip_access_indexes()
    inserted = 0
    skipped = 0
    for entry in DEFAULT_IP_ACCESS_ENTRIES:
        cidr = normalize_cidr(entry["cidr"])
        label = (entry.get("label") or "").strip() or cidr
        res = await db.ip_access_list.update_one(
            {"companyId": COMPANY_ID, "cidr": cidr},
            {
                "$setOnInsert": {
                    "id": new_id(),
                    "companyId": COMPANY_ID,
                    "cidr": cidr,
                    "label": label,
                    "active": True,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                },
            },
            upsert=True,
        )
        if res.upserted_id is not None:
            inserted += 1
        else:
            skipped += 1
    return {"seeded": True, "inserted": inserted, "skipped": skipped}


async def list_ip_access(*, active_only: bool = False) -> List[dict]:
    q: dict = {"companyId": COMPANY_ID}
    if active_only:
        q["active"] = True
    return await db.ip_access_list.find(q, {"_id": 0}).sort([("label", 1), ("cidr", 1)]).to_list(500)


async def list_active_cidrs() -> List[str]:
    docs = await list_ip_access(active_only=True)
    return [d["cidr"] for d in docs if d.get("cidr")]


async def is_ip_allowed(ip: str) -> bool:
    """True if no active rows, or ip matches any active CIDR. Kill-switch always True."""
    if ip_access_disabled():
        return True
    cidrs = await list_active_cidrs()
    if not cidrs:
        return True
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return False
    for c in cidrs:
        try:
            if addr in ipaddress.ip_network(c, strict=False):
                return True
        except ValueError:
            continue
    return False


async def enforce_ip_access(request: Request) -> None:
    """Raise 403 when allowlist is active and client IP is not permitted."""
    if ip_access_disabled():
        return
    cidrs = await list_active_cidrs()
    if not cidrs:
        return
    client_ip = resolve_client_ip(request)
    if await is_ip_allowed(client_ip):
        return
    raise HTTPException(status_code=403, detail=_DENY_DETAIL)


async def find_by_cidr(cidr: str) -> Optional[dict]:
    return await db.ip_access_list.find_one(
        {"companyId": COMPANY_ID, "cidr": cidr},
        {"_id": 0},
    )


async def find_by_id(entry_id: str) -> Optional[dict]:
    return await db.ip_access_list.find_one(
        {"companyId": COMPANY_ID, "id": entry_id},
        {"_id": 0},
    )


def build_entry(*, cidr: str, label: str, active: bool = True) -> dict:
    return {
        "id": new_id(),
        "companyId": COMPANY_ID,
        "cidr": cidr,
        "label": (label or "").strip() or cidr,
        "active": bool(active),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
