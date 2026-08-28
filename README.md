# Calling CRM

Production-oriented telecalling CRM (Baazexcall-style parity + RBAC).

## Repository layout

```text
docs/                 Product blueprint (source of truth for roadmap)
  01-product-requirements.md
  02-system-architecture.md
  03-module-specs-and-build-guide.md
  baazexcall-menu-lock.md
frontend/             React (CRA + CRACO) agent/admin SPA
backend/              FastAPI + MongoDB API
```

**Current runtime stack:** React SPA + FastAPI + MongoDB (working MVP from `calling-crm-main.zip`).

**Target architecture** (migration path): see `docs/02-system-architecture.md` (Next.js + PostgreSQL + Prisma + telephony adapter). Do not mix stacks in one app until an intentional migration.

## Prerequisites

- Node.js 20+
- Python 3.11+
- MongoDB 6+ running locally (or Atlas URI)

## Quick start

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # edit secrets
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

Health check: http://localhost:8000/api/health

On startup the API seeds menus, roles, dispositions, and (if missing) an admin from `ADMIN_EMAIL` / `ADMIN_PASSWORD`.

### 2. Frontend

```bash
cd frontend
cp .env.example .env
yarn install                # or: npm install
yarn start                  # http://localhost:3000
```

`REACT_APP_BACKEND_URL` must point at the API (default `http://localhost:8000`).

## Default local admin

Set in `backend/.env`:

```text
ADMIN_EMAIL=admin@callingcrm.com
ADMIN_PASSWORD=ChangeMe_Admin_123!
```

Demo users (created by seed with password from env `DEMO_PASSWORD`, default `Passw0rd!`):

| Role       | Email                         |
|------------|-------------------------------|
| Supervisor | supervisor@callingcrm.com     |
| Agent      | rohan@callingcrm.com          |
| Affiliate  | affiliate@callingcrm.com      |

Change these passwords before any shared/staging deploy.

## Features in this codebase

- JWT auth, login lockout, refresh
- Menu + permission RBAC with OWN / TEAM / ALL data scope
- Leads (import, assign, auto-assign), Today Calls, dispositions (carry_forward / non_carry_forward)
- Pipeline, follow-ups, call history
- Clients, notes, append-only ledger (FTD / deposits / withdrawals)
- Users, teams, roles & menus, audit log
- Dashboard + caller / affiliate / company reports + CSV export

Not yet in this MVP (see docs for roadmap): softphone, Live Floor barge, IVR/DID, WhatsApp/SMS, predictive dialer, AI/QA.

## Tests

```bash
cd backend
source .venv/bin/activate
export REACT_APP_BACKEND_URL=http://localhost:8000
pytest -q
```

Requires API + Mongo running and seeded users.

## Documentation

| Doc | Purpose |
|-----|---------|
| [docs/01-product-requirements.md](docs/01-product-requirements.md) | Full product PRD and menus |
| [docs/02-system-architecture.md](docs/02-system-architecture.md) | Target production architecture |
| [docs/03-module-specs-and-build-guide.md](docs/03-module-specs-and-build-guide.md) | Screen specs, phases, DoD |
| [docs/baazexcall-menu-lock.md](docs/baazexcall-menu-lock.md) | Live Baazexcall reverse-engineer annex |

## Security notes

- Never commit `.env` files
- Do not ship hardcoded credentials in the UI
- Prefer httpOnly cookie auth for production; current SPA also uses Bearer token in memory/localStorage — harden before public deploy
