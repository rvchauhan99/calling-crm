#!/bin/sh
# App Platform sets PORT=8080. Local default remains 8000.
set -eu
PORT="${PORT:-8000}"
exec uvicorn server:app --host 0.0.0.0 --port "$PORT" --workers 1
