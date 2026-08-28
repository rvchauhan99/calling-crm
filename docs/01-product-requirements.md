# Calling CRM — Product Requirements Document (PRD)

**Document ID:** `01-product-requirements`  
**Audience:** Product owners, architects, coding agents  
**Status:** Final blueprint (requirements only)  
**Companion docs:** [02-system-architecture.md](./02-system-architecture.md), [03-module-specs-and-build-guide.md](./03-module-specs-and-build-guide.md), [baazexcall-menu-lock.md](./baazexcall-menu-lock.md)

---

## 1. Vision and positioning

### 1.1 Product name (working)

**Calling CRM** — a production-grade, access-based telecalling CRM with integrated softphone, dialer, omnichannel follow-up, live floor monitoring, and finance-desk client ledger.

### 1.2 Goal

Build a **better clone of Baazexcall** (white-label LakshyaCRM) that:

1. Achieves **feature parity** with every Baazexcall admin and agent menu.
2. Replaces coarse admin-vs-user access with **menu- and permission-based RBAC** (users only see assigned menus; APIs enforce the same).
3. Adds best-in-class calling CRM capabilities: campaigns/dialer, IVR/DID, Live Floor, WhatsApp/SMS, pipeline, follow-ups, automation, audit, AI/QA.

### 1.3 Industry pattern (from live reverse-engineer)

Baazexcall reports include `ftd`, `totalDeposit`, `totalWithdrawal`, `dwRatio`, and client **ledger/transactions**. This product serves **sales / trading-desk / high-intent outbound calling** teams, not only generic lead management. The Client Finance / Ledger module is first-class.

### 1.4 Portals

| Portal | Login | Typical users |
|--------|-------|---------------|
| **Admin** | Email + password | Super Admin, Company Admin, Supervisor (when menus assigned) |
| **Agent (User Panel)** | Username + password | Caller / Agent, optionally Affiliate with scoped menus |

Branding is **domain-driven** (logo, site name per company domain), matching Baazexcall’s `X-Company-Domain` / multi-tenant logo pattern.

---

## 2. Source parity lock (Baazexcall / LakshyaCRM)

Live lock date: 2026-08-27. Details: [baazexcall-menu-lock.md](./baazexcall-menu-lock.md).

### 2.1 Admin parity menus

| Baazex menu | Route | Must ship |
|-------------|-------|-----------|
| Dashboard | `/` | Yes |
| Admins | `/admins` | Yes |
| Caller | `/caller` | Yes |
| Affiliate | `/affiliate` | Yes |
| Leeds | `/leeds` | Yes (rename label to **Leads** in UI; keep “Leeds” as alias if desired) |
| Call History | `/call-history` | Yes |
| Client List | `/client-list` | Yes |
| Report | `/report` | Yes |
| Response | `/response` | Yes |

### 2.2 Agent parity menus

| Baazex menu | Route | Must ship |
|-------------|-------|-----------|
| Dashboard | `/` | Yes |
| Today Calls | `/today-calls` | Yes |
| Call History | `/call-history` | Yes |
| My Clients | `/my-clients` | Yes |
| Reports | `/reports` | Yes |

### 2.3 Locked business rules from live product

- Leads are primarily **phone_number**-centric; assignment to callers; import + **daily auto-assign** count.
- Dispositions (Responses) are **slot-numbered** with type:
  - `carry_forward` — lead stays in working set / retry path.
  - `non_carry_forward` — lead leaves active carry path.
- Caller reports track: clients created, calls done, follow-up clients, **FTD**, deposits, withdrawals, D/W ratio, per-disposition counters.
- Clients support notes, call, ledger, transactions.

### 2.4 Known Baazexcall gaps (must close)

No production-grade softphone UI, IVR/DID designer, campaign dialer modes, Live Floor, WhatsApp/SMS inbox, sales pipeline, follow-up calendar, custom RBAC menus, strong Lead 360, audit log, or automation engine.

---

## 3. Personas

| Persona | Portal | Responsibility |
|---------|--------|----------------|
| **Super Admin** | Admin | Platform / company bootstrap, billing hooks, all menus |
| **Company Admin** | Admin | Users, roles/menus, leads, dispositions, campaigns, numbers, settings |
| **Supervisor** | Admin (+ optional softphone) | Live Floor, team leads, listen/whisper/barge, QA, team reports |
| **Agent (Caller)** | Agent | Today Calls, softphone, dispositions, follow-ups, own clients |
| **Affiliate** | Admin or limited Agent | Attributed leads / conversion reports only (scoped) |
| **Custom role** | Either | Any combination via menu + permission assignment |

---

## 4. Access model (non-negotiable)

### 4.1 Principles

1. **Menus are data**, not hardcoded by role name.
2. Each user inherits a **role template**, then may receive **per-user menu and permission overrides** (grant or revoke).
3. Sidebar shows only assigned menus.
4. Every API checks **permission + data scope**.
5. Sensitive actions write an **audit log**.

### 4.2 Menu catalog fields

| Field | Description |
|-------|-------------|
| `key` | Stable id, e.g. `admin.leads` |
| `label` | Display name |
| `parentKey` | Optional parent for nested nav |
| `route` | App path |
| `portal` | `admin` \| `agent` |
| `icon` | Icon key |
| `sortOrder` | Integer |
| `enabled` | Soft kill-switch |
| `requiredPermissions` | List of permission keys to open the page |

### 4.3 Permission key convention

Format: `module.action`

Examples: `leads.view`, `leads.create`, `leads.import`, `leads.assign`, `leads.export`, `leads.delete`, `calls.view`, `calls.listen`, `calls.barge`, `recordings.play`, `recordings.download`, `clients.view`, `clients.ledger`, `clients.ledger.edit`, `reports.export`, `roles.manage`, `menus.assign`, `audit.view`.

### 4.4 Data scope

| Scope | Meaning |
|-------|---------|
| `ALL` | Entire company tenant |
| `TEAM` | Users in same team(s) |
| `OWN` | Records owned by / assigned to current user |

Scope applies to lists, exports, reports, recordings, and ledger views.

### 4.5 Default role templates (editable)

**Agent:** Dashboard, Softphone, Today Calls, My Leads (or scoped Leads), Follow-ups, My Calls / Call History, My Clients, WhatsApp (own), Scripts, Status/Break, Reports (own). Scope: `OWN`.

**Supervisor:** Agent set + Live Floor, Team Leads, Team Reports, Listen/Whisper/Barge, QA, Campaigns (view). Scope: `TEAM` (or `ALL` if configured).

**Company Admin:** Full admin catalog including Users, Roles & Menus, Numbers, IVR, Integrations, Settings, Audit. Scope: `ALL`.

**Super Admin:** Everything + tenant/branding/billing. Scope: `ALL`.

**Affiliate:** Affiliate dashboard/report + attributed leads only. Scope: attributed set.

---

## 5. Complete target menu catalog

Users only see menus assigned to them. Below is the **full product catalog**.

### 5.1 Admin portal menus

| # | Menu key | Label | Route | Parity / New |
|---|----------|-------|-------|--------------|
| 1 | `admin.dashboard` | Dashboard | `/admin` | Parity |
| 2 | `admin.live_floor` | Live Floor | `/admin/live-floor` | New |
| 3 | `admin.leads` | Leads | `/admin/leads` | Parity (Leeds) |
| 4 | `admin.today_calls_monitor` | Today Calls Monitor | `/admin/today-calls` | New (ops view) |
| 5 | `admin.pipeline` | Pipeline | `/admin/pipeline` | New |
| 6 | `admin.clients` | Clients | `/admin/clients` | Parity |
| 7 | `admin.follow_ups` | Follow-ups | `/admin/follow-ups` | New |
| 8 | `admin.campaigns` | Campaigns | `/admin/campaigns` | New |
| 9 | `admin.dialer` | Dialer Control | `/admin/dialer` | New |
| 10 | `admin.call_history` | Call History | `/admin/call-history` | Parity |
| 11 | `admin.dispositions` | Responses | `/admin/responses` | Parity |
| 12 | `admin.scripts` | Scripts | `/admin/scripts` | New |
| 13 | `admin.messaging` | Messaging | `/admin/messaging` | New |
| 14 | `admin.whatsapp` | WhatsApp Inbox | `/admin/whatsapp` | New |
| 15 | `admin.sms` | SMS | `/admin/sms` | New |
| 16 | `admin.numbers` | Numbers (DID) | `/admin/numbers` | New |
| 17 | `admin.ivr` | IVR / Call Flows | `/admin/ivr` | New |
| 18 | `admin.queues` | Queues | `/admin/queues` | New |
| 19 | `admin.callers` | Callers | `/admin/callers` | Parity |
| 20 | `admin.affiliates` | Affiliates | `/admin/affiliates` | Parity |
| 21 | `admin.admins` | Admins | `/admin/admins` | Parity |
| 22 | `admin.teams` | Teams | `/admin/teams` | New |
| 23 | `admin.roles` | Roles & Menus | `/admin/roles` | New (critical) |
| 24 | `admin.reports` | Reports | `/admin/reports` | Parity |
| 25 | `admin.automation` | Automation | `/admin/automation` | New |
| 26 | `admin.integrations` | Integrations | `/admin/integrations` | New |
| 27 | `admin.qa` | Quality / QA | `/admin/qa` | New |
| 28 | `admin.audit` | Audit Log | `/admin/audit` | New |
| 29 | `admin.settings` | Settings | `/admin/settings` | New |
| 30 | `admin.billing` | Billing | `/admin/billing` | Optional commercial |

### 5.2 Agent portal menus

| # | Menu key | Label | Route | Parity / New |
|---|----------|-------|-------|--------------|
| 1 | `agent.dashboard` | Dashboard | `/agent` | Parity |
| 2 | `agent.softphone` | Softphone | `/agent/softphone` | New |
| 3 | `agent.today_calls` | Today Calls | `/agent/today-calls` | Parity |
| 4 | `agent.leads` | My Leads | `/agent/leads` | New |
| 5 | `agent.follow_ups` | Follow-ups | `/agent/follow-ups` | New |
| 6 | `agent.call_history` | Call History | `/agent/call-history` | Parity |
| 7 | `agent.clients` | My Clients | `/agent/my-clients` | Parity |
| 8 | `agent.whatsapp` | WhatsApp | `/agent/whatsapp` | New |
| 9 | `agent.scripts` | Scripts | `/agent/scripts` | New |
| 10 | `agent.reports` | Reports | `/agent/reports` | Parity |
| 11 | `agent.status` | Status / Break | `/agent/status` | New |

---

## 6. Module requirements

### 6.1 Dashboard

**Admin**

- KPIs (today / custom range): total calls, answered, missed, outbound, talk time, unique leads called, conversion, FTD count, SLA first-touch breaches.
- Presence strip: available / on-call / wrap-up / break / offline counts.
- Widgets configurable per user (same access model).

**Agent**

- Own KPIs: calls done, answered, dispositions, follow-ups due, clients created, FTD (if permitted).

### 6.2 Live Floor (War Room)

- Real-time agent cards: name, status, current lead/phone (masked if required), duration, campaign.
- Supervisor actions: listen, whisper, barge, take-over (permission-gated).
- Queue wait, abandon rate, campaign pace.
- Click-through to lead 360 and post-call recording.

### 6.3 Leads (Baazex Leeds+)

- List with search and filters: status, owner, campaign, source, last-call, follow-up due, DND, response type.
- CRUD; duplicate detect on phone/email; merge.
- Import CSV/Excel with column mapping; export if `leads.export`.
- Auto-assign: round-robin, weighted, by source, by skill, only punched-in agents.
- Preserve **daily auto-assign** quota per admin/company (Baazex parity).
- Custom fields, tags, source, campaign, DND flag.
- **Lead 360:** profile, numbers, timeline (calls, WhatsApp, SMS, notes, status changes), files, tickets, finance summary if converted.

### 6.4 Today Calls (agent work queue)

- Daily assigned queue; fetch next number; agent status (available / break / wrap-up).
- On call end: **forced disposition** before next lead.
- Honor `carry_forward` vs `non_carry_forward` (retry vs drop from carry set).
- Optional note + next follow-up + 1-click WhatsApp/SMS.
- Admin monitor view of all agents’ today queues.

### 6.5 Pipeline

- Configurable stages; kanban + list.
- Deal value, expected close, lost reasons.
- Disposition mapping can auto-move stage.

### 6.6 Clients + Ledger (Baazex Client List+)

- Convert lead → client; person + optional company; multi numbers.
- Notes, call-from-client, full activity timeline.
- **Ledger / transactions:** deposit, withdrawal, FTD flag, running balance.
- Permissions: `clients.ledger` (view), `clients.ledger.edit` (mutate); optional maker-checker.
- Export ledger restricted and audited.

### 6.7 Affiliates

- Create/disable affiliates; reset password.
- Lead attribution; affiliate performance report (scoped).

### 6.8 Campaigns + Dialer

- Outbound list campaigns and inbound queue campaigns.
- Bind: lead list, agents/teams, caller ID, script, dispositions, retry rules, calling hours, DND, pacing.
- Modes: click-to-call, preview, progressive, power; predictive as later phase; broadcast/IVR blast as later phase.
- AMD / voicemail drop as add-on.
- Number masking; wrap-up timer with forced disposition.

### 6.9 Call History / CDR

- Direction (in/out/missed), agent, DID, duration, recording, disposition, campaign, lead/client link.
- Play / download recordings by permission.
- Filter + export.

### 6.10 Responses (Dispositions) + Scripts

- Slot-based responses: `slotNumber`, `responseText`, `type` (`carry_forward` | `non_carry_forward`).
- Map disposition → next lead status, create follow-up, send template, pipeline stage, convert-to-client.
- Stage-aware call scripts / teleprompter for agents.

**Default seed (from live Baazexcall samples):**

| Slot | Text | Type |
|------|------|------|
| 1 | Not Answer | carry_forward |
| 2 | Follow up | carry_forward |
| 3 | Registered | carry_forward |
| 4 | Not Reachable | non_carry_forward |
| (configurable) | Busy / Wrong Number / Not Interested / DND / Callback | as configured |

### 6.11 Follow-ups

- Calendar + list; snooze; missed-follow-up alerts.
- Queue callback from inbound missed calls.

### 6.12 Messaging (WhatsApp / SMS / Email)

- WhatsApp Business API: templates, shared or own inbox, 1-click from lead, bulk, 24h session window.
- SMS: India DLT-registered templates, bulk, delivery reports.
- Email via SMTP (phase later); all channels on unified lead timeline.
- Messaging can be feature-flagged until Meta / DLT credentials exist.

### 6.13 Telephony config

- DID / virtual numbers; inbound/outbound; caller ID presentation.
- Visual IVR / call flow builder: play audio, DTMF, team, queue, voicemail, office hours, SMS notify, hangup, sticky agent, skill routing.
- Queues, ring groups, music on hold, greeting library.
- Blocklist, time groups, holidays, failover routes.

### 6.14 People (Callers, Admins, Teams)

- Users: email (admin login), username (agent login), extension, forward-to-mobile, outbound allow, SIP/WebRTC credentials.
- Status: active / inactive; reset password; API key reset where applicable.
- Teams, shifts, punch in/out, break codes, idle SLA.
- **Roles & Menus** UI: assign menus and permissions to roles and users.

### 6.15 Reports

**Parity reports**

- Caller report (Baazex KPIs including FTD, D/W, response counters).
- Affiliate report.
- Company report.

**Enhancement reports**

- Disposition mix, hour-of-day, login/break compliance, conversion funnel, first-call-connect, campaign performance, Live Floor historical.

Features: date range, saved views, schedule email, CSV/Excel export; all scope-respecting.

### 6.16 Automation

Triggers: new lead, disposition submitted, missed call, follow-up due, SLA breach, FTD created.  
Actions: assign/reassign, restage, SMS/WA/email, create task/follow-up, webhook.

### 6.17 Integrations

- Public REST + webhooks (`lead.created`, `call.ended`, `disposition.submitted`).
- Lead sources: website forms, Facebook Lead Ads, IndiaMART / JustDial-class inbound.
- Optional CRM connectors (Zoho / HubSpot) in a later phase.

### 6.18 Softphone (Agent)

- Browser WebRTC softphone: dial, answer, hold, mute, transfer, conference, DTMF keypad, after-call work (ACW).
- Campaign join / next-lead; screen-pop Lead 360.
- Must work with telephony adapter; mock provider allowed for local/dev.

### 6.19 Quality / QA + AI add-ons

- Evaluate recordings; scorecards; calibration; coaching tasks.
- AI (phase): transcription, summary, sentiment, auto-tags, QA auto-score, live assist prompts.

### 6.20 Settings, Audit, Billing

- Company profile, branding (logo, colors, domain), timezone (default IST), recording consent text, TRAI/DND policy.
- API keys, IP allowlist, session timeout, MFA for admin logins.
- Audit: login success/fail, exports, role/menu changes, lead deletes, recording downloads, ledger edits.
- Billing module only if selling minutes/SMS (optional).

---

## 7. Best-in-class enhancements checklist

| Area | Requirement |
|------|-------------|
| Access | Menu + permission + data-scope RBAC |
| Ops | Live Floor with listen/whisper/barge |
| Voice | Softphone, click-to-call, CDR, recordings, dialer modes |
| Inbound | IVR builder, queues, sticky agent |
| Omni | WhatsApp + SMS on lead timeline |
| CRM depth | Pipeline, follow-ups, Lead 360, custom fields |
| Finance desk | Ledger, FTD, D/W ratio, permissioned edits |
| Automation | Rules engine + webhooks |
| Compliance | DND, DLT, recording consent, field masking, retention |
| Quality | QA + optional AI |
| Extensibility | Custom fields; telephony provider adapter |
| Mobile | Agent app phase 2 |

---

## 8. Success metrics (north-star)

- Connects per agent-hour  
- Disposition completeness %  
- Follow-up SLA hit rate  
- FTD rate (where applicable)  
- Talk-time %  
- Abandon rate (inbound)  
- First-response time (inbound)  
- Time-to-first-touch on new leads  

---

## 9. Non-functional requirements (product view)

- Multi-tenant-ready branding (even if v1 is single company).
- Server-side authorization on every mutation and export.
- India-first: +91 normalization, IST reporting, DLT SMS, DND.
- Softphone and Live Floor feel realtime (WebSocket presence).
- No plaintext secrets in repo; no customer dumps from Baazexcall.

---

## 10. Out of scope for requirements phase

- Writing application code (see architecture + build guide when implementing).
- Guaranteeing Meta WhatsApp approval or carrier DID provisioning (design for disable-until-ready).

---

## 11. Document map for coding agents

| Doc | Use for |
|-----|---------|
| **01 (this file)** | What to build — menus, features, rules, personas |
| **02 Architecture** | How to structure stack, data, APIs, security |
| **03 Module specs** | Screens, fields, workflows, phases, acceptance criteria |
| **baazexcall-menu-lock** | Raw reverse-engineer annex |

**Rule for coding agents:** Implement parity modules first, then enhancements in the phase order defined in doc 03. Never ship a nav item without a working list/detail page and API permission checks.
