"""One-shot India tag for rows saved before international phone countries."""
from core import COMPANY_ID, db, now_iso

FLAG_ID = "phone_country_india_v1"


async def ensure_phone_country_india() -> dict:
    """Set missing phone_country / lead_phone_country to IN. Does not overwrite a stored country."""
    existing = await db.system_flags.find_one({"companyId": COMPANY_ID, "id": FLAG_ID}, {"_id": 1})
    if existing:
        return {"skipped": True, "flag": FLAG_ID}

    leads = await db.leads.update_many(
        {"companyId": COMPANY_ID, "phone_country": {"$exists": False}},
        {"$set": {"phone_country": "IN"}},
    )
    clients = await db.clients.update_many(
        {"companyId": COMPANY_ID, "phone_country": {"$exists": False}},
        {"$set": {"phone_country": "IN"}},
    )
    calls = await db.calls.update_many(
        {"companyId": COMPANY_ID, "lead_phone_country": {"$exists": False}},
        {"$set": {"lead_phone_country": "IN"}},
    )
    await db.system_flags.update_one(
        {"companyId": COMPANY_ID, "id": FLAG_ID},
        {"$set": {
            "companyId": COMPANY_ID,
            "id": FLAG_ID,
            "done_at": now_iso(),
            "leads": leads.modified_count,
            "clients": clients.modified_count,
            "calls": calls.modified_count,
        }},
        upsert=True,
    )
    return {
        "skipped": False,
        "flag": FLAG_ID,
        "leads": leads.modified_count,
        "clients": clients.modified_count,
        "calls": calls.modified_count,
    }
