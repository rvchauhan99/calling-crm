# Calling CRM — Vultr API deploy (phase 1: folder + env)

**Backend only** on Vultr (Docker Compose + MongoDB Atlas).  
**Frontend** is hosted by you on **Vercel** (not in this compose stack).

```text
Browser (Vercel UI) ──HTTPS──► api (uvicorn :8000 on Vultr) ──► Atlas
```

## 1. Fill secrets (before go-live)

```bash
cd deploy
chmod +x scripts/setup-env.sh
./scripts/setup-env.sh
# edit .env — replace every REPLACE_ME_*
```

### Required values

| Variable | What to put |
|----------|-------------|
| `MONGO_URL` | Atlas `mongodb+srv://...` URI |
| `DB_NAME` | e.g. `calling_crm` |
| `JWT_SECRET` | `openssl rand -hex 32` |
| `ADMIN_EMAIL` | Valid email (not `@localhost`) |
| `ADMIN_PASSWORD` | Strong Super Admin password |
| `DEMO_PASSWORD` | Seeded demo users password |
| `FRONTEND_URL` | **Vercel origin** for CORS, e.g. `https://your-app.vercel.app` |
| `COOKIE_SECURE` | `true` if API is HTTPS; `false` for plain `http://IP:8000` tests |
| `API_PUBLISH` | Default `8000:8000` (no TLS). With TLS: `127.0.0.1:8000:8000` |
| `DOMAIN` | API hostname if using Caddy TLS, e.g. `api.yourdomain.com` |

### Atlas checklist

1. Create cluster + DB user.
2. Network Access: allow your **Vultr VPS public IP**.
3. Paste SRV URI into `MONGO_URL` (URL-encode password special chars).

**Do not commit `deploy/.env`.**

---

## 2. Vercel frontend (your side)

In the Vercel project env (Production):

```bash
REACT_APP_BACKEND_URL=https://api.yourdomain.com
# or temporarily: http://YOUR_VPS_IP:8000
```

Must match the public API base (no `/api` suffix — the app appends `/api`).

Set Vultr `FRONTEND_URL` to the exact Vercel origin (scheme + host, no path), or CORS will block the browser.

---

## 3. Local smoke (optional)

```bash
cd deploy
docker compose --env-file .env up -d --build
curl -sS http://127.0.0.1:8000/api/health
```

Stop: `docker compose --env-file .env down`

---

## 4. Vultr go-live (phase 2 — after env is ready)

On Ubuntu 22.04/24.04 Cloud Compute:

1. Firewall: TCP **8000** (or **80/443** if using TLS profile).
2. Install Docker Engine + Compose plugin.
3. Clone/rsync repo; ensure `deploy/.env` is filled.
4. From `deploy/`:

```bash
docker compose --env-file .env up -d --build
curl -sS http://SERVER_IP:8000/api/health
```

### Optional HTTPS on the API host (Caddy)

1. DNS `A` for `DOMAIN` → VPS IP.
2. In `.env`: `DOMAIN=api.example.com`, `COOKIE_SECURE=true`, `API_PUBLISH=127.0.0.1:8000:8000`.
3. Run:

```bash
docker compose --env-file .env --profile tls up -d --build
curl -sS https://api.example.com/api/health
```

4. Point Vercel `REACT_APP_BACKEND_URL` at `https://api.example.com`.

---

## Files

| File | Role |
|------|------|
| `Dockerfile.api` | Python 3.11 + uvicorn |
| `docker-compose.yml` | `api` (+ optional `caddy` TLS) |
| `Caddyfile` | TLS → `api:8000` |
| `.env.example` | Template → `.env` |
| `scripts/setup-env.sh` | Creates `.env` once |

---

## After first boot

API `seed()` creates menus, roles, admin from `ADMIN_*`, and demo users via `DEMO_PASSWORD`.

When `deploy/.env` is filled, say so — phase 2 is SSH + `docker compose up` on the VPS.
