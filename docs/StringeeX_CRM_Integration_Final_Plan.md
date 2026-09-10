# StringeeX CRM Calling Integration — Final Technical Plan

**Prepared:** 8 September 2026  
**Scope:** Integrating StringeeX / Stringee Contact Center calling into a multi-user CRM  
**Primary reference:** Stringee official developer documentation  
**Decision:** Use StringeeX official REST/PCC APIs + Stringee Web SDK. MCP is optional and is not required for the telephony integration.

---

## 1. Executive Decision

The CRM should integrate StringeeX using three official Stringee capabilities:

1. **StringeeX / PCC REST APIs** for tenant-level administration, agents, numbers, queues, call history, reports and configuration.
2. **Stringee Client Authentication + Web SDK** for the actual browser calling experience, using a short-lived user-specific JWT.
3. **Stringee call events/webhooks + periodic reconciliation** to synchronize call state and history back into the CRM.

An MCP server is **not required**. No official StringeeX MCP server was found in the research. If AI functionality is added later, the CRM can expose a small internal MCP adapter on top of the already-built REST integration.

Official documentation:
- https://developer.stringee.com/docs
- https://developer.stringee.com/docs/client-authentication
- https://developer.stringee.com/docs/icc-rest-api
- https://developer.stringee.com/docs/icc-rest-api/contact-center-agent-management
- https://developer.stringee.com/docs/icc-rest-api/Make-call-to-an-agent-then-connect-the-call-to-a-phone
- https://developer.stringee.com/docs/stringeex-rest-api-reference/api-stringeex-call-management
- https://developer.stringee.com/docs/api-stringeex/api-stringeex-report-management
- https://developer.stringee.com/docs/server/call-events
- https://github.com/stringeecom/stringee

---

# 2. The Key Finding About Credentials

There are **two different credential/token purposes**. They must not be mixed.

## 2.1 Server / REST API authentication

Stringee's PCC REST API uses a JWT access token with:

- `iss` = API key SID
- `jti` = token identifier
- `exp` = expiration
- `rest_api` = true
- Signature = HMAC-SHA256 using the API key secret

The token is sent using:

`X-STRINGEE-AUTH: <JWT>`

Stringee's current PCC authentication documentation explicitly describes this mechanism.

**Important:** The production CRM should not put the API key secret in browser JavaScript.

Reference:
https://developer.stringee.com/docs/rest-api-reference/icc-rest-api-authentication

## 2.2 Client / browser calling authentication

For Web SDK calling, Stringee documents a different JWT containing:

- `iss` = API key SID
- `jti` = token identifier
- `exp` = expiration
- `userId` = Stringee user ID

The CRM backend generates this token and the browser uses it to connect to Stringee.

Reference:
https://developer.stringee.com/docs/client-authentication

This is the mechanism that allows the CRM to connect the browser session to the correct Stringee user.

---

# 3. Important Correction Regarding "Admin Username/Password"

The original idea was:

> Configure the StringeeX admin email/password in CRM and use it for all calling.

That should **not** be the final architecture.

The better production architecture is:

```text
CRM Tenant
   |
   +-- Stringee API credentials
   |       |
   |       +-- REST/PCC JWTs generated server-side
   |
   +-- CRM User A
   |       |
   |       +-- Stringee User A
   |               |
   |               +-- Stringee Agent A
   |
   +-- CRM User B
   |       |
   |       +-- Stringee User B
   |               |
   |               +-- Stringee Agent B
   |
   +-- CRM User C
           |
           +-- Stringee User C
                   |
                   +-- Stringee Agent C
```

The admin/integration credential is used for tenant/API operations.

The individual user's `stringee_user_id` is used for the client calling identity.

---

# 4. Your Required Business Model

Your stated model is:

```text
CRM
 |
 +-- User A
 +-- User B
 +-- User C

StringeeX
 |
 +-- User/Agent A -> calling entitlement
 +-- User/Agent B -> calling entitlement
 +-- User/Agent C -> calling entitlement
```

The CRM must maintain an explicit mapping:

| CRM field | Stringee field |
|---|---|
| CRM tenant ID | Stringee project/account/tenant context |
| CRM user ID | Stringee `stringee_user_id` |
| CRM user | Stringee agent |
| CRM calling enabled | Agent/calling permission |
| CRM outbound number | Stringee number |
| CRM call activity | Stringee call ID |

Stringee's Agent API explicitly requires `stringee_user_id` and describes it as the agent's user ID used to authenticate on Stringee.

Reference:
https://developer.stringee.com/docs/icc-rest-api/contact-center-agent-management

---

# 5. Is Separate User Calling Supported?

### Technical identity: YES

Stringee's public documentation clearly supports individual Stringee users and agents.

The Agent API has:

`stringee_user_id`

and the client authentication JWT has:

`userId`.

The Web SDK authentication response also exposes the authenticated `userId`.

Therefore the CRM can technically connect:

```text
CRM User A
    ->
Stringee User A
    ->
Stringee Agent A
```

and independently:

```text
CRM User B
    ->
Stringee User B
    ->
Stringee Agent B
```

### Calling permission: YES

StringeeX's current pricing/features page explicitly lists:

> "Grant Outbound dialing permissions to each agent, hotline"

This establishes that outbound dialing permission can be controlled at agent/hotline level.

Reference:
https://www.stringeex.com/en/pricing

### Subscription/billing attribution: MUST BE VERIFIED WITH THE TENANT'S COMMERCIAL PLAN

The public technical API documentation establishes user/agent identity and outbound dialing permission, but it does **not** explicitly document a billing rule saying:

> "Every call made using Stringee User A is automatically charged against Subscription A."

The current pricing page describes StringeeX packages as priced per **account/month**, while also describing outbound dialing permissions per agent. Therefore the word "subscription" must be interpreted against the actual Stringee commercial/account structure.

This is not a blocker for the technical integration.

It is a commercial/licensing verification item.

### Final decision

Build the integration assuming:

```text
CRM User
   ->
Stringee User
   ->
Stringee Agent
   ->
per-agent outbound permission
```

Before production billing sign-off, verify with Stringee that your purchased accounts/licenses map to those agents in the way your business expects.

---

# 6. Credentials Required

## 6.1 Stringee API Key SID

Required.

Used to create server-side JWTs.

Store encrypted/securely.

## 6.2 Stringee API Key Secret

Required.

This is the sensitive signing secret.

It must exist only on the CRM backend.

Never expose it to:

- browser
- frontend JavaScript
- mobile client
- CRM user
- public logs

## 6.3 StringeeX / Stringee tenant/project information

Required.

Store:

- Stringee account/project identifier
- Stringee tenant identifier if applicable
- project ID
- Stringee environment/region if applicable

## 6.4 Individual Stringee User ID

Required for each calling CRM user.

Example:

```text
CRM user 101
stringee_user_id = "agent_101"
```

## 6.5 Stringee Agent ID

Required for StringeeX/PCC operations.

Example:

```text
stringee_agent_id = "AG_XXXXXXXX"
```

## 6.6 Stringee number

Required for outbound caller ID/routing according to the chosen call flow.

Example:

```text
+84XXXXXXXXX
```

Do not assume every agent automatically owns a separate phone number. The number assignment/display/routing model must match the tenant's StringeeX configuration.

## 6.7 Webhook URLs

Required for CRM synchronization.

At minimum:

```text
https://crm.example.com/api/integrations/stringee/events
```

And, depending on the chosen call flow:

```text
https://crm.example.com/api/integrations/stringee/answer
```

```text
https://crm.example.com/api/integrations/stringee/customer-info
```

Stringee's call settings API explicitly supports `event_url`, `get_customer_info_url`, and `callout_answer_url`.

Reference:
https://developer.stringee.com/docs/icc-rest-api/icc-call-settings

---

# 7. Should CRM Store the StringeeX Admin Password?

## Recommended: NO

Do not make the administrator's normal StringeeX portal password the permanent integration secret.

Prefer:

```text
API Key SID
+
API Key Secret
```

and generate short-lived JWTs on the CRM backend.

The REST API documentation explicitly defines API-key-based JWT authentication.

Reference:
https://developer.stringee.com/docs/rest-api-reference/icc-rest-api-authentication

If the current StringeeX portal only exposes the required API credentials after an admin signs in, the admin can perform the one-time setup and copy/configure the API credentials into the CRM.

The CRM should then operate using API credentials, not the administrator's interactive portal password.

---

# 8. CRM Configuration Screen

Recommended:

```text
CRM Admin
   |
   +-- Settings
       |
       +-- Calling
           |
           +-- Provider: StringeeX
           |
           +-- API Key SID
           +-- API Key Secret
           +-- Project ID
           +-- Tenant/Account ID
           +-- Default Stringee Number
           +-- Event/Webhook URL
           +-- Status: Connected
```

Button:

`Test Connection`

The test should verify:

1. API credentials are valid.
2. CRM can query Stringee.
3. Project/tenant is accessible.
4. Agents can be listed.
5. Required calling permissions/configuration exist.

---

# 9. CRM User Mapping Screen

Recommended:

```text
Settings
  >
Calling
  >
Agents
```

Example:

| CRM User | Stringee User ID | Stringee Agent ID | Calling | Status |
|---|---|---|---|---|
| Ravat | agent_ravat | AG_xxx | Enabled | Available |
| Ankit | agent_ankit | AG_yyy | Enabled | Busy |
| Darshan | agent_darshan | AG_zzz | Enabled | Offline |

The CRM should never allow User A to request a token for User B.

The backend must derive the Stringee user ID from the authenticated CRM user.

---

# 10. Recommended Calling Architecture

```text
                    CRM
                     |
            +--------+--------+
            |                 |
       CRM Frontend       CRM Backend
            |                 |
            |             API Key SID
            |             API Secret
            |                 |
            |          Generate JWT
            |                 |
            |<----------------+
            |
      Stringee Web SDK
            |
            | user-specific JWT
            v
        Stringee Server
            |
            v
        StringeeX
            |
            v
       Customer Phone
```

The browser should never receive the API secret.

---

# 11. Click-to-Call Flow

When CRM User A clicks:

`Call +91XXXXXXXXXX`

the flow should be:

```text
1. CRM authenticates User A.
2. CRM looks up User A's Stringee mapping.
3. Backend confirms:
   - calling_enabled = true
   - user belongs to this tenant
   - Stringee user mapping exists
4. Backend creates short-lived JWT:
   userId = User A's Stringee user ID
5. Browser connects StringeeClient using the JWT.
6. StringeeCall is created.
7. call.makeCall() is executed.
8. CRM displays call state.
9. Stringee sends call events.
10. CRM updates the call activity.
```

Stringee's official Web SDK demonstrates `StringeeClient.connect(access_token)` and `StringeeCall(...).makeCall()`.

References:
https://developer.stringee.com/docs/getting-started-stringee-web-sdk
https://github.com/stringeecom/stringee

---

# 12. Alternative Server-Side Agent Callout

StringeeX also documents a PCC API that accepts:

```json
{
  "agentUserId": "USER_ID",
  "toAgentFromNumberDisplay": "...",
  "toAgentFromNumberDisplayAlias": "...",
  "toCustomerFromNumber": "...",
  "customerNumber": "..."
}
```

The critical field is:

`agentUserId`

and the documentation defines it as the agent's `stringee_user_id`.

This is another strong technical confirmation that Stringee supports operations targeted at a specific agent/user.

Reference:
https://developer.stringee.com/docs/icc-rest-api/Make-call-to-an-agent-then-connect-the-call-to-a-phone

For a CRM softphone, however, the Web SDK is the preferred primary path.

---

# 13. Call History Synchronization

StringeeX exposes:

`GET /v1/call/history`

with filters including:

- call ID
- time
- direction
- agent ID
- call status
- Stringee number
- customer number
- pagination

Reference:
https://developer.stringee.com/docs/api-stringeex/api-stringeex-report-management

CRM should synchronize these records into its own call activity table.

Example:

```text
CRM Call Activity
------------------------------
Customer: John Smith
CRM User: Ravat
Stringee User: agent_ravat
Stringee Agent: AG_xxx

Direction: OUTBOUND
Status: ANSWERED

Start: 2026-09-08 11:32
Answer: 2026-09-08 11:32
End: 2026-09-08 11:36

Duration: 04:21
Stringee Call ID: call_xxxxx
Recording: Available
```

---

# 14. Real-Time Call Events

Stringee provides server call events.

The CRM should expose a secure webhook endpoint.

Example:

```text
POST /api/integrations/stringee/events
```

The CRM should process events such as:

- created
- started
- ringing
- answered
- ended
- agentEnded

The event data can be used to update CRM activities.

Reference:
https://developer.stringee.com/docs/server/call-events

---

# 15. Use Webhooks + Periodic Reconciliation

Do not rely exclusively on webhooks.

Recommended:

```text
             StringeeX
                |
        +-------+-------+
        |               |
      Events         Call History
        |               |
        v               v
     Webhook         Sync Worker
        |               |
        +-------+-------+
                |
                v
           CRM Calls
```

Use webhooks for near-real-time updates.

Use a scheduled sync job to recover calls if an event was lost or the CRM was temporarily unavailable.

Recommended reconciliation interval:

- every 5–15 minutes for active systems
- configurable per tenant

---

# 16. Incoming Call Architecture

Phase 2:

```text
Customer
   |
   v
StringeeX Number
   |
   v
Stringee
   |
   v
CRM Web SDK
   |
   v
Incoming call popup
   |
   +-- Search customer by phone
   |
   +-- Open existing customer
   |
   +-- Create lead if unknown
```

The CRM should display:

```text
Incoming Call
-----------------
John Smith
+91XXXXXXXXXX

[Answer] [Reject]

Open Customer
```

---

# 17. Customer Information Lookup

Stringee's call settings support:

`get_customer_info_url`

Stringee sends `from`, `to`, and `project` information to the CRM endpoint.

The CRM can return customer information that is then made available to the call client.

Reference:
https://developer.stringee.com/docs/icc-rest-api/icc-call-settings

This can be used for incoming-call screen-pop.

---

# 18. Recordings

Stringee provides APIs for recorded call files.

The CRM should store the relationship:

```text
CRM Call
   |
   +-- Stringee Call ID
   +-- Recording reference
   +-- Recording availability
```

Do not unnecessarily duplicate the audio file into CRM storage unless business/compliance requirements require it.

Reference:
https://developer.stringee.com/docs/call-rest-api/call-rest-api-download-recorded-file

---

# 19. Agent Status

StringeeX Agent API provides agent status information.

Useful CRM statuses:

```text
AVAILABLE
BUSY
OFFLINE
AFTER_CALL_WORK
```

The exact values should follow the current Stringee API response.

Stringee documents system status such as:

- agent in call
- agent not in call
- after call work

Reference:
https://developer.stringee.com/docs/icc-rest-api/contact-center-agent-management

---

# 20. Numbers, Queues and IVR

Stringee's PCC REST API supports:

- Numbers
- Agents
- Groups
- Queues
- IVR
- Routing

Reference:
https://developer.stringee.com/docs/icc-rest-api

These should be integrated in later phases rather than blocking the initial CRM dialer.

---

# 21. StringeeX Commercial Account Structure

The current StringeeX pricing page lists packages by:

`$X USD/account/month`

and states, for example, that Essentials requires at least 4 accounts.

It also explicitly lists:

- Manage portal accounts
- Manage groups
- Manage queues
- Grant outbound dialing permissions to each agent/hotline
- Call recording configuration

Reference:
https://www.stringeex.com/en/pricing

### Important interpretation

Do not build CRM billing logic based on an assumption that:

```text
1 CRM user = 1 Stringee billing account
```

until Stringee confirms how your specific subscription is configured.

Instead, model the CRM with:

```text
CRM User
Stringee User
Stringee Agent
Calling Permission
Stringee Number
Commercial Entitlement
```

The commercial entitlement can be mapped once the tenant confirms its StringeeX contract/package.

---

# 22. Exact Confirmation to Get From Stringee

Before production, send Stringee the following questions:

### Question 1

"For our StringeeX tenant, each CRM user will map to one Stringee user/agent. Can each Stringee user/agent independently make outbound calls from the CRM using the Web SDK?"

### Question 2

"If User A and User B are separate StringeeX licensed/accounts/agents, can the CRM generate a client JWT with User A's `userId` and have the call executed as User A?"

### Question 3

"How is outbound dialing permission assigned? Is it controlled per agent/user, per number/hotline, or both?"

### Question 4

"How does StringeeX associate call usage/charges with the agent/account/license that initiated the call?"

### Question 5

"If multiple agents use the same StringeeX tenant, can the CRM independently identify the calling agent in call history and reports?"

### Question 6

"Does the purchased StringeeX package include API/Web SDK calling for all licensed agents, or is an additional feature/license required?"

### Question 7

"What exact API credentials should a production CRM integration use: API Key SID + API Key Secret, or another tenant-level credential?"

### Question 8

"Can the API key be created/managed by a tenant administrator without exposing the administrator's portal password to the CRM?"

These answers will finalize the commercial entitlement configuration.

---

# 23. Security Requirements

## Never expose

- API Key Secret
- REST signing secret
- Admin password
- Long-lived integration tokens

## Store encrypted

- API Key SID
- API Key Secret
- Tenant/project identifiers
- Stringee user IDs
- Agent IDs
- Number IDs

## Backend-only

JWT generation must happen on the CRM backend.

The browser receives only the short-lived client token.

## Tenant isolation

Every Stringee record in the CRM must belong to a CRM tenant.

Never allow:

```text
Tenant A CRM User
    ->
Tenant B Stringee User
```

---

# 24. Recommended Database Model

## stringee_integrations

```text
id
crm_tenant_id
stringee_account_id
stringee_project_id
api_key_sid
api_key_secret_encrypted
default_stringee_number
status
last_verified_at
created_at
updated_at
```

## stringee_users

```text
id
crm_tenant_id
crm_user_id
stringee_user_id
stringee_agent_id
stringee_number
outbound_enabled
status
created_at
updated_at
```

## crm_calls

```text
id
crm_tenant_id
crm_customer_id
crm_user_id

stringee_call_id
stringee_user_id
stringee_agent_id

direction
from_number
to_number

status
started_at
answered_at
ended_at

duration
answer_duration
end_reason

recording_available
recording_reference

created_at
updated_at
```

## stringee_webhook_events

```text
id
crm_tenant_id
event_type
stringee_call_id
payload
received_at
processed_at
processing_status
retry_count
```

---

# 25. API Endpoints Required in the CRM

Recommended internal endpoints:

```text
POST /api/integrations/stringee/connect
POST /api/integrations/stringee/test
POST /api/integrations/stringee/sync-agents

GET  /api/stringee/calling/token
POST /api/stringee/calls/start
POST /api/stringee/calls/end

POST /api/integrations/stringee/events
GET  /api/integrations/stringee/customer-info

POST /api/integrations/stringee/reconcile
GET  /api/calls/{id}/recording
```

The frontend should call the CRM backend, not Stringee administrative APIs directly.

---

# 26. Token Flow

```text
CRM User logs in
       |
       v
CRM session authenticated
       |
       v
GET /api/stringee/calling/token
       |
       v
CRM verifies:
  tenant
  user
  calling enabled
  stringee_user_id
       |
       v
Generate JWT
  iss = API Key SID
  jti = unique ID
  exp = short expiry
  userId = mapped Stringee user
       |
       v
Browser
       |
       v
StringeeClient.connect(token)
```

The Web SDK supports token refresh through its `requestnewtoken` event.

Reference:
https://developer.stringee.com/docs/getting-started-stringee-web-sdk

---

# 27. Recommended Token Lifetime

Use a short lifetime.

Recommended initial policy:

```text
Client JWT:
5–15 minutes
```

Refresh when the SDK requests a new token.

Do not create a token valid for days or months.

---

# 28. Phase 1 — MVP

Build only:

### Admin

- StringeeX connection
- API credential configuration
- Connection test
- Agent sync
- User mapping

### User

- Request calling token
- Stringee Web SDK
- Click-to-call
- Call timer
- Hang up
- Basic call status

### Backend

- Secure JWT generation
- Call activity creation
- Webhook receiver
- Basic call-history sync

### Result

A CRM user can:

```text
Open customer
    ->
Click Call
    ->
Call using their mapped Stringee identity
    ->
CRM stores the call
```

---

# 29. Phase 2

Add:

- Incoming call popup
- Customer lookup
- Call recordings
- Full call history
- Missed calls
- Agent status
- Call notes
- Call outcome
- Retry/reconciliation
- Number management

---

# 30. Phase 3

Add:

- Queues
- IVR
- Groups
- Routing
- Transfers
- Conference
- Supervisor functionality
- Agent performance reports

Stringee's PCC API supports these areas.

---

# 31. Phase 4 — AI / MCP

MCP is optional.

Recommended architecture:

```text
CRM AI Assistant
       |
       v
Internal CRM MCP Adapter
       |
       +-- CRM tools
       |
       +-- Stringee tools
               |
               v
          StringeeX REST API
```

Example AI tools:

```text
get_call_history()
get_agent_status()
get_missed_calls()
get_customer_calls()
get_call_recording()
get_agent_performance()
start_call()
```

The AI should not receive raw Stringee API secrets.

---

# 32. MCP Research Result

A search of official Stringee documentation and public GitHub/search results did not identify an official StringeeX MCP server.

The official Stringee GitHub organization does provide the Web SDK and server examples, including the JavaScript SDK and token-generation samples.

Official SDK:
https://github.com/stringeecom/stringee

Therefore:

**Do not make MCP part of the core integration.**

Build the REST/Web SDK integration first.

If an MCP layer is later required, build it on top of the stable CRM integration.

---

# 33. Final Architecture

```text
                         CRM
                          |
          +---------------+----------------+
          |                                |
       Frontend                         Backend
          |                                |
   Stringee Web SDK              Stringee Integration
          |                       |
          |                       +-- REST/PCC API
          |                       +-- JWT generation
          |                       +-- Webhooks
          |                       +-- Sync worker
          |                       |
          +-------------+---------+
                        |
                    Stringee
                        |
                    StringeeX
                        |
       +----------------+----------------+
       |                |                |
    Agent A          Agent B          Agent C
       |                |                |
 Stringee User A   Stringee User B   Stringee User C
       |                |                |
   CRM User A       CRM User B       CRM User C
```

---

# 34. Final Go/No-Go Decision

## GO

The technical integration is viable using official Stringee capabilities.

### Use

- StringeeX/PCC REST API
- Stringee Client Authentication
- Stringee Web SDK
- Stringee call events
- Stringee call history/report APIs

### Do not use

- Admin password as the browser calling credential
- Shared calling identity for all CRM users
- MCP as a required dependency

### Required production inputs

1. Stringee API Key SID
2. Stringee API Key Secret
3. Stringee project/account information
4. Stringee user ID for each CRM caller
5. Stringee agent ID for each CRM caller
6. Stringee number(s)
7. Outbound dialing permissions
8. Recording configuration if recordings are required
9. CRM webhook URL
10. Customer-info URL if screen-pop is required

### One commercial validation

The only item that remains outside what the public technical documentation definitively states is the exact **commercial billing/license entitlement relationship** for your particular StringeeX subscription.

This does **not** block development.

The technical model of:

```text
CRM User
   ->
Stringee User ID
   ->
Stringee Agent
   ->
Outbound permission
   ->
Call
```

is supported by the public documentation.

The StringeeX pricing page confirms agent-level outbound dialing permissions, but the public documentation does not define a universal billing formula tying every call to a specific "user subscription." Your actual StringeeX contract/account setup must determine that.

---

# 35. Production Acceptance Test

Before launch, test with two actual licensed users.

## Test A

```text
CRM User A
Stringee User A
Agent A
License/entitlement A
```

Make 3 outbound calls.

Verify:

- Caller identity = A
- Agent = A
- Correct number
- Call appears in Stringee history
- CRM activity = A
- Recording = A if enabled
- Usage/billing attribution = A according to Stringee's commercial system

## Test B

Repeat with User B.

Then verify that A and B are completely separated.

## Cross-user security test

Attempt:

```text
CRM User A -> request token for Stringee User B
```

Expected:

```text
DENIED
```

This must be enforced by the CRM backend.

---

# 36. Final Recommendation

Proceed with implementation.

The integration should be designed around **individual Stringee user identity**, not shared admin calling.

The StringeeX admin/API credentials are for the **tenant integration layer**.

The individual CRM user's Stringee identity is for the **calling layer**.

The browser should use the official Stringee Web SDK with a short-lived JWT generated by the CRM backend.

The CRM should receive Stringee call events and reconcile them against Stringee call history.

MCP should be considered only later for AI automation.

**Status: TECHNICALLY APPROVED FOR IMPLEMENTATION.**

**Commercial item to verify:** exact license/billing entitlement mapping for your existing StringeeX subscription/account structure.