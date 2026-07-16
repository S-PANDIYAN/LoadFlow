# LoadFlow — Freight Brokerage Operations Suite

An operations platform connecting **Brokers**, **Carriers**, and **Shippers**: dynamic RBAC with admin-built roles, a full load lifecycle state machine with audit trail, carrier compliance auto-flagging that blocks dispatch, and versioned rate confirmations.

**Live demo:** _(Render URL here after deploy)_ · **API docs:** `/docs`

---

## Stack

**FastAPI + SQLAlchemy + SQLite + JWT**, server-rendered UI (Jinja2 + vanilla JS).


## Run Locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open **http://localhost:8000**. Tables are created and demo data is seeded automatically on first boot.

## Demo Accounts (password: `demo1234`)

| Role | Email | Demonstrates |
|---|---|---|
| Broker Admin | `broker.admin@demo.io` | Role builder, staff invites, full board |
| Broker Dispatcher | `dispatcher@demo.io` | Post / assign / rate, but **no** compliance override (403) |
| Broker Ops Lead | `opslead@demo.io` | Holds `load.override_compliance_flag` |
| Carrier Admin | `carrier.admin@demo.io` | Carrier-side roles and staff |
| Driver | `driver@demo.io` | Status updates + POD only |
| Carrier Dispatch | `carrier.dispatch@demo.io` | Accept / decline only |
| Shipper | `shipper@demo.io` | Sees only their own shipments |

### 2-minute demo path

1. Login as `dispatcher@demo.io` → open flagged load **LF-00004** (carrier has expired insurance) → try to progress it → **blocked (409)**.
2. Try to override → **403, permission denied** (logged server-side).
3. Login as `opslead@demo.io` → override with a justification → progression now works.
4. Open the load's **Audit Trail** — every action timestamped and attributed.
5. As Broker Admin, open **Staff & Roles** → create a custom role by ticking permissions from the catalog.

## How the Requirements Are Met

| Requirement | Implementation |
|---|---|
| RBAC, not hardcoded | Permission catalog seeded as data; roles are DB rows created by org admins via the UI at runtime; authorization checks **permission codes only** (`require_permission("load.assign_carrier")`) — role names appear nowhere in business logic. Role edits take effect immediately (permissions read from DB per request). |
| Bootstrap | Registering a Broker/Carrier org creates the org + its first Admin in one step. Staff can only be created by a `staff.manage` holder — never self-registered. Shippers are standalone accounts. |
| Org scoping | Every query filters by the authenticated user's `organization_id` from the JWT, independent of permissions. |
| Object scoping | Shippers see only their own loads; carrier staff only loads assigned to their org. Out-of-scope objects return 404 so existence is not leaked. |
| API-layer enforcement | All rules live in FastAPI dependencies. The UI only hides buttons as a courtesy — `curl` any endpoint with a low-privileged token to verify (403 + log line). |
| State machine | `Posted → Carrier Assigned → Rate Confirmed → Dispatched → In Transit → Delivered → POD Verified → Invoiced/Closed`. Illegal transitions rejected server-side (409). |
| Audit trail | Every state change and significant action recorded in `load_events` with actor + timestamp; viewable per load in the UI. |
| Compliance blocking | Expired insurance, non-active MC/DOT authority, or unapproved equipment/commodity auto-flags the load at assignment and is **re-checked at every transition**. Progression past Carrier Assigned is blocked until the record is fixed or a `load.override_compliance_flag` holder overrides with a justification (audit-logged). |
| Rate versioning | Versions are immutable rows; re-negotiation creates v2, v3, …; the load permanently pins the version actually confirmed. |
| Denial logging | Permission and scope denials log to console with user, needed permission, and path. |

## Verification

`verify_spec.py` runs 38 end-to-end checks against a live server covering every requirement above — including proof the RBAC is dynamic (registers a new org, builds a new role at runtime, edits its permissions, and observes the change take effect on an existing session).

```bash
uvicorn app.main:app &   # then:
python verify_spec.py    # expect: 38/38 PASSED
```

## Assumptions

- Brokers maintain carrier compliance records (the broker carries the liability and vets carriers); carrier admins can view their own record.
- Staff "invites" are direct account creation with a temporary password (email delivery out of scope).
- POD is a recorded confirmation (reference/note), not file storage.
- Approved equipment/commodities are comma-separated lists; an empty list means unrestricted.
- Org admins implicitly hold all catalog permissions within their own org (standard SaaS owner semantics); org scoping still applies to them.

## Incomplete / With More Time

- Alembic migrations (used `create_all` for velocity)
- Real file upload + viewer for POD; email invites; password reset
- Persistent disk on Render (free tier resets SQLite on redeploy; the idempotent seed keeps every boot demo-ready)
- Rate confirmation PDFs; carrier counter-offers
- Org-wide audit log viewer for admins (per-load trail is done)
- Proper pytest suite (current coverage is the scripted end-to-end run)

## Deployment

`render.yaml` included — deploys as a single Render web service (free tier).

## AI Usage

Built with AI assistance under human direction — the workflow, prompt strategy, and review process are documented in [AI_USAGE.md](AI_USAGE.md).
