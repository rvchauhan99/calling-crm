# LiveKit + SIP (Agentive-style self-host)

Mirrors Agentive's public stack: LiveKit server + SIP bridge on one host.

## Prerequisites

- Ubuntu 22.04+ VPS in Mumbai (or nearby)
- Domain DNS: `lk.YOURDOMAIN` and `sip.YOURDOMAIN` → VPS public IP
- Open firewall: TCP 80, 443, 7880, 7881; UDP 50000-60000; TCP/UDP 5060

## Quick start

```bash
cd deploy/livekit
cp .env.example .env
# edit LIVEKIT_API_KEY / LIVEKIT_API_SECRET / DOMAIN / PUBLIC_IP
docker compose up -d
curl -s https://lk.YOURDOMAIN/   # expect OK when TLS terminates in front
```

For local smoke without TLS:

```bash
docker compose -f docker-compose.yml up -d
curl -s http://127.0.0.1:7880/   # OK
```

## Wire Plivo

1. Plivo inbound trunk origination URI → your LiveKit SIP host (`sip.YOURDOMAIN:5060`)
2. Create LiveKit SIP inbound trunk + dispatch rule (see `sip-bootstrap.md`)
3. Plivo outbound trunk credentials → LiveKit SIP outbound trunk
4. Put keys into Calling CRM `backend/.env` (`TELEPHONY_PROVIDER=plivo_livekit`)

## Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | livekit, livekit-sip, redis |
| `livekit.yaml` | LiveKit server config template |
| `sip-config.yaml` | LiveKit SIP service config |
| `.env.example` | Secrets template |
| `sip-bootstrap.md` | CLI steps for trunks / dispatch |

## Notes

- Agentive runs LiveKit on DigitalOcean; same pattern works on any VPS.
- Redis is required by LiveKit SIP for session state.
- Prefer Caddy/nginx TLS reverse-proxy in front of 7880 for `wss://`.
