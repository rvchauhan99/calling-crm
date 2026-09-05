import os
import asyncio
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from core import client, db, COMPANY_ID
import routes_auth, routes_admin, routes_leads, routes_clients, routes_reports
import routes_sheet_sources
from seed import seed
from sheet_sync import sync_source

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Calling CRM API")

app.include_router(routes_auth.router)
app.include_router(routes_admin.router)
app.include_router(routes_leads.router)
app.include_router(routes_clients.router)
app.include_router(routes_reports.router)
app.include_router(routes_sheet_sources.router)

_sheet_poll_task = None


@app.get("/api/health")
async def health():
    return {"status": "ok"}


app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_URL", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _parse_iso(ts):
    if not ts:
        return None
    try:
        if isinstance(ts, datetime):
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


async def _sheet_poll_loop():
    """Every 30s, sync enabled sources whose poll_seconds elapsed."""
    while True:
        try:
            await asyncio.sleep(30)
            if os.environ.get("SHEET_SYNC_DISABLED", "").lower() in ("1", "true", "yes"):
                continue
            now = datetime.now(timezone.utc)
            sources = await db.sheet_sources.find(
                {"companyId": COMPANY_ID, "enabled": True},
                {"_id": 0},
            ).to_list(200)
            for source in sources:
                if source.get("syncing"):
                    lock_until = _parse_iso(source.get("sync_lock_until"))
                    if lock_until and lock_until > now:
                        continue
                poll = max(60, int(source.get("poll_seconds") or 120))
                last = _parse_iso(source.get("last_synced_at"))
                if last and (now - last).total_seconds() < poll:
                    continue
                try:
                    await sync_source(source, acquire_lock=True)
                except Exception:
                    logger.exception("Background sync failed for %s", source.get("id"))
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Sheet poll loop error")


@app.on_event("startup")
async def startup():
    global _sheet_poll_task
    try:
        await seed()
        logger.info("Seed complete")
    except Exception as e:
        logger.exception("Seed failed: %s", e)
    if os.environ.get("SHEET_SYNC_DISABLED", "").lower() not in ("1", "true", "yes"):
        _sheet_poll_task = asyncio.create_task(_sheet_poll_loop())
        logger.info("Sheet sync poll loop started")
    else:
        logger.info("Sheet sync poll loop disabled (SHEET_SYNC_DISABLED)")


@app.on_event("shutdown")
async def shutdown():
    global _sheet_poll_task
    if _sheet_poll_task:
        _sheet_poll_task.cancel()
        try:
            await _sheet_poll_task
        except asyncio.CancelledError:
            pass
        _sheet_poll_task = None
    client.close()
