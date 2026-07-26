# 18 — Async Jobs, Batch Analyze & Outbound Webhooks

Implemented in **M3.3a** (async batch analyze + job status) and **M3.3b** (outbound
webhooks). Files: `app/jobs/*`, `app/db/batch_job_store.py`, `app/webhooks/*`,
`app/db/{webhook_store,webhook_delivery_store}.py`, `BatchJob`/`Webhook`/
`WebhookDelivery` ORM + migrations `0007_batch_jobs`/`0008_webhooks`, deps in
`app/dependencies.py`, models in `app/models.py`. **Deferred (need live infra):**
the real arq/Redis worker + per-tenant concurrency caps + durable scheduled retries
(M3.3c).

## What M3.3a does

- `POST /v1/analyze/batch` submits 1–50 ticket texts for **asynchronous** analysis
  (metered + quota-gated exactly like `/v1/analyze`), creates a `batch_jobs` row, and
  returns it immediately with **202** (status `queued`).
- The batch is processed in the background; each item reuses the shared
  `run_analysis` (cache → provider → metrics → persist → meter), so results become
  ordinary tickets/analyses under the org — **queryable via `/v1/tickets`** — and no
  analyze logic is duplicated.
- `GET /v1/analyze/batch/{job_id}` polls status (`queued`/`running`/`completed`/
  `completed_with_errors`/`failed`) + `total`/`completed`/`failed` counts.

## The `JobRunner` abstraction (the "task queue" seam)

```python
class JobRunner(Protocol):
    async def run(self, job: Callable[[], Coroutine[Any, Any, None]]) -> None: ...
    async def aclose(self) -> None: ...
```

- **`BackgroundJobRunner`** (default) runs the job in-process via an `asyncio`
  background task — **no external infrastructure**, graceful degradation like the
  in-memory cache. It keeps strong task references and `aclose()` drains in-flight
  jobs at shutdown (wired into `lifespan`).
- A **Redis-backed worker (arq/Celery)** is the registry-ready production backend:
  add a `JobRunner` impl and an `_RUNNERS` entry; select via `settings.job_queue`. It
  was **not** wired here because this environment has no Redis/worker to verify it.

Built once in `create_app` → `app.state.job_runner`; `build_job_runner(settings)`
selects the backend (unknown name → `ValueError`).

## `BatchService`

`submit(organization_id, texts, analyze_one)` creates the job, schedules
`_process` on the runner, and returns the queued job. `_process` marks the job
`running`, calls the caller-supplied `analyze_one(text)` per item (counting
successes/failures — a single bad item doesn't abort the batch), then records
`completed`/`completed_with_errors`; if the whole job crashes it records `failed`.
The `analyze_one` closure (built in the route) captures the app's provider/cache/
sessionmaker and calls `run_analysis`.

## Why `BatchJobStore` wraps a *sessionmaker* (not a request session)

The job row created during the request must be **durable and visible** to the
background task that processes it afterwards. So `SqlAlchemyBatchJobStore` opens a
fresh, self-committing session per op (`create`/`get`/`update`) via the sessionmaker
— a deliberate departure from the request-scoped stores. `get_batch_job_store`
returns it (**503** without a DB, since jobs need persistence). Schema: see
[03_database.md](03_database.md) (`batch_jobs`, tenant-scoped NOT NULL FK, indexed by
org, `created_at`/`updated_at`).

## Observability

`batch_jobs_total{status}` counts jobs reaching a final status.

## Testing (fully offline)

Route/service tests use a fake `BatchJobStore` + an **inline** `JobRunner` (runs the
job synchronously) so a submitted batch completes deterministically — no background
timing. The `BackgroundJobRunner` is tested directly (schedule + drain); the
SQLAlchemy store via a fake sessionmaker + a `skipif(not DATABASE_URL)` round-trip.
Migration `0007` verified offline (`--sql`).

## What must NEVER change

- Batch reuses `run_analysis` (no second analyze pipeline); items persist as normal
  tickets/analyses and are metered like `/v1/analyze`.
- Submission is metered + quota-gated (`require_quota`); tenant-scoped throughout
  (jobs and results filter by `organization_id`; cross-org poll → 404).
- The default runner needs **no infra** (in-process); the external worker stays
  behind the `JobRunner` port + registry.
- `BatchJobStore` stays sessionmaker-backed so jobs are visible across request and
  background task.

## M3.3b — Outbound webhooks

The **outbound mirror** of the M2.5b Stripe inbound webhooks: here the app is the
signer and the tenant verifies.

### Registration (`app/webhooks/routes.py`)

| Method | Path | Guard | Purpose |
|---|---|---|---|
| POST | `/v1/orgs/{org_id}/webhooks` | owner/admin | Register an endpoint; **secret returned once** |
| GET | `/v1/orgs/{org_id}/webhooks` | membership | List (no secret) |
| DELETE | `/v1/orgs/{org_id}/webhooks/{id}` | owner/admin | Delete (204; 404 if not in org) |

A webhook has a `url`, a per-webhook signing `secret`, an `event_types`
subscription list, and `active`. Management mirrors API keys (owner/admin to
create/delete). **The secret is *retained*** (we sign each delivery with it), unlike
API keys which we hash — so it must be **encrypted at rest** in production.

### Signing (`app/webhooks/signing.py`)

HMAC-SHA256 over `{timestamp}.{body}` → `X-Webhook-Signature: t=<unix>,v1=<hex>` —
the exact scheme we verify inbound for Stripe. Receivers recompute + compare in
constant time and reject stale timestamps.

### Dispatch (`app/webhooks/dispatcher.py`)

`HttpWebhookDispatcher.dispatch(org_id, event_type, payload)` finds the org's
**active** webhooks subscribed to `event_type`, creates a `webhook_deliveries`
record, and POSTs the signed JSON via an **injected httpx client** with **bounded
inline retries** (short exponential backoff, `webhook_max_attempts`), recording the
final `delivered`/`failed` outcome (+ `attempts`/`response_status`/`error`). It is
**best-effort and never raises** — a down webhook must not fail the batch (a
per-webhook crash is isolated; a lookup failure is swallowed). `NoOpWebhookDispatcher`
is returned when there's no database (`get_webhook_dispatcher`), so the batch path
works without webhooks configured. The stores are **sessionmaker-backed** (the
dispatcher runs in the background).

### Trigger

`BatchService.submit` takes an optional `on_complete(job_id, status, completed,
failed)` hook, called after the job reaches a final state. The batch route wires it
to `dispatcher.dispatch(..., event_type="batch.completed", ...)`. The dispatcher is
generic, so adding events (e.g. `analysis.created`) is trivial later.

### Observability

`webhook_deliveries_total{status}` counts delivery outcomes.

### What must NEVER change (webhooks)

- Deliveries are **signed** (HMAC over `{timestamp}.{body}`) and **best-effort** — a
  failed/slow webhook never breaks the batch/analysis path.
- The signing secret is retained + returned once; management is owner/admin.
- Dispatch stays sessionmaker-backed (runs in the background) behind the
  `WebhookDispatcher` port.

## Deferred / next (M3.3c and beyond)

- Real arq/Redis worker `JobRunner` + per-tenant concurrency caps.
- **Durable, scheduled retries** (persist `next_attempt_at`; a worker sweeps and
  re-attempts) — M3.3b does bounded *inline* retries only.
- More event types (e.g. `analysis.created`), a deliveries-list endpoint, webhook
  enable/disable + secret rotation, batch result listing + cancellation, and a
  "batch of N would exceed quota" pre-check.
