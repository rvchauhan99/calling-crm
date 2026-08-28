# Stack note for coding agents

## What shipped from `calling-crm-main.zip`

Working MVP:

- `frontend/` — CRA + CRACO + Tailwind + shadcn-style UI
- `backend/` — FastAPI + Motor/MongoDB + JWT RBAC

This is the **current runnable codebase**.

## What the blueprint docs describe

`docs/01`–`03` and `docs/02-system-architecture.md` describe the **target** production design (Next.js App Router, PostgreSQL/Prisma, Redis, telephony adapter).

## Rule

1. Extend this MVP for near-term CRM features (parity with Baazexcall menus already largely present).
2. When migrating to the target stack, treat this tree as the behavioral reference — do not invent conflicting RBAC/disposition/ledger semantics.
3. Keep `docs/` as the product contract; keep this note so agents do not “rewrite from scratch” without reason.
