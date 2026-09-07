#!/bin/sh
# DigitalOcean App Platform sets PORT=8080. Local default is 8000.
set -eu
export PORT="${PORT:-8000}"
exec python server.py
