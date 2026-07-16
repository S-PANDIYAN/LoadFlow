# AI Usage — How This Project Was Built

Tool used: **Claude Code** (Anthropic), driven from the terminal against this repo.

The important part: **AI did not design this system on its own.** I directed the architecture, made the decisions, and reviewed the output at every step. AI was the implementation accelerator, not the architect of record. This document describes the actual division of work.

---

## Division of Work

### What I (the developer) did

- **Read and decomposed the problem statement myself** and decided what the judges are really testing: dynamic RBAC (not hardcoded roles), server-side enforcement, and the compliance-blocking rule.
- **Designed the system before any code was written.** I wrote a detailed Phase 1 specification by hand: the exact database models (Organization, User, Permission, Role, RolePermission, UserRole), the JWT claim structure, the `Permission -> Role -> User` design rule, the bootstrap flow (org registration creates the first admin; staff are invite-only), and the API surface. The AI received this as its input, not the raw problem statement alone.
- **Set the constraints**: FastAPI + SQLAlchemy + SQLite stack, 5-hour budget, deploy target (Render), what to cut (Alembic, email invites, file storage) and why.
- **Made the calls on design questions** the AI surfaced: admins implicitly hold all permissions within their org; permissions are read from the DB per request (so role edits apply instantly); out-of-scope objects return 404 instead of 403.
- **Reviewed every generated file** before accepting it, and demanded a rating/critique of my phase plan before implementation started.
- **Owned all git commits** — the AI wrote code; I reviewed and committed it phase by phase.

### What AI did

- Turned my written specification into code: models, Pydantic schemas, routers, the permission-check dependency, seed data, and the dashboard UI.
- Flagged gaps in my spec during its review (missing staff-creation endpoint, undefined admin-bypass rule, carrier accept/decline permissions missing from the catalog) — which I then approved as amendments.
- Wrote and ran an end-to-end verification script (`verify_spec.py`, 38 checks) proving each requirement works against the live server, including the "not hardcoded" proof: create a new org and a new role at runtime, edit the role's permissions, and observe an existing session gain them instantly.

---

## Prompt Style

The pattern that worked, in order:

1. **Context first, code later.** The first prompt was the full problem statement with an explicit instruction to *not* write code — only to analyze what's critical, what to skip, and where the traps are (rate-version immutability, the bootstrap question, org scoping being independent of permissions).
2. **Human-authored spec as the prompt.** For the core phase, I wrote the design document myself (models, field lists, API list, business rules, incorrect-vs-correct code examples like `if user.role == "dispatcher"` vs `if "load.assign_carrier" in user.permissions`) and asked the AI to critique and rate it before implementing.
3. **Phase-by-phase, with a checkpoint each phase.** Scaffold -> RBAC -> domain logic -> UI -> deploy. After each phase, I got a report of what was done and committed it before continuing.
4. **Verify, don't trust.** After implementation, the instruction was to re-read the original problem statement and prove every requirement live, not from memory. That produced the 38-check verification run.

## Review Habits

- Every denial path was tested by direct API call (curl / requests), not by checking that a button was hidden.
- The demo database was reset after verification so seeded test data would not leak into the demo.
- The smoke test exercised the failure paths first (403 without permission, 409 blocked by compliance, 409 illegal transition) because those are what the spec actually grades.

## What I'd Flag as AI Limitations Encountered

- The AI initially proposed a Next.js stack; I overrode it to FastAPI to match my design and comfort zone. It adapted.
- Generated code needed a DB reset step after tests polluted seed data — caught in review, not by the AI initially.
- Windows shell quirks (heredoc quoting) forced switching the test harness from inline shell scripts to a committed Python file — which turned out to be better for the repo anyway.
