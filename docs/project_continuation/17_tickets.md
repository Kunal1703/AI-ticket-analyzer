# 17 — Tickets: Read / History, Feedback, Re-analyze

Implemented in **M3.1** (read/history) and **M3.2** (feedback capture + re-analyze).
Files: `app/tickets/{__init__,base,routes}.py`, `app/db/{ticket_store,feedback_store}.py`,
ticket/feedback deps in `app/dependencies.py`, models in `app/models.py`, `Feedback`
ORM + migration `0006_feedback`.

## Why read-only

Tickets are created **implicitly** by the analyze path (`get_or_create_ticket`,
deduped per-org by `text_hash`); analyses are **append-only/versioned** under a
ticket. Since M2.4 the tenant-scoped `/v1/analyze` populates `organization_id`, so
ticket history is now queryable per tenant. M3.1 therefore exposes **listing +
retrieval**, not a parallel write path (that would duplicate `/v1/analyze`'s
business logic). Explicit create/update/delete were intentionally deferred (see
[14_remaining_roadmap.md](14_remaining_roadmap.md)).

## Endpoints (prefix `/v1`, `app/tickets/routes.py`)

| Method | Path | Guard | Purpose |
|---|---|---|---|
| GET | `/tickets` | `get_tenant_context` | Paginated list of the org's tickets (+ latest analysis) |
| GET | `/tickets/{ticket_id}` | `get_tenant_context` | One ticket + its full versioned analysis history (404 if not in the org) |

- **List** query params: `limit` (1–100, default 20), `offset` (≥0), optional
  `category`/`priority` (validated against the `TicketCategory`/`TicketPriority`
  enums). Ordered most-recent-first. Response: `PaginatedTickets` =
  `{items: [TicketSummary], total, limit, offset}`; each `TicketSummary` carries the
  latest analysis's category/priority/summary + `analyses_count`.
- **Detail**: `TicketDetail` = ticket metadata + `raw_text` + `analyses`
  (`AnalysisRead[]`, oldest-first — the version history).

## Authorization (tenant scoping)

Both endpoints depend on **`get_tenant_context`** (resolves from `X-API-Key` **or**
a user JWT), so any authenticated principal in the org can read its tickets — **no
new scope** is required (existing `analyze`-scoped API keys keep working; chosen for
back-compat). Every query is scoped to `context.organization_id`; **legacy org-less
tickets are never exposed**, and a ticket in another org returns **404** (tenant
isolation, tested).

## Port + store (`TicketStore`)

Read-only persistence port (`app/tickets/base.py`, mirroring `OrgStore`/`UsageStore`)
so routes are testable against an in-memory fake with no DB:

- `list_for_org(org_id, *, limit, offset, category?, priority?)`
- `count_for_org(org_id, *, category?, priority?)`
- `get_for_org(org_id, ticket_id)`

`SqlAlchemyTicketStore` (`app/db/ticket_store.py`) implements them. Category/priority
live on the versioned analyses, so filtering uses an **EXISTS** over the `analyses`
relationship (`Ticket.analyses.any(...)`) — "tickets that have an analysis matching".
Analyses are eager-loaded (`selectinload`) so the list/detail builders can pick the
latest / render history without N+1 queries. `get_ticket_store` is the DI provider.

## Testing

Route tests override `get_tenant_context` (fixed org) + `get_ticket_store` (a
`FakeTicketStore`) — no DB/auth stack — covering pagination, category filter, latest-
analysis surfacing, ordering, 404 (unknown + cross-org). The SQLAlchemy store is
unit-tested with a mocked session; a `skipif(not DATABASE_URL)` round-trip exercises
real queries. No migration (reuses `tickets`/`analyses`).

## What must NEVER change

- Tenant-scoped: every query filters by `organization_id`; legacy org-less rows stay
  hidden; cross-org access is 404.
- Routes depend on the `TicketStore`/`FeedbackStore` ports, not the ORM/session directly.
- Ticket creation stays on the analyze path (no parallel ticket-create endpoint).
- Re-analyze stays metered + quota-gated (via `require_quota`) and **reuses**
  `run_analysis` (`bypass_cache=True`) — it appends a versioned analysis, never
  overwrites; no duplicated analyze logic.
- Feedback targets a specific analysis and is additive (never mutates the analysis).

## M3.2 — Feedback capture + re-analyze

### Endpoints (extend `app/tickets/routes.py`)

| Method | Path | Guard | Purpose |
|---|---|---|---|
| POST | `/tickets/{id}/reanalyze` | `require_quota` | Re-run the AI on the ticket's text; append a new versioned analysis |
| POST | `/tickets/{id}/feedback` | `get_tenant_context` | Record feedback on an analysis (201) |
| GET | `/tickets/{id}/feedback` | `get_tenant_context` | List a ticket's feedback |

### Re-analyze

`POST /tickets/{id}/reanalyze` is **metered + quota-gated exactly like
`/v1/analyze`** (depends on `require_quota` → auth + `analyze` scope for API keys +
the monthly cap → **402**). It loads the ticket (404 if not in the org), then reuses
the shared `run_analysis` with a new **`bypass_cache=True`** flag: the cache read is
skipped (forcing a fresh provider call), a **new versioned analysis is appended**
under the existing ticket (`get_or_create_ticket` dedupes by `text_hash`+org, so no
duplicate ticket), usage is metered, and the cache is refreshed. No business logic is
duplicated — re-analyze is `run_analysis` with the cache read turned off. `Provider*`
errors flow through the global handler as for `/v1/analyze`.

### Feedback (`feedback` table)

Feedback targets a **specific analysis version** (the training signal). The request
carries a `rating` (`positive`/`negative`), optional `corrected_category`/
`corrected_priority` (the human's correction) + `comment`, and an optional
`analysis_id` — **when omitted it attaches to the ticket's latest analysis**. The
route validates the analysis belongs to the ticket (400 malformed id, 404 not part of
the ticket / no analysis to rate). Any org member/tenant may submit (no new scope,
like the reads). `FeedbackStore` (`create`/`list_for_ticket`) +
`SqlAlchemyFeedbackStore`; `create` flushes then `refresh`es to load the
server-generated `created_at` before the request-scoped session commits. Schema: see
[03_database.md](03_database.md) (`feedback`, tenant-scoped NOT NULL FKs, indexed by
org + ticket).

## M3.6 — Ticket lifecycle & workspace APIs

Added because M4.3 (agent workspace) exposed real backend gaps during frontend
integration. Deliberately small: lifecycle status + a partial-update endpoint +
richer list querying + a `ticket_id` in the analyze responses. Files:
`Ticket.status` column + migration `0010_ticket_status`, `app/models.py`
(`TicketStatus`/`TicketSort`/`AnalyzeResponse`/`UpdateTicketRequest`),
`app/tickets/routes.py`, `app/db/ticket_store.py` + `app/tickets/base.py`,
`app/services/{analyze,analysis_service}.py`, `app/db/repositories.py`.

### Ticket lifecycle (`tickets.status`)

New `TicketStatus` enum — `open` / `in_progress` / `pending` / `resolved` /
`closed` — stored as a **value string** on `tickets.status` (`String(32)`, NOT
NULL, `server_default 'open'`), the same convention as `role`/`category`/
`priority` (not a PG enum). New tickets default to `open`. **Transitions are
unrestricted** (any state → any state, including reopen) — no state machine, by
design (kept small; the UX layer can order transitions later).

### `PATCH /v1/tickets/{id}` — status + manual assignee

| Method | Path | Guard | Purpose |
|---|---|---|---|
| PATCH | `/tickets/{id}` | `get_tenant_context` | Update `status` and/or `assignee` |

Guarded by `get_tenant_context` (**any org member** — agents triage tickets;
consistent with `POST /route` and feedback). The body (`UpdateTicketRequest`) has
optional `status` + `assignee`; only fields **present in the request** are applied
(via Pydantic `model_fields_set`), so `{"assignee": null}` **clears** the assignee
while omitting it leaves it unchanged. At least one field is required (else 422);
an unknown enum value is 422; a ticket outside the org is 404. The route mutates
the loaded ORM object and the **request-scoped session commits** — exactly like
`POST /route`; the read port stays read-only. Returns the fresh `TicketDetail`
(now including `status`). `TicketSummary` also carries `status`.

### `ticket_id` in the analyze responses (deep-linking)

`POST /v1/analyze` and `POST /v1/tickets/{id}/reanalyze` now return an
**`AnalyzeResponse`** = `TicketAnalysis` **+ `ticket_id`** (additive; the legacy
public `/analyze` still returns a plain `TicketAnalysis`, and the email channel is
unchanged). Plumbing: `persist_analysis` returns the persisted ticket id;
`run_analysis` returns an `AnalyzeOutcome(analysis, ticket_id)`. On a **cache hit**
(nothing persisted) the tenant path resolves the id best-effort via
`resolve_ticket_id` (own session, swallows errors) — **skipped for the legacy
org-less path**, so its cache-hit path stays DB-free. `ticket_id` is `null` only
when no database is configured. `reanalyze` already holds the ticket, so it returns
`str(ticket.id)` directly.

### Richer `GET /v1/tickets` querying

Added optional filters `status`, `assignee`, `source`, `search` (case-insensitive
substring on `raw_text` via `ILIKE`, LIKE-wildcards escaped) and a `sort`
(`created_at` / `-created_at`, default `-created_at` = newest first, the prior
behavior). All additive/optional → backward compatible; `count_for_org` applies the
same filters for correct totals. (Cursor pagination intentionally **not** added.)

### What must NEVER change (M3.6)

- Status/`ticket_id`/filters are all **additive**: legacy `/analyze` keeps its
  plain `TicketAnalysis`; existing `/v1/tickets` calls keep working.
- PATCH stays **any-member** and mutates via the request-scoped session (read port
  stays read-only); `ticket_id` resolution stays **best-effort** and skips the
  legacy path.
- `status` stays a value string (no PG enum), consistent with the other enums.

## Known follow-ups

- **`app/db/models.py` is now at 18 models** — well past the ~8 split threshold.
  Splitting it into an `app/db/models/` package is an overdue standalone chore
  (imports must keep working via the package `__init__`).
- Ticket delete (owner/admin) for data-cleanup/GDPR; bulk actions; cursor
  pagination; a status state-machine / SLA-breach state (all intentionally out of
  M3.6 scope).
- **✅ Frontend now consumes** this surface — the M4.3 workspace wires ticket
  status controls, PATCH (status/assign), `ticket_id` deep-links, and the new
  filters (see the "M3.6 frontend integration" section in [22_frontend.md](22_frontend.md)).
- Config note: `app/api/v1/` may become the home for versioned routers as they
  multiply ([14_remaining_roadmap.md](14_remaining_roadmap.md)); today they live
  beside their domain (`app/tickets/routes.py`).
