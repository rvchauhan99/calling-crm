"""CSV import updates source on duplicate only when existing source is Import."""
import asyncio
import os
import time
import uuid
from pathlib import Path

import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from conftest import BASE_URL, client_for


def _uid_phone(prefix="91"):
    return prefix + str(uuid.uuid4().int)[:8]


def _wait_job(admin, job_id, timeout=30):
    body = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = admin.get(f"{BASE_URL}/api/leads/import-jobs/{job_id}", timeout=30)
        assert status.status_code == 200, status.text
        body = status.json()
        if body["status"] in ("completed", "failed"):
            break
        time.sleep(0.2)
    assert body is not None
    return body


def _post_import_job(admin, csv_data):
    r = requests.post(
        f"{BASE_URL}/api/leads/import-jobs",
        files={"file": ("leads.csv", csv_data, "text/csv")},
        headers={"Authorization": admin.headers["Authorization"]},
        timeout=30,
    )
    assert r.status_code == 202, r.text
    return r.json()["jobId"]


class TestImportUpdateImportSource:
    created = []
    jobs = []

    def test_duplicate_updates_source_when_existing_is_import(self, admin):
        phone = _uid_phone("95")
        # Import is non-creatable via POST /leads — seed via import job first.
        first_csv = (
            "name,phone,email,city,source\n"
            f"TEST_ImpSrc_Import,{phone},impsrc@example.com,Mumbai,Import\n"
        )
        job1 = _post_import_job(admin, first_csv)
        self.jobs.append(job1)
        body1 = _wait_job(admin, job1)
        assert body1["status"] == "completed", body1
        assert body1["progress"]["created"] == 1, body1

        found = admin.get(f"{BASE_URL}/api/leads?search={phone}", timeout=30).json()
        assert found["total"] >= 1, found
        lead = found["leads"][0]
        lead_id = lead["id"]
        self.created.append(lead_id)
        assert lead["source"] == "Import"
        e164 = lead["phone"]

        csv_data = (
            "name,phone,email,city,source\n"
            f"TEST_ImpSrc_Website,{e164},impsrc2@example.com,Dubai,Website\n"
        )
        job_id = _post_import_job(admin, csv_data)
        self.jobs.append(job_id)
        body = _wait_job(admin, job_id)
        assert body["status"] == "completed", body
        assert body["progress"]["created"] == 0, body
        assert body["progress"]["duplicates"] == 1, body
        assert body["progress"].get("updated") == 1, body

        got = admin.get(f"{BASE_URL}/api/leads/{lead_id}", timeout=30)
        assert got.status_code == 200, got.text
        assert got.json()["lead"]["source"] == "Website"

        err = admin.get(f"{BASE_URL}/api/leads/import-jobs/{job_id}/errors.csv", timeout=30)
        assert err.status_code == 200, err.text
        assert "Duplicate phone; source updated" in err.text

    def test_duplicate_does_not_update_when_existing_source_not_import(self, admin):
        phone = _uid_phone("94")
        create = admin.post(
            f"{BASE_URL}/api/leads",
            json={
                "name": "TEST_ImpSrc_Website",
                "phone": phone,
                "email": "impsrc3@example.com",
                "city": "Mumbai",
                "source": "Website",
            },
            timeout=30,
        )
        assert create.status_code == 200, create.text
        lead = create.json()["lead"]
        lead_id = lead["id"]
        self.created.append(lead_id)

        e164 = lead["phone"]
        csv_data = (
            "name,phone,email,city,source\n"
            f"TEST_ImpSrc_Cold,{e164},impsrc4@example.com,Dubai,Cold List\n"
        )
        job_id = _post_import_job(admin, csv_data)
        self.jobs.append(job_id)
        body = _wait_job(admin, job_id)
        assert body["status"] == "completed", body
        assert body["progress"]["created"] == 0, body
        assert body["progress"]["duplicates"] == 1, body
        assert body["progress"].get("updated", 0) == 0, body

        got = admin.get(f"{BASE_URL}/api/leads/{lead_id}", timeout=30)
        assert got.status_code == 200, got.text
        assert got.json()["lead"]["source"] == "Website"

    def test_import_jobs_anon_denied(self, anon):
        r = requests.post(
            f"{BASE_URL}/api/leads/import-jobs",
            files={"file": ("leads.csv", "name,phone\nA,9876543210\n", "text/csv")},
            timeout=30,
        )
        assert r.status_code in (401, 403)

    @classmethod
    def teardown_class(cls):
        c = client_for("admin")
        for lid in cls.created:
            c.delete(f"{BASE_URL}/api/leads/{lid}", timeout=30)
        if cls.jobs:
            env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
            mongo = os.environ.get("MONGO_URL") or env.get("MONGO_URL")
            dbname = os.environ.get("DB_NAME") or env.get("DB_NAME")

            async def wipe():
                client = AsyncIOMotorClient(mongo)
                await client[dbname].lead_import_jobs.delete_many({"id": {"$in": cls.jobs}})
                client.close()

            asyncio.run(wipe())
