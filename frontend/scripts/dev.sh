#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d node_modules ]] || [[ ! -f .env ]]; then
  bash scripts/setup.sh
fi

echo "Starting frontend at http://localhost:3003"
export PORT=3003
exec npm run start
