"""Lead sources master: defaults, ensure-on-boot, and DB helpers."""
from typing import List, Optional

from core import db, COMPANY_ID, new_id, now_iso
from lead_constants import DEFAULT_LEAD_SOURCES, SYSTEM_LEAD_SOURCES, NON_CREATABLE_LEAD_SOURCES

LEAD_SOURCES_MENU = (
    "lead_sources",
    "Lead Sources",
    "ShareNetwork",
    "/lead-sources",
    "Config",
    8,
    ["view", "create", "edit", "delete"],
)


async def ensure_lead_source_indexes():
    await db.lead_sources.create_index([("companyId", 1), ("name", 1)], unique=True)
    await db.lead_sources.create_index([("companyId", 1), ("id", 1)], unique=True)


async def ensure_lead_sources():
    """Idempotent upsert of default CRM lead sources + menu/RBAC for Super Admin / Supervisor.

    Safe to run on every API boot (independent of RUN_SEED). Does not overwrite
    admin edits to active/order/name — only inserts missing defaults.
    """
    await ensure_lead_source_indexes()

    for order, name in enumerate(DEFAULT_LEAD_SOURCES, start=1):
        creatable = name not in NON_CREATABLE_LEAD_SOURCES
        is_system = name in SYSTEM_LEAD_SOURCES
        await db.lead_sources.update_one(
            {"companyId": COMPANY_ID, "name": name},
            {
                "$setOnInsert": {
                    "id": new_id(),
                    "companyId": COMPANY_ID,
                    "name": name,
                    "order": order,
                    "active": True,
                    "creatable": creatable,
                    "is_system": is_system,
                    "created_at": now_iso(),
                },
            },
            upsert=True,
        )

    key, label, icon, path, group, order, actions = LEAD_SOURCES_MENU
    await db.menus.update_one(
        {"companyId": COMPANY_ID, "key": key},
        {"$set": {
            "key": key, "label": label, "icon": icon, "path": path,
            "group": group, "order": order, "actions": actions,
            "companyId": COMPANY_ID,
        }},
        upsert=True,
    )

    # Shift sheet_sources and later catalog orders when lead_sources sits at 8
    # (seed MENU_CATALOG already encodes this; this keeps live DBs consistent).
    await db.menus.update_one(
        {"companyId": COMPANY_ID, "key": "sheet_sources"},
        {"$set": {"order": 9}},
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
    await db.roles.update_one(
        {"companyId": COMPANY_ID, "name": "Supervisor"},
        {
            "$addToSet": {
                "permissions": f"{key}:view",
                "menus": key,
            },
        },
    )


async def list_lead_sources(*, active_only: bool = False) -> List[dict]:
    q = {"companyId": COMPANY_ID}
    if active_only:
        q["active"] = True
    return await db.lead_sources.find(q, {"_id": 0}).sort("order", 1).to_list(200)


async def source_names(*, active_only: bool = True, creatable_only: bool = False) -> List[str]:
    q = {"companyId": COMPANY_ID}
    if active_only:
        q["active"] = True
    if creatable_only:
        q["creatable"] = True
    docs = await db.lead_sources.find(q, {"_id": 0, "name": 1}).sort("order", 1).to_list(200)
    return [d["name"] for d in docs if d.get("name")]


async def is_allowed_source(name: str, *, allow_non_creatable: bool = False) -> bool:
    s = (name or "").strip()
    if not s:
        return False
    q = {"companyId": COMPANY_ID, "name": s, "active": True}
    if not allow_non_creatable:
        q["creatable"] = True
    doc = await db.lead_sources.find_one(q, {"_id": 1})
    return doc is not None


async def find_source_by_name(name: str) -> Optional[dict]:
    return await db.lead_sources.find_one(
        {"companyId": COMPANY_ID, "name": (name or "").strip()},
        {"_id": 0},
    )
