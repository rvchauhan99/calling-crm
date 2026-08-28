import os
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent / ".env")

import logging
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from core import client
import routes_auth, routes_admin, routes_leads, routes_clients, routes_reports
from seed import seed

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Calling CRM API")

app.include_router(routes_auth.router)
app.include_router(routes_admin.router)
app.include_router(routes_leads.router)
app.include_router(routes_clients.router)
app.include_router(routes_reports.router)


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


@app.on_event("startup")
async def startup():
    try:
        await seed()
        logger.info("Seed complete")
    except Exception as e:
        logger.exception("Seed failed: %s", e)


@app.on_event("shutdown")
async def shutdown():
    client.close()
