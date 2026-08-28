#!/usr/bin/env bash
# Create deploy/.env from .env.example if missing (does not overwrite).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  echo "deploy/.env already exists — not overwriting."
  exit 0
fi

if [[ ! -f .env.example ]]; then
  echo "Missing deploy/.env.example" >&2
  exit 1
fi

cp .env.example .env
echo "Created deploy/.env"
echo "Edit it now: MONGO_URL, JWT_SECRET, ADMIN_*, DEMO_PASSWORD, FRONTEND_URL (Vercel origin)"
echo "Then: docker compose --env-file .env up -d --build"
