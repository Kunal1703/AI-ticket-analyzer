# 19 — Routing Rules & SLA Policies

Implemented in **M3.4a**. Files: `app/routing/{__init__,base,engine,routes}.py`,
`app/db/routing_store.py`, `RoutingRule`/`SlaPolicy` ORM + `tickets.assignee`/
`tickets.sla_due_at` + migration `0009_routing_sla`, deps in `app/dependencies.py`,
models in `app/models.py`. **Deferred to M3.4b:** custom per-tenant categories
(which need dynamic per-org structured-output schema generation).

## What M3.4a does

Per-tenant helpdesk configuration + an explicit "route this ticket" action:

- **Routing rules** — when a ticket's analysis matches `conditions` (a subset of
  `{category, priority}`), apply `actions` (`{assignee, tags}`). Rules are evaluated
  in ascending `position`; the **first active match wins**.
- **SLA policies** — a `resolution_minutes` deadline per `priority`.
- **`POST /v1/tickets/{id}/route`** — evaluate the org's rules + SLA against the
  ticket's **latest analysis** and **persist** `assignee` + `sla_due_at` on the
  ticket. Surfaced on `GET /v1/tickets` and `GET /v1/tickets/{id}`.

## Pure engine (`app/routing/engine.py`)

`RoutingEngine.evaluate(category, priority, rules) -> RoutingDecision(assignee,
tags, matched_rule_id)` and `SlaCalculator.due_at(priority, policies, base_time) ->
datetime | None`. Both take already-loaded ORM rows and do **no I/O**, so they are
trivially unit-testable. Conditions/actions are stored as JSONB and matched by
string equality against the stored analysis `category`/`priority` values (which are
the enum *value* strings) — keeping matching **forward-compatible** with the custom
taxonomies coming in M3.4b (no coupling to the fixed enums).

## Endpoints (`app/routing/routes.py`, prefix `/v1`)

| Method | Path | Guard | Purpose |
|---|---|---|---|
| POST | `/orgs/{org_id}/routing-rules` | owner/admin | Create a rule |
| GET | `/orgs/{org_id}/routing-rules` | membership | List rules (by `position`) |
| DELETE | `/orgs/{org_id}/routing-rules/{id}` | owner/admin | Delete (204/404) |
| POST | `/orgs/{org_id}/sla-policies` | owner/admin | Create a policy |
| GET | `/orgs/{org_id}/sla-policies` | membership | List policies |
| DELETE | `/orgs/{org_id}/sla-policies/{id}` | owner/admin | Delete (204/404) |
| POST | `/tickets/{ticket_id}/route` | tenant context | Apply rules + SLA; persist on ticket (404 no ticket, 409 no analysis) |

Config CRUD mirrors API-key/webhook management (owner/admin to modify, membership to
list). The stores (`RoutingRuleStore`/`SlaPolicyStore` + `SqlAlchemy…` impls) are
**request-scoped** (session-backed) — routing happens in a request, not the
background.

## Why an explicit route endpoint (not auto-on-analyze)

Routing is applied by an explicit `POST …/route` rather than inside `run_analysis`,
so the shared analyze pipeline stays untouched (no per-analysis routing-config
query, no coupling). The ticket loaded via the request-scoped `TicketStore` is
mutated (`assignee`/`sla_due_at`) and the request session commits — no extra store
method needed.

## What must NEVER change

- Routing is applied explicitly (`POST …/route`); `run_analysis` is not coupled to
  routing config.
- The engine stays **pure** (no I/O); matching is string-equality on stored analysis
  values (forward-compatible with custom categories).
- Tenant-scoped throughout (config + `/route` filter by `organization_id`); config
  changes are owner/admin.

## Deferred / next

- **M3.4b** custom per-tenant categories: a per-org category taxonomy + **dynamic
  structured-output schema generation** threaded through the provider + analyze path
  (the fixed `TicketCategory` enum becomes per-tenant).
- Rule action richness (accumulate tags across matches, priority override), SLA
  breach tracking / escalation, and auto-routing on analysis (opt-in) if desired.
