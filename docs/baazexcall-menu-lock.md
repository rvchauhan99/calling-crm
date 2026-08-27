# Baazexcall (LakshyaCRM) live menu lock

Source: reverse-engineered from `admin.baazexcall.com` + `baazexcall.com` JS bundles and authenticated API (`https://api.lakshyacrm.com/api/v1`) on 2026-08-27.

White-label vendor: **LakshyaCRM**. Tenant resolved via `X-Company-Domain` = hostname.

## Admin portal menus (`admin.baazexcall.com`)

| Menu | Route | Permission key (our clone) | Notes |
|------|-------|----------------------------|-------|
| Dashboard | `/` | `dashboard.view` | Stats + report; date filters |
| Admins | `/admins` | `admins.manage` | Super-admin only on vendor; company admins in our clone |
| Caller | `/caller` | `callers.manage` | Agents: name, status, reset password |
| Affiliate | `/affiliate` | `affiliates.manage` | Lead feeders / partners |
| Leeds | `/leeds` | `leads.view` | Phone leads, import, daily auto-assign |
| Call History | `/call-history` | `calls.view` | CDR-style history + pending/responded |
| Client List | `/client-list` | `clients.view` | Converted clients, ledger, notes, call |
| Report | `/report` | `reports.view` | Caller / affiliate / company reports |
| Response | `/response` | `dispositions.manage` | Disposition slots (carry_forward / non_carry_forward) |

### Admin API map

- Auth: `/admin/auth/login`, `/logout`, `/refresh`, `/admin/reset-password`
- Profile: `/admin/me`, `/admin/me/site`
- Callers: `/admin/callers` CRUD-ish + status + reset password
- Affiliates: `/admin/affiliates` + status + reset password
- Leads: `/admin/leeds`, `/import`, `/daily-auto-assign`
- Responses: `/admin/responses`, `/admin/responses/:slot`
- Call history: `/admin/call-history`
- Clients: getClientList, create, update, delete, transaction, search-user, ledger, notes, call
- Reports: `/admin/reports/caller|affiliate|company`

### Key entities (from live samples)

**Caller:** `id`, `fullname`, `userType=CALLER`, `userStatus`, `totalClients`, `admin`

**Lead (Leed):** `id`, `phone_number`, `assignedTo`, `type` (unassigned|…), `response`, `responseType`, `isAssigned`, `assignedAt`

**Response (disposition):** `slotNumber` 1..N, `responseText`, `type` = `carry_forward` | `non_carry_forward`

**Caller report:** `clientCreate`, `totalCallDone`, `followUpClient`, `ftd`, `totalDeposit`, `totalWithdrawal`, `dwRatio`, `responseCounters`

## Agent / User portal (`baazexcall.com`)

| Menu | Route | Permission key |
|------|-------|----------------|
| Dashboard | `/` | `dashboard.view` |
| Today Calls | `/today-calls` | `today_calls.use` |
| Call History | `/call-history` | `calls.view` |
| My Clients | `/my-clients` | `clients.view` |
| Reports | `/reports` | `reports.view` |

### Agent API map

- Auth: `/auth/login`, `/logout`, `/refresh`
- `/user/me`, `/user/reset-password`
- Today calls: status, get-numbers, list, response, admin responses
- Call history, clients (notes, call, ledger)

## Gaps we close in the better clone

Baazexcall is thin (leads + dispositions + callers + client ledger). We keep those modules and add: menu RBAC, Live Floor, campaigns/dialer, IVR/DID, WhatsApp/SMS, automations, audit, softphone, pipeline, follow-ups.
