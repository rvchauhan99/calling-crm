import os
import asyncio
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from core import client, db, COMPANY_ID, parse_frontend_origins
import routes_auth, routes_admin, routes_leads, routes_clients, routes_reports
import routes_sheet_sources
import routes_telephony
import routes_ip_access
from seed import seed
from sheet_sync import (
    pick_next_due_source,
    run_sync_with_company_lock,
)
from lead_import_jobs import start_lead_import_worker, stop_lead_import_worker
from bind_port import listen_port

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

_sheet_poll_task = None
_lead_import_worker_task = None


def _run_seed_enabled() -> bool:
    return os.environ.get("RUN_SEED", "").strip().lower() in ("1", "true", "yes")


async def _sheet_poll_loop():
    """Every 30s, sync at most one due source (company-wide single-flight)."""
    while True:
        try:
            await asyncio.sleep(30)
            if os.environ.get("SHEET_SYNC_DISABLED", "").lower() in ("1", "true", "yes"):
                continue
            source = await pick_next_due_source()
            if not source:
                continue
            holder = f"poller-{os.getpid()}"
            try:
                result = await run_sync_with_company_lock(source, holder=holder)
                if result.get("status") == "busy":
                    logger.info("Sheet sync skipped (company lock busy)")
                elif result.get("status") == "error":
                    logger.warning(
                        "Background sync error for %s: %s",
                        source.get("id"),
                        result.get("error"),
                    )
            except Exception:
                logger.exception("Background sync failed for %s", source.get("id"))
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Sheet poll loop error")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _sheet_poll_task, _lead_import_worker_task
    try:
        from seed import ensure_indexes
        await ensure_indexes()
        logger.info("Mongo indexes ensured")
    except Exception as e:
        logger.exception("ensure_indexes failed: %s", e)
    try:
        from lead_sources import ensure_lead_sources
        await ensure_lead_sources()
        logger.info("Lead sources master ensured")
    except Exception as e:
        logger.exception("ensure_lead_sources failed: %s", e)
    try:
        from ip_access import ensure_ip_access
        await ensure_ip_access()
        logger.info("IP access master ensured")
    except Exception as e:
        logger.exception("ensure_ip_access failed: %s", e)
    try:
        from ip_access import ensure_ip_access_defaults
        result = await ensure_ip_access_defaults()
        logger.info("IP access defaults seed: %s", result)
    except Exception as e:
        logger.exception("ensure_ip_access_defaults failed: %s", e)
    try:
        from seed import ensure_telephony_menus
        await ensure_telephony_menus()
        logger.info("Telephony menus ensured")
    except Exception as e:
        logger.exception("ensure_telephony_menus failed: %s", e)
    try:
        from seed import ensure_ledger_menu_without_reverse
        await ensure_ledger_menu_without_reverse()
        logger.info("Ledger menu reverse permission stripped")
    except Exception as e:
        logger.exception("ensure_ledger_menu_without_reverse failed: %s", e)
    try:
        from ledger_cleanup import ensure_cleanup_ledger_reversals
        result = await ensure_cleanup_ledger_reversals()
        logger.info("Ledger reversal cleanup done: %s", result)
    except Exception as e:
        logger.exception("ensure_cleanup_ledger_reversals failed: %s", e)
    try:
        from unconvert_reports_cleanup import ensure_exclude_undone_convert_calls
        result = await ensure_exclude_undone_convert_calls()
        logger.info("Undone-convert reports cleanup done: %s", result)
    except Exception as e:
        logger.exception("ensure_exclude_undone_convert_calls failed: %s", e)
    try:
        from disposition_pipeline import ensure_disposition_pipeline_links
        result = await ensure_disposition_pipeline_links()
        logger.info("Disposition pipeline links ensured: %s", result)
    except Exception as e:
        logger.exception("ensure_disposition_pipeline_links failed: %s", e)
    try:
        from disposition_pipeline import ensure_lead_pipeline_from_disposition
        result = await ensure_lead_pipeline_from_disposition()
        logger.info("Lead pipeline backfill ensured: %s", result)
    except Exception as e:
        logger.exception("ensure_lead_pipeline_from_disposition failed: %s", e)
    if _run_seed_enabled():
        try:
            await seed()
            logger.info("Seed complete")
        except Exception as e:
            logger.exception("Seed failed: %s", e)
    else:
        logger.info("Seed skipped (live database)")
    _lead_import_worker_task = start_lead_import_worker()
    logger.info("Lead import worker started")
    if os.environ.get("SHEET_SYNC_DISABLED", "").lower() not in ("1", "true", "yes"):
        _sheet_poll_task = asyncio.create_task(_sheet_poll_loop())
        logger.info("Sheet sync poll loop started")
    else:
        logger.info("Sheet sync poll loop disabled (SHEET_SYNC_DISABLED)")
    yield
    await stop_lead_import_worker()
    _lead_import_worker_task = None
    if _sheet_poll_task:
        _sheet_poll_task.cancel()
        try:
            await _sheet_poll_task
        except asyncio.CancelledError:
            pass
        _sheet_poll_task = None
    client.close()


app = FastAPI(title="Calling CRM API", lifespan=lifespan)

app.include_router(routes_auth.router)
app.include_router(routes_admin.router)
app.include_router(routes_leads.router)
app.include_router(routes_clients.router)
app.include_router(routes_reports.router)
app.include_router(routes_sheet_sources.router)
app.include_router(routes_telephony.router)
app.include_router(routes_ip_access.router)


def _health_ok():
    return {"status": "ok"}


@app.get("/")
async def root_health():
    return _health_ok()


@app.get("/health")
async def probe_health():
    return _health_ok()


@app.get("/api/health")
async def health():
    return _health_ok()


app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_frontend_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


if __name__ == "__main__":
    import uvicorn
    port = listen_port()
    logger.info("Listening on 0.0.0.0:%s", port)
    uvicorn.run("server:app", host="0.0.0.0", port=port, workers=1)
