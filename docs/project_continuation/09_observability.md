# 09 — Observability

Implemented in **M1.4** (structured logs, request IDs, Prometheus metrics, token usage) and **M1.5** (`/ready`). Files: `app/core/logging.py`, `app/core/middleware.py`, `app/observability/metrics.py`, `app/readiness.py`, plus routes in `app/main.py`.

## Structured logging (`app/core/logging.py`)

- `JsonFormatter` emits single‑line JSON: `timestamp`, `level`, `logger`, `message`, `request_id`, and `exception` (on error). Non‑serializable values are stringified (`default=str`).
- `LOG_FORMAT` selects `"json"` (default) or `"text"` (human‑readable for local dev). Both include `request_id`.
- `configure_logging(settings)` installs a single `StreamHandler` with the chosen formatter + a `RequestIdFilter`, using `basicConfig(..., force=True)` so repeated app builds (tests) reconfigure cleanly.
- `resolve_log_level(debug, log_level)` — `DEBUG` forces DEBUG, else the configured level (used by both `configure_logging` and tests).

**Why JSON by default:** production observability wants structured logs; this is the milestone's headline deliverable. Local devs set `LOG_FORMAT=text`.

## Request‑ID correlation (`app/core/middleware.py` + a contextvar)

- `request_id_var: ContextVar[str | None]` lives in `app/core/logging.py`.
- `RequestContextMiddleware` reads an inbound `X-Request-ID` (or generates `uuid4().hex`), stores it on `request.state.request_id`, **sets the contextvar** (reset in `finally`), and echoes `X-Request-ID` on the response.
- `RequestIdFilter` stamps every log record with the contextvar's value (`-` if absent).

**Why `RequestContextMiddleware` is registered outermost:** so the contextvar is set before the timing middleware's access‑log line runs (that line is correlated too). This ordering is deliberate (fixed in M1.5) — the middleware registration order in `create_app` encodes it.

**Known gap:** an unhandled 500 is handled by Starlette's `ServerErrorMiddleware` *outside* the user middleware, after the contextvar is reset, so that specific log line shows `request_id="-"`. The response envelope still carries the correct id. Minor; documented.

## Metrics (`app/observability/metrics.py`, `GET /metrics`)

Prometheus (`prometheus-client`), module‑level singletons against the default registry:
- `http_requests_total{method, path, status}` and `http_request_duration_seconds{method, path}` — recorded in `request_timing_middleware`, labelled by the **matched route template** (`request.scope["route"].path`, else `"other"`) to bound cardinality.
- `ticket_analyses_total{provider, outcome}` — `outcome` ∈ {success, error}.
- `cache_requests_total{result}` — {hit, miss}.
- `llm_tokens_total{provider, type}` — {prompt, completion}, incremented by token counts.
- **Billing (M2.5):** `usage_events_total{event_type}`, `quota_denied_total{event_type}`, `billing_webhooks_total{provider, outcome}`.
- **Async jobs / webhooks / (M3.3):** `batch_jobs_total{status}`, `webhook_deliveries_total{status}`.
- **RAG (M5.2):** `rag_retrievals_total{outcome}` — knowledge‑base retrievals on the analyze path (`grounded`/`empty`/`error`).
- `render()` returns `(generate_latest(), CONTENT_TYPE_LATEST)`; `/metrics` serves it.

Helpers (`record_http_request`, `record_analysis`, `record_cache`, `record_tokens`, `record_usage_event`, `record_quota_denied`, `record_billing_webhook`, `record_batch_job`, `record_webhook_delivery`) keep call sites decoupled from the metric objects. **11 metric families total.**

## Token usage capture

`OpenAIProvider._extract_usage` reads `completion.usage` best‑effort into `TokenUsage(prompt, completion, total)`; malformed usage → `None` (never raises). Usage flows through `AnalysisResult.usage` to:
1. **metrics** (`llm_tokens_total`), and
2. **persistence** (`analyses.token_usage` JSONB, via `persist_analysis`).

**Why a result wrapper:** it kept the `/analyze` response and cached value as a plain `TicketAnalysis` while surfacing usage — the API contract didn't change.

## Health vs Readiness

- `GET /health` — **liveness**, no dependency checks (see [02_request_flow.md](02_request_flow.md)).
- `GET /ready` — **readiness** via `app/readiness.py::check_readiness(sessionmaker, cache, provider)`: `SELECT 1` for the DB (if configured), `cache.ping()`, and provider = "ok if configured" (**no LLM call** — a third‑party outage must not flap the pod). 200 ready / 503 not‑ready with per‑component statuses. `ReadyResponse` in `app/models.py`.

## Current limitations

- **No distributed tracing** (OpenTelemetry) yet.
- **No USD cost** — only raw token counts are captured (cost needs a per‑model pricing map).
- **Default Prometheus registry** — fine for a single process; multi‑process uvicorn workers need Prometheus multiprocess mode.
- **Access‑log line lacks request_id on unhandled 500** (above).

## Future

- OpenTelemetry traces spanning route → provider → DB.
- USD cost derived from token counts + a pricing table (small follow‑up now that tokens are stored).
- Grafana dashboards from the exported metrics; **per‑tenant metric labels are still deliberately avoided** (org id would be unbounded cardinality) — tenant analytics is served by the Analytics API (M4.1, [21_analytics.md](21_analytics.md)) instead.
- `request_id` in the access‑log even on 500s (would require an ASGI‑level id middleware).

## What must NEVER change

- `X-Request-ID` correlation (header + contextvar + log filter).
- `/health` staying dependency‑free; `/ready` not calling the LLM.
- Metric label cardinality discipline (route template, not raw path; bounded `provider`/`outcome`/`result`/`type`).
