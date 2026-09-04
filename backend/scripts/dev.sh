#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]] || [[ ! -f .env ]]; then
  bash scripts/setup.sh
fi

echo "Starting API at http://127.0.0.1:8000 (reload enabled)"
exec .venv/bin/uvicorn server:app --reload --host 0.0.0.0 --port 8000
