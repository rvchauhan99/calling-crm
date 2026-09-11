# Bootstrap LiveKit SIP trunks for Plivo

After `docker compose up` and TLS/`lk` DNS work, create trunks with [LiveKit CLI](https://docs.livekit.io/home/cli/).

```bash
export LIVEKIT_URL=https://lk.YOURDOMAIN
export LIVEKIT_API_KEY=APIdevkey
export LIVEKIT_API_SECRET=your_secret

# Inbound: Plivo → LiveKit
lk sip inbound create \
  --name plivo-inbound \
  --numbers "+91XXXXXXXXXX" \
  --allowed-addresses "plivo-sip-ip-ranges-or-digest"

# Dispatch inbound DID into a call room prefix CRM understands
lk sip dispatch create \
  --name crm-inbound \
  --trunks <inbound-trunk-id> \
  --room-prefix "call-" \
  --pin ""

# Outbound: LiveKit → Plivo termination
lk sip outbound create \
  --name plivo-outbound \
  --address "XXXXXXXXXX.zt.plivo.com" \
  --transport udp \
  --numbers "+91XXXXXXXXXX" \
  --auth-user "<plivo-sip-user>" \
  --auth-pass "<plivo-sip-pass>"
```

Replace Plivo trunk domain/credentials from Plivo console → SIP Trunking / Zentrunk.

Point Calling CRM:

```text
TELEPHONY_PROVIDER=plivo_livekit
LIVEKIT_URL=wss://lk.YOURDOMAIN
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
PLIVO_DID_E164=+91XXXXXXXXXX
```
