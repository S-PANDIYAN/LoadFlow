# LoadFlow — Freight Brokerage Operations Suite

A hackathon-built operations platform for a freight brokerage connecting **Brokers**, **Carriers**, and **Shippers** — with dynamic RBAC, a full load lifecycle state machine, compliance auto-flagging, and versioned rate confirmations.

## Stack & Why

**FastAPI + SQLAlchemy + SQLite + JWT, server-rendered UI (Jinja2 + vanilla JS)** — a single deployable unit with a zero-setup DB and no separate frontend build: maximum must-have velocity in a 5-hour window.

## Run Locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# open http://localhost:8000
```

Tables are created and demo data seeded automatically on first boot. API docs at `/docs`.

## Demo Accounts (password: `demo1234`)

| Account | Email | What it demos |
|---|---|---|
| Broker Admin | `broker.admin@demo.io` | Role builder UI, staff invites, full board |
| Broker Dispatcher | `dispatcher@demo.io` | Post/assign/rate — but **cannot** override compliance (403) |
| Broker Ops Lead | `opslead@demo.io` | Has `load.override_compliance_flag` |
| Carrier Admin | `carrier.admin@demo.io` | Carrier-side roles/staff |
| Driver | `driver@demo.io` | Status updates + POD only |
| Carrier Dispatch | `carrier.dispatch@demo.io` | Accept/decline only |
| Shipper | `shipper@demo.io` | Sees only own shipments |

**Suggested demo flow:** log in as dispatcher → open flagged load `LF-00004` (RustyWheels Transport has expired insurance) → try to progress it → blocked with 409 → try override → 403 (permission denied, logged) → log in as Ops Lead → override with justification → progress works → check the audit trail on the load.

## How the Spec Is Covered

- **RBAC, not hardcoded**: `Permission` catalog is seeded data; `Role` rows are created at runtime by org admins via the UI; authorization checks permission **codes** only (`require_permission("load.assign_carrier")`) — role names appear nowhere in business logic.
- **Bootstrap**: registering a Broker/Carrier org creates the org + its first Admin in one step. Staff accounts can only be created by a `staff.manage` holder — never self-registered.
- **Org scoping**: every query filters by the authenticated user's `organization_id` (from JWT). Carrier staff see only loads assigned to their org; brokers only their own board.
- **Object scoping**: shippers see only `shipper_id == user.id` loads. Out-of-scope objects return 404 (existence not leaked).
- **API-layer enforcement**: all rules live in FastAPI dependencies — the UI only hides buttons as a courtesy. `curl` any endpoint with a low-privilege token to verify (403 + console log).
- **State machine**: `Posted → Carrier Assigned → Rate Confirmed → Dispatched → In Transit → Delivered → POD Verified → Invoiced/Closed`, transitions validated server-side, each recorded in `load_events` with actor + timestamp.
- **Compliance**: expired insurance / non-active authority / unapproved equipment or commodity auto-flags the load at assignment **and is re-checked at every transition**; progression past Carrier Assigned is blocked (409) unless a `load.override_compliance_flag` holder overrides with a justification (audit-logged).
- **Rate confirmation versioning**: versions are immutable rows; re-negotiation creates v2, v3…; the load pins the version actually confirmed (`rate_confirmation_id`) forever.
- **Denied attempts logged**: permission/scope denials log to console with user, needed permission, and path.

## Assumptions

- **Brokers maintain carrier compliance records** (broker is liable, brokers vet carriers). Carrier admins can view their own record.
- Staff "invites" are direct account creation with a temp password — email delivery skipped for hackathon scope.
- POD is a recorded confirmation (note/reference), not file storage.
- Compliance equipment/commodity lists are comma-separated text; empty list = no restriction.
- One compliance record per carrier org (current snapshot, not history).
- Org admins implicitly hold all catalog permissions **within their own org** (standard SaaS owner semantics); org scoping still applies to them.

## Incomplete / With More Time

- Alembic migrations (used `create_all` for velocity; fine for SQLite demo)
- Real file upload + viewer for POD; email invites; password reset
- Persistent disk on Render (free tier resets SQLite on redeploy — seed makes every boot demo-ready)
- Rate-confirmation PDF generation; carrier-side counter-offers
- Cross-org audit log viewer page for admins (per-load audit trail is done)
- Tests as a proper pytest suite (currently a scripted end-to-end smoke run)

## AI Tool Usage

Built with **Claude Code** (Anthropic). Workflow: pasted the full problem statement first and had the model produce a phase plan + risk analysis before any code; then phase-by-phase generation (models → RBAC layer → domain logic → UI), reviewing each file and running an end-to-end smoke test of the RBAC/compliance/scoping rules before moving on. Commits map to phases.

## Deployment

`render.yaml` included — deploy as a Render web service (free tier). SQLite lives on ephemeral disk; the idempotent seed keeps the demo working after restarts.
