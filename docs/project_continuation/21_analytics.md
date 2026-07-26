# 21 — Analytics API

Implemented in **M4.1** (the first Phase 4 milestone). Files:
`app/analytics/{__init__,base,service,routes}.py`, `app/db/analytics_store.py`,
analytics deps in `app/dependencies.py`, models in `app/models.py`. **Read-only, no
migration** (aggregates the existing `tickets`/`analyses`).

## What M4.1 does

Tenant-scoped aggregate metrics over the org's tickets/analyses, with an optional
date window:

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/analytics/summary` | Totals + category/priority distributions |
| GET | `/v1/analytics/timeseries` | Daily counts of `tickets` or `analyses` |

- **`/summary`** → `{start, end, total_tickets, total_analyses, by_category,
  by_priority}`. Distributions are `GROUP BY` over `analyses.category`/`priority`.
- **`/timeseries?metric=tickets|analyses`** → `{metric, start, end, points:
  [{date, count}]}` — daily counts (`GROUP BY date(created_at)`).
- **Window:** optional `start`/`end` **date** query params; `end` is **inclusive**
  of its whole calendar day (converted to a half-open `[start, 00:00 of end+1)` UTC
  datetime window). Both optional.

## Layering

- **`AnalyticsStore` port** (`app/analytics/base.py`) + `SqlAlchemyAnalyticsStore`
  (`app/db/analytics_store.py`): all aggregation runs **in SQL** (`func.count`,
  `GROUP BY`, `cast(created_at, Date)`), tenant-scoped by `organization_id` and
  window-bounded — request-scoped (session-backed) since analytics is a read path.
- **`AnalyticsService`** (`app/analytics/service.py`): owns the calendar-date →
  datetime **window conversion** and assembles the store's aggregates into the
  response models. Thin coordinator, unit-tested with a fake store (asserting the
  window math + assembly) — no HTTP concerns.
- **Routes** guard with `get_tenant_context` (API key or JWT, any org member — no
  new scope, consistent with the tickets read API).

## Design notes

- **Distributions are analysis-level** (`GROUP BY analyses.category/priority`) —
  well-defined and simple. A "current classification per ticket" view (latest
  analysis per ticket, e.g. Postgres `DISTINCT ON`) is a straightforward refinement.
- **OLAP/materialized views deferred:** M4.1 reads the OLTP tables directly, which
  is fine at current scale. A separate OLAP store / materialized views (per
  [14_remaining_roadmap.md](14_remaining_roadmap.md)) is a later scale concern.

## What must NEVER change

- Analytics is **read-only** and **tenant-scoped** (every query filters by
  `organization_id`); no writes, no new tables.
- Aggregation stays in SQL behind the `AnalyticsStore` port; the service stays
  HTTP-free (window math + assembly only).

## Deferred / next

- Latest-analysis-per-ticket distributions; SLA-breach / resolution-time metrics;
  usage/cost analytics; assignee/routing breakdowns.
- OLAP store / materialized views for scale; cache the aggregates.
- **Frontend consumer:** the M4.4 analytics dashboard (`web/`) reads `/summary` +
  `/timeseries` — stat tiles, distributions, and a daily timeseries chart. See
  [22_frontend.md](22_frontend.md).
