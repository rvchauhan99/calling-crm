#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]] || [[ ! -f .env ]]; then
  bash scripts/setup.sh
fi

exec .venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000 --workers 2
