#!/usr/bin/env bash
# Build and restart Calling CRM API (+ Caddy TLS) on Vultr.
# Used by GitHub Actions and manual deploys. Never overwrites deploy/.env.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/calling-crm}"
DEPLOY_DIR="${APP_DIR}/deploy"
HEALTH_URL="${VULTR_HEALTH_URL:-https://139-84-223-174.sslip.io/api/health}"

if [[ ! -f "${DEPLOY_DIR}/.env" ]]; then
  echo "Missing ${DEPLOY_DIR}/.env — copy from .env.example and fill secrets first." >&2
  exit 1
fi

cd "${DEPLOY_DIR}"
docker compose --env-file .env --profile tls up -d --build

echo "Waiting for API health..."
for i in $(seq 1 30); do
  if curl -fsS "${HEALTH_URL}" >/dev/null 2>&1; then
    echo "Deploy OK: ${HEALTH_URL}"
    exit 0
  fi
  sleep 2
done

echo "Health check failed: ${HEALTH_URL}" >&2
docker compose --env-file .env --profile tls ps
docker logs calling-crm-api-1 --tail 30 || true
exit 1
