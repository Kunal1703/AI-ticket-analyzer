# 25 — Agentic Resolution Actions (M5.3)

The final **Phase 5 (AI moat)** milestone, and the last of the original roadmap.
It adds a **human-in-the-loop agentic layer**: a suggester (rule-based or AI)
**proposes** resolution actions for a ticket, a privileged human **approves or
rejects** them, approved actions are **executed** through action handlers, and
**every** transition is written to an append-only, tenant-scoped **audit log**.
Nothing executes automatically; destructive actions always require approval.

Files: `app/actions/*` (state machine, ports, suggester, handlers, service,
routes, LLM suggester), `app/db/action_store.py`, `resolution_actions` +
`audit_logs` ORM + migration `0013`, `app/prompts.py` (action prompt), the
additive `AnalysisProvider.suggest_actions`, and DI/router wiring. Design
decision: **D34**.

## Why

M5.1 made prompts measurable; M5.2 grounded analyses in the KB; M5.3 closes the
loop by turning an analysis into **proposed, approved, audited actions** — the
"auto-resolve" surface — while keeping a human firmly in control. The safety
model (approval-gated, no auto-destructive execution, full audit trail) is the
milestone's substance; the suggester's intelligence source is pluggable behind a
port.

## The state machine (`app/actions/state.py`)

Unlike ticket status (M3.6, deliberately unrestricted), resolution actions
enforce a **real state machine**, because the safety story depends on it:

```
proposed ─► approved ─► executed
   │            └─────► failed
   └──────► rejected
(rejected / executed / failed are terminal)
```

`ensure_transition(current, target)` raises `InvalidActionTransition` (→ HTTP
409) on any disallowed move. The critical invariant falls straight out of it:
**a `proposed` action cannot be executed** — execution requires prior approval.

## Data model (migration `0013`)

Two tenant-scoped tables (see [03_database.md](03_database.md)):

- **`resolution_actions`** — `organization_id` (NOT NULL), `ticket_id`,
  `analysis_id` (nullable, SET NULL), `action_type`, `params` (JSONB),
  `rationale`, `status` (state-machine value), `is_destructive`, `suggested_by`,
  `approved_by`, `result` (JSONB), timestamps.
- **`audit_logs`** — append-only: `organization_id` (NOT NULL), `actor_type`
  (`user`/`system`/`ai`), `actor_id`, `action` (e.g. `action.approved`),
  `resource_type`/`resource_id`, `detail` (JSONB), `created_at`; composite
  `(organization_id, created_at)` index for listing.

## Ports (`app/actions/base.py`)

Everything is a `Protocol`, so the service/routes test against fakes with no
DB/LLM: `ActionSuggester` (proposes), `ActionHandler` (executes one type),
`ActionStore` + `AuditStore` (persistence). Which action types are
**destructive** is defined **once** here (`DESTRUCTIVE_ACTIONS` /
`is_destructive`), so the suggester and handlers can never disagree.

## Suggesters (`app/actions/suggester.py`, `llm_suggester.py`)

- **`RuleBasedActionSuggester`** (default, `actor_type=system`) — deterministic,
  offline, no LLM: maps a ticket's latest analysis to proposals (summary note +
  set-status; escalate on High/Critical; a reply draft on Billing/Refund). The
  safe default, mirroring the keyless embedding/cache defaults.
- **`LlmActionSuggester`** (`ACTION_SUGGESTER=llm`, `actor_type=ai`) — reuses the
  existing `AnalysisProvider` via an **additive** `suggest_actions` structured-
  output method (returns a `ResolutionPlan`), so it is provider-agnostic and
  translates failures through the same `Provider*` hierarchy. No parallel LLM
  path. `build_action_suggester(settings, provider=…)` selects between them
  (unknown → rule, fail-safe).

`AnalysisProvider.suggest_actions` has a **default that raises `ProviderError`**
(only `OpenAIProvider` overrides it), so adding the capability didn't break any
existing provider/fake — the additive, backward-compatible pattern.

## Handlers (`app/actions/handlers.py`)

Each handler executes one action type behind the `ActionHandler` port:

- **Internal, non-destructive:** `set_status` / `assign` mutate the ticket via the
  request session; `add_note` records the note (captured in the audit trail).
- **Outward, destructive:** `send_reply` / `escalate` **dispatch a signed webhook**
  (reusing M3.3b) for the tenant's integration to carry out the real send/escalation
  — the app never performs an irreversible external operation itself, and these
  only ever run *after* approval.

## The service (`app/actions/service.py`)

`ActionService` coordinates the ports and enforces the invariants in one place:
`suggest` (persist proposals + audit), `approve`/`reject` (state-machine guarded
+ audit), `execute` (guarded so **only an approved action runs**, then dispatches
to the handler → executed/failed, audited). It mutates the loaded ORM rows so the
request session commits, exactly like the ticket PATCH/route endpoints.

## Endpoints (`app/actions/routes.py`, prefix `/v1`)

| Method | Path | Guard | Purpose |
|---|---|---|---|
| POST | `/tickets/{id}/actions/suggest` | member | Propose actions (nothing runs) |
| GET | `/tickets/{id}/actions` | member | List a ticket's actions |
| POST | `/tickets/{id}/actions/{aid}/approve` | owner/admin **user** | proposed → approved |
| POST | `/tickets/{id}/actions/{aid}/reject` | owner/admin **user** | proposed → rejected |
| POST | `/tickets/{id}/actions/{aid}/execute` | owner/admin **user** | run handler (409 if not approved) |
| GET | `/orgs/{org_id}/audit-logs` | owner/admin | tenant audit trail |

`require_approver` gates approve/reject/execute: the principal must be a **user**
(an API key can't approve — machines don't approve their own actions) who is an
**owner/admin** of the org; its `user_id` is recorded as the approver. Everything
is tenant-scoped (cross-org → 404).

## Observability

Actions are observable through the **audit log** (a richer, queryable record than
a counter), so M5.3 adds no new Prometheus metric — the audit trail is the
action-observability surface.

## Testing (all offline)

- `tests/test_actions_state.py` — the state machine + schema registration.
- `tests/test_actions.py` — rule-based suggester, handlers (each type +
  destructive flags + webhook dispatch), the service (suggest/approve/reject/
  execute + audit; **execute-before-approval blocked**; handler-not-ok/exception →
  failed), and the SQLAlchemy stores (mocked session).
- `tests/test_actions_routes.py` — the full suggest → approve → execute flow over
  HTTP, audit listing, tenant 404s, the 409 safety path, and `require_approver`
  authorization (api-key rejected, non-privileged rejected, owner allowed).
- `tests/test_actions_llm.py` — `suggest_actions` default-raise + OpenAI
  structured path (mocked), `LlmActionSuggester` mapping, suggester selection.
- Migration `0013` verified offline (`alembic upgrade head --sql`).

## What must NEVER change (D34)

- **Human-approved by default:** nothing executes without an explicit approve →
  execute by a privileged human. The state machine makes executing an unapproved
  action impossible (409).
- **No automatic destructive execution:** destructive/outward action types
  (`DESTRUCTIVE_ACTIONS`, one source of truth) are always approval-gated, and
  their handlers hand the real effect to the tenant via a webhook.
- **Everything is audited:** every transition writes an append-only, tenant-scoped
  audit-log entry with the actor.
- **Tenant-scoped throughout:** actions + audit filter by `organization_id`;
  cross-org access is 404; approval requires a member (never an API key).
- **Provider-agnostic + additive:** `suggest_actions` is additive (default-raise;
  the `analyze`/`TicketAnalysis` contract + `Provider*` translation unchanged);
  the suggester is behind a port with an **offline rule-based default**.

## Deferred / next (Phase 5 complete)

Phase 5 (the AI moat) is complete: M5.1 (prompt versioning + eval), M5.2 (RAG),
M5.3 (agentic actions). Natural follow-ups: more action types (tags, refunds via
a real integration), auto-approval of safe internal actions when explicitly
opted-in, a frontend action/approval UI + audit viewer, richer audit querying
(by resource/actor/date), and grounding suggestions in RAG context on the suggest
path. Broader deferred items remain in [14_remaining_roadmap.md](14_remaining_roadmap.md)
(M3.3c worker, M3.4b custom categories, M2.5c outbound Stripe, RBAC deepening,
refresh-token rotation, the `models.py` split).
