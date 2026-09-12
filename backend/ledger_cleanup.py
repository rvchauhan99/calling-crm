"""One-shot / idempotent cleanup of retired ledger reversal entries."""
import logging

from core import COMPANY_ID, db, live_ledger_filter, now_iso

logger = logging.getLogger(__name__)

CLEANUP_REASON = "cleanup:remove_ledger_reversals"


async def _rewrite_client_balances(client_id: str) -> float:
    """Replay live entries in created_at order; fix balance_after + clients.balance."""
    entries = await db.ledger.find(
        {"client_id": client_id, "companyId": COMPANY_ID, **live_ledger_filter()},
        {"_id": 0, "id": 1, "type": 1, "amount": 1},
    ).sort("created_at", 1).to_list(10000)
    bal = 0.0
    for e in entries:
        bal = round(bal + (e["amount"] if e["type"] == "credit" else -e["amount"]), 2)
        await db.ledger.update_one(
            {"id": e["id"], "companyId": COMPANY_ID},
            {"$set": {"balance_after": bal}},
        )
    await db.clients.update_one(
        {"id": client_id, "companyId": COMPANY_ID},
        {"$set": {"balance": bal}},
    )
    return bal


async def ensure_cleanup_ledger_reversals() -> dict:
    """Soft-delete all live category=reversal rows and recompute affected balances.

    Idempotent: if no live reversals remain, this is a no-op.
    """
    q = {
        "companyId": COMPANY_ID,
        "category": "reversal",
        **live_ledger_filter(),
    }
    reversals = await db.ledger.find(q, {"_id": 0, "id": 1, "client_id": 1}).to_list(100000)
    if not reversals:
        logger.info("Ledger reversal cleanup: nothing to do")
        return {"deleted": 0, "clients_updated": 0}

    client_ids = sorted({r["client_id"] for r in reversals if r.get("client_id")})
    now = now_iso()
    soft = {
        "deleted_at": now,
        "deleted_by": "system",
        "deleted_reason": CLEANUP_REASON,
    }
    res = await db.ledger.update_many(
        {"id": {"$in": [r["id"] for r in reversals]}, "companyId": COMPANY_ID},
        {"$set": soft},
    )
    for cid in client_ids:
        await _rewrite_client_balances(cid)

    out = {
        "deleted": res.modified_count,
        "clients_updated": len(client_ids),
    }
    logger.info(
        "Ledger reversal cleanup: soft-deleted %s entries across %s clients",
        out["deleted"], out["clients_updated"],
    )
    return out
