# Third-party registration checklist — Cloud Telephony

Use with [cloud-telephony-build-plan.md](./cloud-telephony-build-plan.md). Solo proprietor path (Udyam + Plivo India).

## 1. Udyam (required before DID)

| Field | Your value |
|-------|------------|
| Portal | https://udyamregistration.gov.in/ |
| Entity | Sole proprietorship |
| Aadhaar (proprietor) | |
| PAN | |
| GSTIN | (skip if not registered) |
| Certificate PDF saved | [ ] |

**Done when:** Udyam Registration Certificate PDF downloaded.

## 2. Plivo India account

| Field | Your value |
|-------|------------|
| Signup | https://console.plivo.com/ |
| Data region | **India** (immutable) |
| Business type | Direct Brand |
| KYC doc | Udyam PDF (+ seal/sign if required) |
| Auth ID | (store in env only) |
| Auth Token | (store in env only) |
| Wallet top-up | ₹________ (suggest 2,000–5,000) |
| DID E.164 | +91__________ |

**Done when:** Compliance = Approved and one India voice number rented.

### Plivo SIP trunks (after LiveKit is up)

| Trunk | Setting | Value |
|-------|---------|-------|
| Inbound | Origination URI | `sip:<did>@sip.YOURDOMAIN:5060` (or LiveKit SIP URI from docs) |
| Inbound | Auth | IP ACL of LiveKit host **or** digest |
| Outbound | Termination | Plivo outbound trunk domain |
| Outbound | From / CLI | Your DID |
| Recording | Enabled | Yes |
| Webhook | CRM | `https://API_HOST/api/telephony/webhooks/plivo` |

## 3. Backup docs (if Plivo rejects Udyam alone)

- [ ] Shop & Establishment / trade licence  
- [ ] Proprietor photo + address proof  
- [ ] Bank statement / utility in business name (if asked)

## 4. Sign-off

| Step | Date | Initials |
|------|------|----------|
| Udyam complete | | |
| Plivo KYC approved | | |
| DID live | | |
| Test inbound OK | | |
| Test outbound OK | | |

## 5. Unlock CRM softphone UI

Until this checklist is done and keys are in `backend/.env`, **Call / softphone / DID edit stay inactive** in the UI (`TELEPHONY_PROVIDER=mock` → `ui_enabled: false`).

Enable after keys:

```bash
TELEPHONY_PROVIDER=plivo_livekit
LIVEKIT_URL=wss://lk.yourdomain.com
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
# optional local mock UI QA only:
# TELEPHONY_UI_FORCE=1
```

Manual **Log Call** remains available at all times.
