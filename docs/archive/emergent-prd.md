# Calling CRM — PRD

## Original Problem
Production-grade telecalling CRM (Baazexcall "better clone"). CRM + Finance Ledger + Analytics only. NO voice/telephony/AI. Single-tenant. React + FastAPI + MongoDB. Granular menu/permission RBAC with data scope (OWN/TEAM/ALL), leads + client management, manual call-disposition logging, append-only finance ledger, computed reporting/dashboards.

## Stack & Decisions
- React (JS/JSX) + Tailwind + shadcn/ui + Recharts; sky-blue & white theme (NO green).
- FastAPI + Motor(MongoDB). String-UUID docs (`id`), `companyId` on all business docs (multi-tenant seam).
- Auth: custom JWT (bcrypt, 12h access). Token in httpOnly cookie AND response body; frontend uses Bearer header (ingress forces CORS `*`, so no cookie-credentials).
- Ledger: append-only + idempotency key + derived balance + reversing entries (no Mongo replica-set transactions available). FTD tracked once on first credit post-conversion.
- RBAC: deny-by-default `require(permission)` dependency on every business route. Live role lookup per request. Data scope enforced server-side via scope_filter.

## Personas / Roles (seeded, editable)
- Super Admin (ALL), Supervisor (TEAM), Agent/Caller (OWN), Affiliate (OWN) + custom roles.

## Backend files
- core.py (config, auth, rbac, scope, audit), seed.py (menus/roles/demo), routes_auth.py, routes_admin.py (users/roles/menus/teams), routes_leads.py (leads/dispositions/calls/today/history/pipeline/followups), routes_clients.py (clients/ledger), routes_reports.py (dashboard/reports/audit/export), server.py.

## Implemented (2026-06)
- Auth & RBAC + Roles & Menus admin UI (editable perms + data scope, no redeploy).
- Leads: list/create/edit/delete, CSV import (dedup + E.164/+91 normalize), manual assign, quota auto-assign, Lead 360 sheet.
- Dispositions/Responses: CRUD, carry_forward/non_carry_forward, ACW flag.
- Today Calls: agent workspace, log disposition + follow-up + stage, ACW gating (blocks new lead while pending).
- Call History (scoped, export CSV), Pipeline kanban (drag-drop), Follow-ups.
- Clients: convert from lead, notes, finance ledger (post/reverse/idempotency/FTD, export).
- Users (callers/affiliates/admins tabs), Teams.
- Reports: caller/affiliate/company + CSV export. Dashboard KPIs + charts (IST).
- Audit log (login, create/update/delete, ledger, assign, convert, export).
- Rich demo seed: 120 leads, 4 dispositions set, 3 agents+supervisor+affiliate, calls, 8 clients, ledger.

## Backlog / Next
- P1: Lead merge, custom-fields UI builder, precomputed daily rollups (cron).
- P2: S3 object storage for imports/exports, richer dashboard widgets, saved report views.

## Test credentials
See /app/memory/test_credentials.md
