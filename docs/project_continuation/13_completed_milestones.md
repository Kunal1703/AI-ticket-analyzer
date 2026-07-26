# 13 — Completed Milestones (full history)

Every milestone shipped so far, in order, with purpose / implementation / files / verification / state / lessons. This is the complete phase list.

> **Phases:** Phase 0 = hardening (M0.1–M0.5). Between M0.5 and M1.0 an engineering review was done. Phase 1 = production infra (M1.0–M1.5). A **provider‑agnostic refactor** happened between M1.2 and M1.3. Phase 2 = tenancy/auth (M2.1–M2.3 done; M2.4+ pending). Plus two housekeeping commits (Docker networking, `.env.example` port).

---

## PHASE 0 — Hardening

### M0.1 — Tooling & CI baseline
- **Purpose:** enforce quality automatically before touching behavior.
- **Implementation:** `pyproject.toml` (ruff/mypy/coverage config), `requirements-dev.txt`, `.github/workflows/ci.yml` (ruff, ruff format --check, mypy, pytest --cov on 3.12 with a dummy `OPENAI_API_KEY`). Conformed existing code to the formatter.
- **Verification:** 34 tests green; CI green.
- **State/Lessons:** established the green‑gate discipline used by every later milestone.

### M0.2 — `.dockerignore` + Docker correctness
- **Purpose:** stop shipping `venv/`, `.git/`, tests, `.env` into the image; fix a misleading "build stage" comment.
- **Files:** `.dockerignore`, `Dockerfile`.
- **Verification:** build context shrank from ~158 MB to <1 MB; secrets excluded (Docker daemon was down, so verified by measurement + logic).

### M0.3 — Wire dead config / fix TTL discrepancy
- **Purpose:** three settings (`cache_ttl_seconds`, `openai_max_retries`, `debug`) existed but did nothing; README claimed a TTL that wasn't implemented.
- **Implementation:** `TTLCache` (real per‑entry TTL, injectable clock) replacing the TTL‑less dict; retry count read from settings via `AsyncRetrying`; `debug` → forces DEBUG logging (`resolve_log_level`); `Field(ge=1)` guard on retries (0 would never call the LLM).
- **Files:** `app/main.py`, `app/openai_client.py`, `app/config.py`, docs.
- **Lessons:** fixed a genuine correctness bug (docs↔behavior mismatch).

### M0.4 — CORS, security headers, error envelope
- **Purpose:** fix `allow_origins=["*"] + credentials` (invalid/insecure); standardize errors.
- **Implementation:** config‑driven CORS; `app/core/middleware.py` (`RequestContextMiddleware`, `SecurityHeadersMiddleware`); `app/core/errors.py` (envelope + handlers). **Bug caught:** deriving `error.code` from `HTTPStatus.phrase` is version‑dependent (3.13 renamed 422) → switched to a stable code map.
- **Files:** `app/core/*`, `app/main.py`, `app/config.py`.
- **Verification:** 62 tests, 87% coverage.

### M0.5 — Provider abstraction seam + closed test gaps
- **Purpose:** decouple business logic from the OpenAI SDK; test the untested error/retry paths.
- **Implementation:** `app/ai/` package — `AnalysisProvider` (ABC), `Provider*` exceptions, `factory` registry, `OpenAIProvider` translating OpenAI errors; `app/openai_client.py` became a shim. Comprehensive provider tests.
- **Files:** `app/ai/*`, `app/openai_client.py`, tests.
- **State:** the template abstraction for the whole project.

### (Between M0.5 and M1.0) — Engineering review
Produced the Phase‑0 review whose top finding (import‑time global singletons, missing DI/app‑factory) became **M1.0**.

---

## PHASE 1 — Production infrastructure

### M1.0 — DI / application‑factory seam
- **Purpose:** remove import‑time globals; enable per‑request DI and clean shutdown.
- **Implementation:** `create_app(settings)` + `app = create_app()`; `app.state` resources; `lifespan` closes provider/cache/engine; `Cache` protocol extracted to `app/cache.py`; `resolve_log_level`/`configure_logging` → `app/core/logging.py`; removed the global `get_provider` singleton (footgun); `app/dependencies.py` with `get_*`. Endpoints moved to an `APIRouter`. Fixed stale OpenAPI `responses`.
- **Files:** `app/main.py` (factory), `app/cache.py`, `app/core/logging.py`, `app/dependencies.py`.
- **Verification:** 93 tests, 97.5%.

### M1.1 — Postgres + Alembic foundation
- **Purpose:** persistence layer present + migratable; app still runs without a DB.
- **Implementation:** `app/db/{base,models,session}.py` (ORM `Ticket`/`Analysis`, engine/sessionmaker factories, naming convention); Alembic (`alembic.ini`, `env.py`, `0001_initial`); `docker-compose` Postgres; `psycopg` v3 driver; optional `DATABASE_URL`.
- **Deviation:** ORM lives in `app/db/models.py` (not `app/models/`) because `app/models.py` holds the Pydantic schemas.
- **Verification:** 97 tests; migration verified offline (`--sql`).

### M1.2 — Persist analyses (best‑effort, flagged)
- **Purpose:** persist ticket + versioned analysis on the analyze path without ever breaking it.
- **Implementation:** `app/db/repositories.py` (get‑or‑create ticket, add analysis), `app/services/analysis_service.py` (best‑effort `persist_analysis`), `get_db_sessionmaker` dependency; wired into `create_app`/`lifespan`/route.
- **Verification:** 117 tests; failure‑injection test proves 200 on DB failure.

### (Between M1.2 and M1.3) — Provider‑agnostic refactor
- **Purpose:** make the app truly provider‑agnostic (OpenAI = one backend).
- **Implementation:** `ProviderConfig`; generic `LLM_*` settings with `OPENAI_*` env aliases (`AliasChoices`); `api_key` optional; `OpenAIProvider` accepts `base_url`; `ProviderSpec` registry with `openai`/`groq`/`together`/`openrouter`/`ollama`/`openai-compatible`; route uses `provider.model`. **Bug caught:** `OPENAI_*` kwarg aliases break when the env var is present (`extra_forbidden`) → tests switched to canonical `llm_*` names; verified with and without `OPENAI_API_KEY`.
- **Files:** `app/ai/config.py`, `app/ai/factory.py`, `app/ai/openai_provider.py`, `app/config.py`.

### M1.3 — Redis cache behind the `Cache` protocol
- **Purpose:** shared, multi‑instance cache with graceful fallback.
- **Implementation:** `app/cache/` package (`base`/`memory`/`redis`/`factory`); **async** `Cache` protocol; `RedisCache` (best‑effort, JSON‑serialized, native TTL); `build_cache`; `redis` dependency; compose `cache` service.
- **Verification:** 149 tests; RedisCache tested via mocked async client (best‑effort, serialization, TTL, aclose).

### M1.4 — Observability (structured logs, request IDs, metrics, token usage)
- **Purpose:** production observability + cost basis.
- **Implementation:** JSON logs + `request_id` contextvar + filter; `app/observability/metrics.py` + `/metrics`; HTTP metrics in the timing middleware (route‑template labels); `AnalysisResult`/`TokenUsage` (provider returns result+usage); `analyses.token_usage` column + migration `0002`; token/analysis/cache metrics. Also reordered middleware so the access log carries `request_id`.
- **Verification:** 162 tests, 98%.

### M1.5 — `/ready` readiness + graceful shutdown
- **Purpose:** separate liveness/readiness; verify clean shutdown.
- **Implementation:** `app/readiness.py` (`check_readiness`), `GET /ready` (DB `SELECT 1` + `cache.ping()` + provider‑configured; **no LLM call**); `Cache.ping()`; `ReadyResponse`. Shutdown (provider/cache/engine close) was already in `lifespan`; added tests.
- **Verification:** 184 tests.

---

## PHASE 2 — Multi‑tenancy, auth, billing (in progress)

### M2.1 — Tenancy & user/org schema (data layer only)
- **Purpose:** the multi‑tenant data model, unenforced.
- **Implementation:** ORM `Organization`/`User`/`Membership`/`ApiKey`; nullable `organization_id` FK on `tickets`/`analyses`; migration `0003_tenancy` (unique slug/email/key_hash, unique (org,user), cascades, indexes). No routes, no enforcement.
- **Verification:** 187 tests; migration chain verified offline.

### M2.2 — Authentication (provider‑agnostic) + local email/password
- **Purpose:** signup/login/JWT/refresh, designed so OAuth/OIDC/SSO can be added later.
- **Implementation:** `app/auth/` (`base` interface + `AuthenticatedIdentity` + `UserStore` port + errors; `password` Argon2; `tokens` JWT `TokenService`; `local_provider`; `factory`; `service` `AuthService`; `routes` `/v1/auth/*`); `SqlAlchemyUserStore`; DI (`get_token_service`, `get_user_store`, `get_auth_service`, `get_current_user`); deps `argon2-cffi`, `PyJWT`, `email-validator`. **Bug caught:** `get_current_user` must catch `TokenError` (not an `AuthError`).
- **Verification:** 257 tests, 98.4%; live smoke signup→me→refresh.

### M2.3 — API keys + per‑tenant request context
- **Purpose:** hashed/scoped/revocable API keys; resolve `organization_id` into a request `TenantContext` from key OR JWT; isolation.
- **Implementation:** `app/tenancy/` (`api_key` gen/hash; `base` `TenantContext` + `OrgStore`/`ApiKeyStore` ports + errors; `service` `OrganizationService`/`ApiKeyService`; `routes` `/v1/orgs`, `/v1/orgs/{id}/api-keys`, `/v1/tenant`); `SqlAlchemyOrgStore`/`SqlAlchemyApiKeyStore`; DI (`get_org_store`, `get_api_key_store`, `get_org_service`, `get_api_key_service`, `require_org_membership`, `get_tenant_context`, `get_optional_token_service`). Minimal `POST /v1/orgs` (+ owner membership) as the prerequisite for keys.
- **Verification:** 290 tests, 96.7%; cross‑tenant 403, revoked‑key 401, tenant resolution both ways.

### M2.4 — Versioned `/v1/analyze` + tenant‑scoped persistence + RBAC
- **Purpose:** an authenticated, tenant‑scoped analyze endpoint alongside the legacy one; enforce roles + API‑key scopes; persist per‑org.
- **Implementation:**
  - **Shared orchestration** `app/services/analyze.py::run_analysis` (cache → provider → metrics → best‑effort persist). Both legacy `/analyze` (org=None) and new `/v1/analyze` call it → no divergence.
  - **`POST /v1/analyze`** (in `app/main.py::router`) depends on `require_scope("analyze")` → `TenantContext`; persists under `context.organization_id`. Cache key namespaced by org in `run_analysis`; content hash still used for DB dedupe.
  - **Global provider exception handler** `app/core/errors.py::provider_exception_handler` registered for `ProviderError` — centralizes `Provider*`→HTTP mapping; both analyze routes dropped their try/except (identical behavior preserved).
  - **RBAC:** `Role` enum (`app/tenancy/base.py`); `require_role(*roles)` + `require_scope(*scopes)` dependency factories (`app/dependencies.py`). API‑key create/revoke now require `owner`/`admin`.
  - **Tenant‑scoped persistence:** `organization_id` threaded through `persist_analysis` → `get_or_create_ticket` (dedupe scoped per‑org) → `add_analysis` (inherits ticket's org).
- **Files:** `app/services/analyze.py` (new); edits to `app/main.py`, `app/core/errors.py`, `app/dependencies.py`, `app/tenancy/base.py`, `app/tenancy/routes.py`, `app/db/repositories.py`, `app/services/analysis_service.py`; tests `tests/test_analyze_v1.py`.
- **Verification:** 310 tests, 96.9%; `/v1/analyze` via API key + JWT, scope‑denied 403, non‑owner RBAC 403, unauth 401, **legacy `/analyze` unchanged**, org‑namespaced cache.
- **Lessons:** the global exception handler is the clean way to DRY error mapping across endpoints; `Depends(factory(...))` trips ruff B008 — use a module‑level dependency singleton.

### M2.5a — Usage metering + plan quota enforcement (billing groundwork)
- **Purpose:** meter analyses per org and enforce a per‑plan monthly cap on `/v1/analyze`, without external dependencies — the metering half of M2.5 (Stripe = M2.5b).
- **Implementation:**
  - **New `app/billing/` domain** (mirrors `app/tenancy/`): `plans.py` (a **configurable** `Plan` registry with **placeholder** limits, overridable via `Settings.plan_monthly_analysis_limits`; `get_plan` fails safe to the default); `base.py` (`UsageStore` port + `BillingError → QuotaExceededError`); `service.py` (`BillingService.check_quota` over calendar‑month UTC usage); `metering.py` (`record_analysis_usage` — best‑effort, own session, like `persist_analysis`).
  - **Data:** `UsageEvent` ORM (org‑scoped **NOT NULL**, composite `(organization_id, created_at)` index); migration `0004_usage_events`; `SqlAlchemyUsageStore` (`count_since` sums `quantity`). `OrgStore.get(org_id)` added for the plan lookup.
  - **Enforcement:** `require_quota` dependency (layered on `require_scope("analyze")`) → **402** (`payment_required`) before the LLM call; `/v1/analyze` depends on it. `record_analysis_usage` wired into `run_analysis` (tenant path only, cache‑miss only). Legacy `/analyze` unchanged.
  - **Config/obs:** `plan_monthly_analysis_limits` setting; `usage_events_total` + `quota_denied_total` metrics; 402 slug added to the stable error‑code map; plan registry built on `app.state.plans`.
- **Files:** `app/billing/*` (new), `app/db/usage_store.py` (new), `alembic/versions/0004_usage_events.py` (new); edits to `app/db/models.py`, `app/tenancy/base.py`, `app/db/org_store.py`, `app/config.py`, `app/observability/metrics.py`, `app/core/errors.py`, `app/dependencies.py`, `app/services/analyze.py`, `app/main.py`; tests `tests/test_billing.py` (new) + additions to `tests/test_analyze_v1.py`/`tests/test_tenancy_service.py`. Docs: [16_billing.md](16_billing.md).
- **Verification:** 343 tests, 8 skipped, green with **and** without `OPENAI_API_KEY`; migration `0004` verified offline (`--sql`). Over‑quota → 402, metering best‑effort/no‑ops without a DB, unlimited plan bypasses the store, legacy `/analyze` never metered/limited.
- **Lessons:** two session strategies again — enforcement is a request‑scoped read (fail the request), metering is a best‑effort own‑session write (never break the response). Gate before the provider call to protect the LLM budget.

### M2.5b — Stripe billing provider + idempotent webhooks + plan sync + usage endpoint
- **Purpose:** ingest signature‑verified Stripe webhooks idempotently and sync `Organization.plan`; expose per‑org usage — keeping the Stripe SDK behind a provider port.
- **Implementation:**
  - **Provider‑agnostic billing abstraction** (`app/billing/provider.py`, mirrors `AuthProvider`): `BillingProvider` ABC + neutral `BillingEvent` + `_PROVIDERS` registry + `build_billing_provider`. `StripeBillingProvider` (`app/billing/stripe_provider.py`) verifies via `stripe.Webhook.construct_event` and maps events → plan; **`stripe` imported lazily** so the app runs without the dependency; SDK/signature/payload failures → `BillingProviderError` (→ 400).
  - **Idempotent ingestion** `POST /v1/billing/webhook` (`app/billing/routes.py`): `WebhookService.handle` → parse → dedupe (`processed_webhook_events` unique `event_id`) → plan sync (org from `metadata.organization_id`, plan from configurable `stripe_price_plan_map`; sets `stripe_customer_id`). 503 when unconfigured.
  - **Usage endpoint** `GET /v1/orgs/{org_id}/usage` (org‑scoped) via `BillingService.current_usage`/`plan_for` (the M2.5a deferral).
  - **Data:** `ProcessedWebhookEvent` ORM + `Organization.stripe_customer_id`; migration `0005_billing_webhooks`; `SqlAlchemyWebhookEventStore` + `WebhookEventStore` port; `OrganizationService.get_org`/`OrgStore.get`.
  - **Config/obs:** `stripe==11.4.1` dependency; `billing_provider`/`stripe_api_key`/`stripe_webhook_secret`/`stripe_price_plan_map` settings; `billing_webhooks_total` metric; provider built on `app.state.billing_provider`.
- **Files:** `app/billing/{provider,stripe_provider,routes}.py` (new), `app/db/webhook_event_store.py` (new), `alembic/versions/0005_billing_webhooks.py` (new); edits to `app/billing/{__init__,base,service}.py`, `app/db/models.py`, `app/tenancy/{base,service}.py`, `app/db/org_store.py`, `app/config.py`, `app/observability/metrics.py`, `app/models.py`, `app/dependencies.py`, `app/main.py`, `requirements.txt`; tests `tests/test_billing_webhooks.py` (new) + usage tests in `tests/test_analyze_v1.py`. Docs: [16_billing.md](16_billing.md).
- **Verification:** 384 tests, 8 skipped, 96.3%; green with **and** without `OPENAI_API_KEY`; `mypy .` clean; migration `0005` verified offline. Signature‑error → 400, duplicate → 200 no‑op, plan sync, 503 unconfigured, usage endpoint, missing‑SDK translation.
- **Lessons:** with no live Stripe/SDK, the provider is testable by injecting a fake `stripe` module into `sys.modules`; the route/idempotency/plan‑sync logic via a `FakeBillingProvider`. Lazy‑import the optional SDK so the app never hard‑depends on it.

---

## PHASE 3 — Helpdesk features (in progress)

### M3.1 — Tickets read / history API
- **Purpose:** tenant‑scoped, read‑only listing + retrieval of tickets and their versioned analyses (`/v1/tickets`) — the first Phase 3 milestone. Tickets are created on the analyze path, so no write endpoints (creation would duplicate `/v1/analyze`).
- **Implementation:**
  - **Read port** `TicketStore` (`app/tickets/base.py`) + `SqlAlchemyTicketStore` (`app/db/ticket_store.py`): `list_for_org`/`count_for_org`/`get_for_org`, all scoped by `organization_id`; category/priority filter via EXISTS over the `analyses` relationship; analyses eager‑loaded (`selectinload`).
  - **Routes** (`app/tickets/routes.py`, prefix `/v1`): `GET /tickets` (paginate `limit`/`offset`, filter `category`/`priority`; items carry the latest analysis) and `GET /tickets/{id}` (full version history, 404 if not in org). Guarded by `get_tenant_context` (API key or JWT) — **no new scope** (back‑compat); legacy org‑less tickets never exposed; cross‑org → 404.
  - **Models:** `TicketSummary`/`TicketDetail`/`AnalysisRead`/`PaginatedTickets`; `get_ticket_store` dependency; router included in `create_app`. **No migration** (reuses `tickets`/`analyses`).
  - **Lint:** added `fastapi.Query` to ruff's `extend-immutable-calls` (Query in defaults, same as `Depends`).
- **Files:** `app/tickets/*` (new), `app/db/ticket_store.py` (new); edits to `app/models.py`, `app/dependencies.py`, `app/main.py`, `pyproject.toml`; tests `tests/test_tickets.py` (new). Docs: [17_tickets.md](17_tickets.md).
- **Verification:** 404 tests, 10 skipped, 96.3%; green with **and** without `OPENAI_API_KEY`; `mypy .` clean. Pagination, category filter, latest‑analysis surfacing, history ordering, unknown/cross‑org 404, store mocked‑session + skipif round‑trip.
- **Lessons:** a read‑only `Protocol` store keeps the new routes DB‑free in tests (override `get_ticket_store` + `get_tenant_context`); filter on versioned children via the relationship's `.any()` EXISTS.

### M3.2 — Feedback capture + re‑analyze
- **Purpose:** capture human feedback on analyses (training signal) and re‑run analysis on an existing ticket, appending a new versioned analysis.
- **Implementation:**
  - **Re‑analyze** `POST /v1/tickets/{id}/reanalyze`: **metered + quota‑gated via `require_quota`** (auth + `analyze` scope + `402` cap), loads the ticket (404 if not in org), then **reuses `run_analysis`** with a new **`bypass_cache=True`** flag — forces a fresh provider call, appends a new versioned analysis under the existing ticket (`get_or_create_ticket` dedupes by `text_hash`+org), meters, refreshes cache. No duplicated analyze logic.
  - **Feedback** `POST`/`GET /v1/tickets/{id}/feedback`: `Feedback` ORM (tenant‑scoped NOT NULL FKs to orgs/tickets/analyses) + migration `0006_feedback`; `FeedbackStore` port + `SqlAlchemyFeedbackStore` (`create` flush+refresh for `created_at`; `list_for_ticket`); `get_feedback_store` dep. POST targets a specific analysis — defaults to the ticket's latest, optional `analysis_id` (400 malformed / 404 not part of ticket / 404 no analysis). Any org member/tenant (no new scope).
  - **Models:** `FeedbackRating`/`CreateFeedbackRequest`/`FeedbackResponse`; `bypass_cache` param on `run_analysis` (cache read skipped, still SET).
- **Files:** `app/db/feedback_store.py` + migration `0006` (new); edits to `app/db/models.py` (`Feedback`), `app/tickets/{base,routes,__init__}.py`, `app/services/analyze.py`, `app/models.py`, `app/dependencies.py`; tests `tests/test_feedback.py` (new). Docs: [17_tickets.md](17_tickets.md).
- **Verification:** 432 tests, 10 skipped, 96.4%; green with **and** without `OPENAI_API_KEY`; `mypy .` clean; migration `0006` verified offline. Re‑analyze returns a fresh (cache‑bypassed) analysis + 404; feedback default‑latest/explicit‑id/400/404/422, list, store mocked‑session, schema.
- **Lessons:** re‑analyze is just `run_analysis(bypass_cache=True)` — threading one flag avoided a second analyze path; a fresh row needs `flush()`+`refresh()` to surface the server‑default `created_at` before the request commits. **`models.py` hit 9 models — the package split is now a recommended standalone chore.**

### M3.3a — Async batch analyze + job‑queue abstraction + job status
- **Purpose:** submit many tickets for asynchronous analysis with progress tracking, needing no external infra (arq/Redis deferred).
- **Implementation:**
  - **`JobRunner` port + registry** (`app/jobs/{base,runner}.py`): `BackgroundJobRunner` (in‑process asyncio task; `aclose` drains at shutdown) as default; `build_job_runner(settings)` selects the backend; arq/Celery is a registry‑ready future entry. Built on `app.state.job_runner`, disposed in `lifespan`.
  - **`BatchService`** (`app/jobs/service.py`): create `batch_jobs` row → schedule `_process` on the runner → per item call a caller‑supplied `analyze_one` (which wraps `run_analysis`), counting successes/failures → record final status (`completed`/`completed_with_errors`/`failed`).
  - **Data:** `BatchJob` ORM + migration `0007_batch_jobs`; **`BatchJobStore` wraps a sessionmaker** (own self‑committing sessions) so a job is visible to its background task; `get_batch_job_store` (503 without a DB).
  - **Routes** (`app/jobs/routes.py`): `POST /v1/analyze/batch` (1–50 texts, `require_quota` → **202** + job) and `GET /v1/analyze/batch/{job_id}` (poll status, 404 cross‑org). Each item reuses `run_analysis` → results are normal tickets/analyses.
  - **Config/obs:** `job_queue` setting; `batch_jobs_total{status}` metric; `BatchRequest`/`BatchJobResponse` models.
- **Files:** `app/jobs/*` + `app/db/batch_job_store.py` + migration `0007` (new); edits to `app/db/models.py` (`BatchJob`), `app/config.py`, `app/models.py`, `app/observability/metrics.py`, `app/dependencies.py`, `app/main.py`; tests `tests/test_batch.py` (new). Docs: [18_jobs.md](18_jobs.md).
- **Verification:** 462 tests, 12 skipped, 96%; green with **and** without `OPENAI_API_KEY`; `mypy .` clean; migration `0007` verified offline. Submit→poll, partial‑failure counts, job‑crash→failed, empty/too‑many/blank‑item 422, cross‑org 404, runner registry, store mocked‑sessionmaker + skipif round‑trip.
- **Lessons:** batch is `run_analysis` under a runner — no second pipeline; test async jobs with an **inline** runner for determinism; a background‑job store must be **sessionmaker‑backed** (not request‑scoped) so the job row is visible to the background task.

### M3.3b — Outbound webhooks
- **Purpose:** notify tenants of async events (`batch.completed`) via signed, retried HTTP callbacks — the outbound mirror of the M2.5b Stripe inbound webhooks.
- **Implementation:**
  - **Data:** `Webhook` (url, retained signing `secret`, `event_types`, `active`) + `WebhookDelivery` (audit/log) ORM + migration `0008_webhooks`; sessionmaker‑backed `SqlAlchemyWebhookStore`/`SqlAlchemyWebhookDeliveryStore` (+ ports) so they work in the background dispatch task.
  - **Signing** (`app/webhooks/signing.py`): HMAC‑SHA256 over `{timestamp}.{body}` → `X-Webhook-Signature: t=…,v1=…` (mirrors the Stripe scheme we verify inbound).
  - **Dispatch** (`app/webhooks/dispatcher.py`): `HttpWebhookDispatcher` finds active subscribed webhooks, records a delivery, POSTs signed JSON via an **injected httpx client** with **bounded inline retries** (backoff), records `delivered`/`failed` — **best‑effort, never raises** (a down webhook can't fail the batch). `NoOpWebhookDispatcher` when no DB.
  - **Trigger:** `BatchService.submit(on_complete=…)` hook → the batch route dispatches `batch.completed` (job id, status, counts).
  - **Registration** (`app/webhooks/routes.py`): `POST`/`GET`/`DELETE /v1/orgs/{org_id}/webhooks` (owner/admin to create/delete, membership to list; secret returned once).
  - **Wiring/obs:** shared `httpx.AsyncClient` on `app.state` (closed in `lifespan`); `get_webhook_store`/`get_webhook_dispatcher` deps; `webhook_max_attempts`/`webhook_timeout_seconds` settings; `webhook_deliveries_total{status}` metric; `Create/WebhookResponse`/`WebhookCreatedResponse` models.
- **Files:** `app/webhooks/*` + `app/db/{webhook_store,webhook_delivery_store}.py` + migration `0008` (new); edits to `app/db/models.py` (`Webhook`/`WebhookDelivery`), `app/config.py`, `app/models.py`, `app/observability/metrics.py`, `app/dependencies.py`, `app/jobs/{service,routes}.py`, `app/main.py`; tests `tests/test_webhooks.py` (new). Docs: [18_jobs.md](18_jobs.md).
- **Verification:** 503 tests, 14 skipped, 95.6%; green with **and** without `OPENAI_API_KEY`; `mypy .` clean; migration `0008` verified offline. Signing determinism, deliver/retry‑then‑succeed/exhaust‑and‑fail, unsubscribed skip, lookup‑error + per‑delivery‑crash isolation, registration CRUD (secret‑once, invalid‑url 422, delete 404), batch→dispatch wiring, store mocked‑session + skipif round‑trip.
- **Lessons:** outbound delivery is the exact inverse of the Stripe inbound verification (we sign, they verify); a background dispatcher must be **best‑effort** (swallow all errors) and **sessionmaker‑backed**; inject the httpx client so delivery is fully offline‑testable.

### M3.4a — Routing rules + SLA policies
- **Purpose:** per‑tenant helpdesk config (route/assign tickets + SLA deadlines), applied by an explicit endpoint — custom categories deferred to M3.4b.
- **Implementation:**
  - **Pure engine** (`app/routing/engine.py`): `RoutingEngine.evaluate` (first active rule whose `{category?, priority?}` conditions all match → `{assignee, tags}`, ordered by `position`) + `SlaCalculator.due_at` (`ticket.created_at + resolution_minutes` for the matching priority). No I/O; matching is string‑equality on stored analysis values (forward‑compatible with M3.4b custom taxonomies).
  - **Data:** `RoutingRule` + `SlaPolicy` ORM + nullable `tickets.assignee`/`tickets.sla_due_at` + migration `0009_routing_sla`; request‑scoped `SqlAlchemyRoutingRuleStore`/`SqlAlchemySlaPolicyStore` + ports.
  - **Routes** (`app/routing/routes.py`): config CRUD `POST`/`GET`/`DELETE /v1/orgs/{org_id}/routing-rules` + `…/sla-policies` (owner/admin modify, membership list); **`POST /v1/tickets/{id}/route`** evaluates rules + SLA against the latest analysis and **persists** `assignee`/`sla_due_at` on the ticket (404 no ticket, 409 no analysis). `GET /v1/tickets[/{id}]` now surface those fields.
  - **Deps/models:** `get_routing_rule_store`/`get_sla_policy_store`; `Create/RoutingRuleResponse`, `Create/SlaPolicyResponse`, `RoutingResult`, `RoutingConditions`/`RoutingActions` models; router included in `create_app`.
- **Files:** `app/routing/*` + `app/db/routing_store.py` + migration `0009` (new); edits to `app/db/models.py` (`RoutingRule`/`SlaPolicy` + ticket columns), `app/models.py`, `app/dependencies.py`, `app/tickets/routes.py` (surface fields), `app/main.py`; tests `tests/test_routing.py` (new). Docs: [19_routing.md](19_routing.md).
- **Verification:** 538 tests, 14 skipped, 95.6%; green with **and** without `OPENAI_API_KEY`; `mypy .` clean; migration `0009` verified offline. Engine first‑match/no‑match/catch‑all, SLA due/no‑match, config CRUD (create/list/delete/404, bad minutes 422), `/route` persists + 404 + 409, store mocked‑session.
- **Lessons:** a **pure engine** + **explicit apply endpoint** keeps `run_analysis` untouched and the logic trivially testable; string‑based condition matching keeps routing forward‑compatible with per‑tenant custom categories (M3.4b).

### M3.5 — Inbound channels (email‑to‑ticket + CSV import)
- **Purpose:** ingest tickets from non‑API sources into the existing pipeline, tagged by `source`.
- **Implementation:**
  - **Source threading:** `source` param added to `run_analysis` → `persist_analysis` → `get_or_create_ticket` (default `"api"`); email/CSV tickets tagged `email`/`csv`.
  - **Email** `POST /v1/channels/email` (authenticated tenant, metered + quota‑gated): `{from_address, subject, body}` → ticket text → `run_analysis(source="email")` → returns the analysis.
  - **CSV import** `POST /v1/channels/import` (tenant, metered): CSV as the **raw request body** (no `python-multipart`), parsed by `app/channels/csv_parser.py` (picks a `text`/`ticket`/`body`/… column or the single column; 400 on malformed/empty/oversized, cap 50) → submitted as an async batch (`source="csv"`), reusing M3.3a.
  - **DRY:** `app/jobs/submit.py::submit_analyze_batch` (+ `batch_job_response`) factors the batch route's `analyze_one` + `on_complete` dispatch; reused by the batch route and CSV import (parameterized by `source`).
  - **Models/wiring:** `EmailInboundRequest`; `app/channels/` router included in `create_app`. **No migration.**
- **Files:** `app/channels/*` + `app/jobs/submit.py` (new); edits to `app/services/analyze.py`/`analysis_service.py` (source), `app/jobs/routes.py` (use helper), `app/models.py`, `app/main.py`; tests `tests/test_channels.py` (new). Docs: [20_channels.md](20_channels.md).
- **Verification:** 557 tests, 14 skipped, 95.7%; green with **and** without `OPENAI_API_KEY`; `mypy .` clean. CSV parser (column pick/blank/no‑column/empty/no‑rows/too‑many/non‑UTF‑8), source threading at persist, email 200 + 422, import 202 + per‑row analysis + 400.
- **Lessons:** channels are thin adapters — reuse `run_analysis`/batch and thread one `source` param; keep CSV dependency‑light (raw body + stdlib `csv`); factor batch orchestration once (`submit_analyze_batch`) so both entry points stay in sync.

---

## PHASE 4 — Analytics & frontend (in progress)

### M4.1 — Analytics API
- **Purpose:** tenant‑scoped aggregate metrics over tickets/analyses (`/v1/analytics/*`) — the first Phase 4 milestone. Read‑only; **no migration**.
- **Implementation:**
  - **`AnalyticsStore` port** + `SqlAlchemyAnalyticsStore`: all aggregation in SQL (`func.count`, `GROUP BY` category/priority, `cast(created_at, Date)` per‑day), tenant‑scoped + `[start, end)` window‑bounded; request‑scoped (read path).
  - **`AnalyticsService`**: owns the calendar‑date → half‑open UTC window conversion (`end` day inclusive) and assembles responses; HTTP‑free, fake‑store testable.
  - **Routes** (`app/analytics/routes.py`): `GET /v1/analytics/summary` (totals + category/priority distributions) and `GET /v1/analytics/timeseries?metric=tickets|analyses` (daily counts); guarded by `get_tenant_context` (any member). Optional `start`/`end` date params.
  - **Models:** `AnalyticsSummary`/`TimeseriesResponse`/`TimeseriesPoint`/`TimeseriesMetric`; `get_analytics_store`/`get_analytics_service` deps; router in `create_app`.
- **Files:** `app/analytics/*` + `app/db/analytics_store.py` (new); edits to `app/models.py`, `app/dependencies.py`, `app/main.py`; tests `tests/test_analytics.py` (new). Docs: [21_analytics.md](21_analytics.md).
- **Verification:** 579 tests, 16 skipped, 95.6%; green with **and** without `OPENAI_API_KEY`; `mypy .` clean. Window math (end‑day inclusive), service assembly + timeseries metrics, routes (summary/timeseries/invalid‑metric 422/invalid‑date 422), store mocked‑session + skipif round‑trip.
- **Lessons:** aggregate **in SQL** behind a port (not in Python); a small service owns the date‑window conversion so it's unit‑testable; SQLAlchemy column expressions type as `Any` in generic query helpers to avoid `InstrumentedAttribute` variance noise.

### M4.2 — Frontend scaffold (Next.js BFF) + auth screens
- **Purpose:** stand up the web frontend — the second Phase 4 milestone. Scope (confirmed with the user): **auth + an application shell**, not feature screens. A **sibling `web/` directory**; the backend is untouched.
- **Implementation:**
  - **Next.js 16 App Router + React 19 + TypeScript + Tailwind v4 + pnpm** scaffolded with `create-next-app` in `web/`; **vitest** added for unit tests.
  - **BFF with httpOnly cookies** (chosen over client‑side tokens): the browser calls Next.js same‑origin; Next.js calls FastAPI server‑to‑server. Tokens (`atk_access`/`atk_refresh`) + active org (`atk_org`) live in **httpOnly** cookies (`sameSite=lax`, `secure` in prod, `maxAge` mirroring backend TTLs). **No backend CORS change.**
  - **Server Actions** (`web/src/lib/auth/actions.ts`) for login/signup/logout/createOrg/setActiveOrg (write side); a **server‑only session DAL** (`session.ts`, React‑`cache`d `getSession()`) for reads; a **refresh Route Handler** (`app/api/auth/refresh/route.ts`) that renews tokens (Route Handlers can write cookies, Server Components can't); a **proxy** (`src/proxy.ts` — Next 16 renamed Middleware→Proxy) for optimistic cookie‑based redirects.
  - **Typed server‑only API client** (`web/src/lib/api/*`) mirroring `app/models.py`, translating the backend error envelope into `ApiError`. Pure modules (`errors`, `navigation` open‑redirect guard, `cookie-config`) kept **Next.js‑free** for unit testing.
  - **Routes:** `/login`, `/signup` (`(auth)` group, client forms → Server Actions), `/dashboard` (`(app)` group, protected shell + org context + placeholders), `/api/auth/refresh`, `/` (→ dashboard). Org context threads `X-Organization-Id`.
  - **CI:** separate `.github/workflows/web-ci.yml` (lint + typecheck + vitest + build), path‑filtered to `web/**`, independent of the Python `CI`; `web/` excluded from the backend `.dockerignore`.
- **Files:** `web/**` (new app); edits to `.dockerignore` (exclude `web/`) and `.github/workflows/web-ci.yml` (new). Docs: [22_frontend.md](22_frontend.md).
- **Verification:** `pnpm lint`/`typecheck`/`test` (11 unit tests)/`build` all green. Behavioral smoke (no backend needed): `/login`,`/signup` → 200; `/dashboard` no‑cookies → 307 `/login`; refresh‑only cookie → 307 `/api/auth/refresh`; `/` → 307 `/dashboard`. A real login round‑trip needs a live Postgres+`JWT_SECRET` backend (unavailable in this env). **Backend code, tests, and gates unchanged.**
- **Lessons:** Next.js 16 is materially different from Next 15 (async `cookies()`, Middleware→`proxy`, async `params`/`searchParams`) — read the bundled `web/node_modules/next/dist/docs/` before writing; the BFF (Server Actions + server‑only DAL + refresh Route Handler + proxy) keeps tokens out of the browser without touching backend CORS; keeping pure logic Next‑free preserves the "strong tests" DNA on the frontend too.

### M4.3 — Agent workspace (read‑first, existing API only)
- **Purpose:** the first real feature screens — a tenant‑scoped agent workspace over the existing ticket/analysis API. **Constraint (from the user): use the existing backend only; add no endpoints;** build as far as the current API allows and record every missing endpoint as follow‑up tech debt.
- **Implementation:**
  - **Three `(app)` screens:** `/tickets` (`GET /v1/tickets` — paginated list + category/priority filters, latest analysis/assignee/SLA per row, overdue flagged), `/tickets/[id]` (`GET /v1/tickets/{id}` + `.../feedback` — original text, versioned analysis history, feedback list), `/analyze` (`POST /v1/analyze` — AI co‑pilot: paste → structured analysis, also persists a ticket).
  - **Mutations via Server Actions** (`web/src/lib/tickets/actions.ts`): re‑analyze (`POST /v1/tickets/{id}/reanalyze`), apply routing/SLA (`POST /v1/tickets/{id}/route`), feedback (`POST /v1/tickets/{id}/feedback`), ad‑hoc analyze — each maps the error envelope to a user‑safe message (402/409/…), then `revalidatePath`s.
  - **Reuses M4.2 seams:** typed server‑only API client (`web/src/lib/api/tickets.ts` + extended `types.ts`), `getAuthedContext()` guard (signed‑in **with active org**, else redirect), reads in Server Components (fail‑soft via `ErrorPanel`), interactive client components (`TicketActionButton`/`FeedbackForm`/`AnalyzeForm`) using `useActionState`. Proxy now also protects `/tickets` + `/analyze`.
  - **Pure, Next‑free, unit‑tested helpers:** `lib/tickets/query.ts` (param parse/clamp/serialize) + `lib/format.ts` (date/SLA/overdue). +12 tests (23 total).
- **Files:** `web/src/app/(app)/{tickets,tickets/[id],analyze}/*`, `web/src/components/{badges,ErrorPanel,TicketActionButton,FeedbackForm,AnalyzeForm,AnalysisCard}.tsx`, `web/src/lib/{api/tickets.ts,api/types.ts,auth/guard.ts,format.ts,tickets/*}`; edits to `proxy.ts`, `AppShell.tsx`, dashboard. **No backend files touched.** Docs: [22_frontend.md](22_frontend.md).
- **Verification:** `pnpm lint`/`typecheck`/`test` (23)/`build` all green. Smoke (no backend): `/tickets`,`/tickets/{id}`,`/analyze` unauth → 307 `/login?next=…`; refresh‑only cookie → 307 `/api/auth/refresh`. Authenticated data flows need a live backend (unavailable here); pages fail‑soft.
- **Backend gaps recorded as tech debt (NOT implemented):** (1) **no ticket status/lifecycle** (no `status` column, no `PATCH /v1/tickets/{id}`) — the primary gap, gates a full workflow; (2) no manual assignment (assignee only via rules `POST /route`); (3) limited list querying (no search/date/source/assignee/sort/cursor); (4) analyze/reanalyze don't return the ticket id (no deep‑link); (5) no ticket delete; (6) no bulk actions; (7) no SLA breach/escalation state. See [22_frontend.md](22_frontend.md). **Decision on a small "ticket lifecycle" backend milestone is deferred to after M4.3.**
- **Lessons:** the workspace's read/triage half is fully deliverable on today's API; the write half (status/assignment) is where the backend runs out — cleanly isolating that as the candidate next backend slice. Passing server actions as props (server page → client button) keeps one generic action component for re‑analyze/route.
- **M3.6 frontend integration (completion of M4.3; frontend‑only, no backend change):** wired the M3.6 backend surface into the workspace — **status controls** + **manual assignee** editing on the detail page (`StatusControl`/`AssigneeControl` → `updateStatusAction`/`updateAssigneeAction` → `PATCH /v1/tickets/{id}`; empty assignee clears via `{"assignee": null}`); a `StatusBadge` in the list (new column) + detail header; the new **list filters** `status`/`assignee`/`source`/`search` + `sort` (via `lib/tickets/query.ts` + `listTickets` + pagination, `hasActiveFilters` for Clear); **`ticket_id` deep‑linking** (`analyzeText`/`reanalyzeTicket` → `AnalyzeResponse`; `analyzeAction` redirects the co‑pilot to `/tickets/{ticket_id}`, inline‑result fallback without a DB). Files: `web/src/lib/{api/types,api/tickets,tickets/query,tickets/actions}.ts`, `web/src/components/{badges,TicketControls}.tsx`, the two ticket pages. `pnpm lint`/`typecheck`/`test` (41)/`build` green; backend untouched. See [22_frontend.md](22_frontend.md).

### M3.6 — Ticket Lifecycle & Workspace APIs (backend; integration‑driven)
- **Purpose:** close the four backend gaps M4.3 surfaced during frontend integration — no ticket status, no manual assignment, no `ticket_id` for deep‑linking, thin list filtering. A **Phase 3 backend milestone created after M4.3** on the integration‑driven roadmap; kept intentionally small.
- **Implementation:**
  - **Lifecycle:** `TicketStatus` enum (`open`/`in_progress`/`pending`/`resolved`/`closed`) stored as a value string on `Ticket.status` (`String(32)`, NOT NULL, `server_default 'open'`); migration `0010_ticket_status`. Transitions unrestricted (no state machine).
  - **`PATCH /v1/tickets/{id}`** (any org member): updates `status`/`assignee` via `UpdateTicketRequest` using `model_fields_set` (`{"assignee": null}` clears vs. omitted unchanged; ≥1 field else 422; unknown status 422; cross‑org 404). Mutates the loaded ORM object → request‑scoped session commits; the `TicketStore` read port stays read‑only.
  - **`ticket_id` in analyze responses:** new `AnalyzeResponse(TicketAnalysis + ticket_id)` for `/v1/analyze` + `/reanalyze` (additive; legacy `/analyze` + email channel unchanged). `run_analysis` → `AnalyzeOutcome`; `persist_analysis` returns the id; cache‑hit resolves best‑effort via new `resolve_ticket_id` (skipped for the legacy org‑less path). `null` only without a DB.
  - **Richer `GET /v1/tickets`:** additive `status`/`assignee`/`source`/`search` (escaped `ILIKE`) filters + `sort` (created_at asc/desc, default desc). `count_for_org` applies the same filters. No cursor pagination.
- **Files:** `app/db/models.py` (`Ticket.status`), `alembic/versions/0010_ticket_status.py` (new), `app/models.py` (`TicketStatus`/`TicketSort`/`AnalyzeResponse`/`UpdateTicketRequest` + `status` on summary/detail), `app/tickets/{routes,base}.py`, `app/db/{ticket_store,repositories}.py`, `app/services/{analyze,analysis_service}.py`, `app/main.py`, `app/channels/routes.py`; tests in `tests/{test_tickets,test_analyze_v1,test_feedback}.py`. Docs: [17_tickets.md](17_tickets.md), D30 in [12_design_decisions.md](12_design_decisions.md). **Frontend untouched.**
- **Verification:** ruff + mypy clean; **619 passed, 16 skipped**, green with **and** without `OPENAI_API_KEY`; **95.31%** coverage (gate 90%); migration `0010` verified offline (`--sql`). PATCH (status/assignee/clear/404/422), list filters + sort, `ticket_id` on `/v1/analyze` (null w/o DB) + reanalyze, `persist`/`resolve` id unit tests.
- **Lessons:** additive response subclass (`AnalyzeResponse`) surfaces `ticket_id` without breaking the legacy contract; sorting the in‑memory fake to match the real store's `ORDER BY created_at DESC` exposed an order‑dependent legacy test (fixed with explicit timestamps); `model_fields_set` cleanly distinguishes "clear" from "unchanged" in PATCH.

### M4.4 — Analytics dashboard (frontend)
- **Purpose:** the analytics UI over the M4.1 API — a Phase 4 frontend milestone. Scope (confirmed with the user): **analytics dashboard only**; the admin panel (API keys/webhooks/routing‑config UI) deferred to a proposed **M4.5**.
- **Implementation:**
  - **`/analytics`** (`(app)` group, `getAuthedContext`): stat tiles (total tickets/analyses), a daily **timeseries** bar chart (metric = tickets|analyses), and **by‑priority**/**by‑category** distribution bars; a metric + date‑window **GET‑form** filter row (no client JS). Reads in a Server Component (`Promise.all`), fail‑soft `ErrorPanel`.
  - **Server‑only client** `web/src/lib/api/analytics.ts` (`getSummary`/`getTimeseries`) + analytics types mirroring `app/models.py`; **pure/tested** `web/src/lib/analytics/query.ts` (param parse/validate, href builder, `barPercent`, `sortedEntries`) — +10 tests (33 total).
  - **Native charts, no dependency** (dataviz method on the app's Tailwind design): single‑hue category bars (identity by label, not rainbow), the existing severity color scale for priority, a single‑hue SVG timeseries with recessive baseline + per‑bar `<title>` hover; values in ink, one measure per chart, theme‑aware.
  - Nav **Analytics** link; dashboard card made live; proxy protects `/analytics`.
- **Files:** `web/src/app/(app)/analytics/page.tsx`, `web/src/components/{StatTile,DistributionBars,TimeseriesChart,AnalyticsControls}.tsx`, `web/src/lib/{api/analytics.ts,api/types.ts,analytics/query.ts + test}`; edits to `AppShell.tsx`, dashboard, `proxy.ts`. **Backend untouched.** Docs: [22_frontend.md](22_frontend.md).
- **Verification:** `pnpm lint`/`typecheck`/`test` (33)/`build` green. Smoke: `/analytics` unauth → 307 `/login?next=/analytics`; refresh‑only → 307 `/api/auth/refresh`. Real‑aggregate visual pass needs a live backend (unavailable); page fail‑softs, bar math unit‑tested.
- **Lessons:** a dashboard is stat tiles + a few native bars — no charting lib needed; single‑hue magnitude bars (label carries identity) avoid the categorical‑rainbow anti‑pattern; reusing the priority severity scale keeps the viz consistent with the rest of the app.

### M4.5 — Admin panel (frontend)
- **Purpose:** a tenant‑scoped admin panel (`/settings`) over the existing org‑scoped endpoints — the last of the original M4.4 scope, split out to keep milestones reviewable.
- **Implementation:**
  - **`/settings` area** (`(app)` group, `getAuthedContext`) with a tab sub‑nav (`SettingsTabs`, client `usePathname`): **Overview** (org name/slug/plan + `GET /v1/orgs/{id}/usage`), **API keys** (list + create → secret once + revoke), **Webhooks** (list + create → signing secret once + delete), **Routing & SLA** (routing rules + SLA policies: list + create + delete each).
  - **Server‑only client** `web/src/lib/api/admin.ts` (+ admin types) — routes take `org_id` in the **path** and authorize via the user JWT, so token + path org id (no `X-Organization-Id`). **Server Actions** `web/src/lib/admin/actions.ts` map errors (**403 → owner/admin required**) and `revalidatePath`; create actions return the **one‑time secret** in state (revealed via `SecretReveal`, no redirect).
  - **Pure/tested** `web/src/lib/admin/parse.ts` (`parseCsvList`, `buildRoutingConditions`/`buildRoutingActions`) — +5 tests (38 total). Components: `SecretReveal`, generic `DeleteButton`, four create forms. Nav **Settings** link; proxy protects `/settings`.
  - **Role not in session:** backend enforces owner/admin; a non‑privileged member gets a graceful 403 (controls not hidden — no role field in the session; surfacing it is a small backend follow‑up).
- **Files:** `web/src/app/(app)/settings/{layout,page,api-keys,webhooks,routing}.tsx`, `web/src/components/{SettingsTabs,SecretReveal,DeleteButton,ApiKeyCreateForm,WebhookCreateForm,RoutingRuleCreateForm,SlaPolicyCreateForm}.tsx`, `web/src/lib/{api/admin.ts,api/types.ts,admin/actions.ts,admin/parse.ts + test}`; edits to `AppShell.tsx`, `proxy.ts`. **Backend untouched.** Docs: [22_frontend.md](22_frontend.md).
- **Verification:** `pnpm lint`/`typecheck`/`test` (38)/`build` green. Smoke: `/settings` + sub‑pages unauth → 307 `/login?next=…`; refresh‑only → 307 `/api/auth/refresh`. Live CRUD needs a backend (unavailable); pages fail‑soft.
- **Lessons:** one‑time secrets fit the Server‑Action `useActionState` return (reveal once) instead of a redirect; a generic `DeleteButton` + per‑resource create forms keep four CRUDs lean; without a role in the session the backend stays the sole authorization gate (defense‑in‑depth), 403s surfaced inline.

---

## PHASE 5 — AI moat

### M5.1 — Prompt versioning + eval harness (backend)
- **Purpose:** make the analysis prompt a **versioned, recorded** artifact and add an **eval harness** that scores analysis quality against labeled cases so prompt/model changes can be **gated in CI** — the first Phase 5 (AI moat) milestone.
- **Implementation:**
  - **Versioned prompt registry** (`app/prompts.py`): `PromptVersion` + `PROMPT_VERSIONS` + `get_prompt` (fail‑safe to default), mirroring `_PROVIDERS`/plans; `v1` = the pre‑M5.1 prompt (unchanged); back‑compat `SYSTEM_PROMPT`/`build_user_prompt` retained. Selection via `LLM_PROMPT_VERSION` → `Settings.llm_prompt_version` → `ProviderConfig.prompt_version` → `OpenAIProvider`.
  - **Version recorded:** `AnalysisResult.prompt_version` (set by the provider) → `run_analysis` → `persist_analysis` → `add_analysis` → new **`analyses.prompt_version`** column (nullable `String(32)`, migration `0011_analysis_prompt_version`, additive/back‑compat) → surfaced additively on `AnalysisRead`.
  - **Eval harness** (`app/eval/`): `EvalCase`/`EvalReport` + `run_eval(provider, cases)` (provider‑agnostic; a `Provider*` error → error outcome, not abort) + pure metrics (`category_accuracy`/`priority_accuracy`/`exact_match_accuracy`) + `meets_threshold` + `summarize`; a curated `GOLDEN_CASES`; a `python -m app.eval` CLI that exits non‑zero below threshold (`EVAL_MIN_*` envs, defaults 0.80/0.60).
  - **CI gate:** opt‑in `.github/workflows/eval.yml` (`workflow_dispatch`, skipped without an `OPENAI_API_KEY` secret; off the per‑PR path to control LLM cost). Default `ci.yml` unchanged.
- **Files:** `app/prompts.py`, `app/ai/{base,config,openai_provider,factory}.py`, `app/config.py`, `app/db/models.py` (`analyses.prompt_version`), `alembic/versions/0011_analysis_prompt_version.py` (new), `app/db/repositories.py`, `app/services/{analysis_service,analyze}.py`, `app/models.py` (`AnalysisRead.prompt_version`), `app/tickets/routes.py`, `app/eval/*` (new), `.github/workflows/eval.yml` (new); tests `tests/{test_prompts,test_eval}.py` (new) + assertions in `tests/{test_openai_provider,test_repositories}.py`. Docs: [23_prompts_eval.md](23_prompts_eval.md), D32. **Frontend untouched.**
- **Verification:** ruff + mypy clean; **635 passed, 18 skipped**, green with **and** without `OPENAI_API_KEY`; **94.64% coverage** (gate 90%); migration `0011` verified offline (`--sql`). Prompt registry fail‑safe/back‑compat, `messages()` shape, provider records `v1`, `add_analysis` persists it, eval metrics/run/threshold/summarize with a fake provider, golden‑set validity, opt‑in live eval (`skipif`).
- **Lessons:** a versioned prompt registry is the exact `get_plan`/`_PROVIDERS` pattern (fail‑safe selector); the eval harness stays green offline by scoring a **fake provider**, with the real gate opt‑in (cost); mypy checks inline chat‑message literals against the SDK's TypedDict union, so the provider builds the message list inline from the selected `PromptVersion` (the `.messages()` helper is for the harness/tests).

### M5.2 — RAG over the knowledge base (backend)

- **Purpose:** ground tenant-scoped analyses in an organization's knowledge base via retrieval-augmented generation — the second Phase 5 (AI moat) milestone, and the substrate for M5.3 (auto-resolve).
- **Implementation:**
  - **Provider-agnostic embeddings** (`app/embeddings/`, mirroring `app/ai/`): `EmbeddingProvider` ABC + `Embedding*` error hierarchy + `EmbeddingConfig` + `_EMBEDDING_PROVIDERS` registry; `OpenAIEmbeddingProvider` (OpenAI-compatible family, tenacity retries, error translation) + a **keyless deterministic `HashEmbeddingProvider`** (feature hashing, offline). `EMBEDDING_*` settings (key falls back to `llm_api_key`). Built **defensively** in `create_app` → `app.state.embedding_provider` (→ 503 if unbuildable; app still boots), disposed in `lifespan`.
  - **Knowledge base schema:** `Document` + `DocumentChunk` ORM (tenant-scoped NOT NULL org FKs; chunk `embedding` as **JSONB**, org denormalized for search) + migration `0012_documents`.
  - **Pure helpers:** `app/rag/chunking.py::chunk_text` (overlapping word chunks) + `app/rag/similarity.py` (`cosine_similarity`/`top_k_indices`) — I/O-free, unit-tested.
  - **Vector store:** `VectorStore` port (`app/rag/base.py`) + `SqlAlchemyVectorStore` (`app/db/vector_store.py`), session-injected (request-scoped for routes; own session for best-effort retrieval). `RagService` (`app/rag/service.py`) ingests (chunk→embed→store) + retrieves (embed→rank), tenant-scoped.
  - **KB endpoints** (`app/rag/routes.py`): `POST/GET/DELETE /v1/orgs/{org_id}/documents` (owner/admin write, membership read; 502 on embed failure) + `GET …/documents/{id}` + `GET …/documents/search?q=&k=` (ranked retrieval); router in `create_app` (now **11 routers**). `get_vector_store`/`get_embedding_provider`/`get_rag_service`/`get_context_retriever` deps.
  - **Analyze grounding:** append-only context-aware prompt **`v2`** (v1 unchanged); additive `AnalysisProvider.analyze(ticket_text, *, context=None)` (contract + `Provider*` unchanged); `run_analysis(retrieve_context=…)` — best-effort retrieval (own session, swallows errors, **tenant path only**), context folded into the cache key (`{org}:{hash}:rag:{ctx_hash}`) and passed to the provider; `build_context_retriever`/`get_context_retriever` wire it into `/v1/analyze` + `/v1/tickets/{id}/reanalyze`. Opt-in via `RAG_ENABLED` + `LLM_PROMPT_VERSION=v2`. `rag_retrievals_total{outcome}` metric (**11 metric families**).
- **Files:** `app/embeddings/*` (new), `app/rag/*` (new), `app/db/vector_store.py` (new), `alembic/versions/0012_documents.py` (new); edits to `app/db/models.py` (`Document`/`DocumentChunk`), `app/config.py` (embedding/RAG settings), `app/models.py` (KB schemas), `app/prompts.py` (`v2`), `app/ai/{base,openai_provider}.py` (context), `app/services/analyze.py`, `app/dependencies.py`, `app/main.py`, `app/tickets/routes.py`, `app/observability/metrics.py`; tests `tests/test_{embeddings,rag_core,rag_store,rag,rag_analyze}.py` (new). Docs: [24_rag.md](24_rag.md), D33. **Frontend untouched.**
- **Verification:** ruff + ruff format + mypy clean; **755 passed, 20 skipped**, green with **and** without `OPENAI_API_KEY`; **95.12% coverage** (gate 90%); migration `0012` verified offline (`--sql`). Embeddings (determinism/translation/factory), pure chunking+similarity, vector store (mocked + skipif round-trip), RAG service + KB routes (CRUD/search/502/404), prompt `v1`/`v2`, `run_analysis` grounding (context→provider, cache-key namespacing, legacy skipped, best-effort), `/v1/analyze` grounded end-to-end.
- **Lessons:** the embeddings layer is a straight copy of the AI-provider DNA (registry + neutral config + error translation), so a keyless `hash` provider makes the whole feature offline-testable; keeping ranking in a **pure** module (store loads candidates) mirrors routing and stays fake-testable; grounding is additive at every seam (`v2` append-only, `analyze(context=)` optional, best-effort retriever) so the legacy contract and no-RAG behavior are byte-identical; re-exporting `service`/`retrieval` from `app/rag/__init__` created an import cycle (they reach into `app.db.vector_store`) — the package `__init__` stays minimal (pure surface only), like `app/routing/__init__`.

### M5.3 — Agentic resolution actions (backend)

- **Purpose:** turn analyses into **human-approved, audited** resolution actions ("auto-resolve") — the final Phase 5 (AI moat) milestone. Nothing executes automatically; destructive actions always require approval.
- **Implementation:**
  - **Domain + schema:** `ResolutionAction` + `AuditLog` ORM (tenant-scoped, org NOT NULL) + migration `0013`; enums (`ActionType`/`ActionStatus`/`ActorType`) + schemas (`SuggestedAction`/`ResolutionPlan`/`ResolutionActionResponse`/`AuditLogResponse`) in `app/models.py`. **Pure state machine** `app/actions/state.py` (proposed→approved→executed/failed; rejected/executed/failed terminal; `ensure_transition` → `InvalidActionTransition`).
  - **Ports** (`app/actions/base.py`): `ActionSuggester`/`ActionHandler`/`ActionStore`/`AuditStore` + single-source `DESTRUCTIVE_ACTIONS`. Stores: `SqlAlchemyActionStore`/`SqlAlchemyAuditStore` (`app/db/action_store.py`).
  - **Suggesters:** `RuleBasedActionSuggester` (deterministic offline default, `actor_type=system`) + `LlmActionSuggester` (`ACTION_SUGGESTER=llm`, `actor_type=ai`) reusing an **additive** `AnalysisProvider.suggest_actions` (default-raise → only `OpenAIProvider` overrides, structured `ResolutionPlan` output, `Provider*`-translated) + action prompt in `app/prompts.py`. `build_action_suggester` (fail-safe to rule).
  - **Handlers** (`app/actions/handlers.py`): internal `set_status`/`assign`/`add_note` (mutate the ticket); destructive `send_reply`/`escalate` (dispatch a signed webhook, reusing M3.3b; never auto-run).
  - **Service** (`app/actions/service.py`): `suggest`/`approve`/`reject`/`execute` — state-machine-guarded (execute requires approved → 409 otherwise), each transition audited with the actor.
  - **Routes** (`app/actions/routes.py`): `POST /v1/tickets/{id}/actions/suggest`, `GET …/actions`, `POST …/actions/{aid}/{approve,reject,execute}` (owner/admin **user** via `require_approver` — never an API key), `GET /v1/orgs/{org_id}/audit-logs` (owner/admin). 12th router. DI: `get_action_store`/`get_audit_store`/`get_action_suggester`/`get_action_service`/`require_approver`.
- **Files:** `app/actions/*` (new), `app/db/action_store.py` (new), `alembic/versions/0013_resolution_actions.py` (new); edits to `app/db/models.py`, `app/models.py`, `app/config.py` (`action_suggester`), `app/prompts.py`, `app/ai/{base,openai_provider}.py` (`suggest_actions`), `app/dependencies.py`, `app/main.py`; tests `tests/test_actions_{state,,routes,llm}.py` (new). Docs: [25_actions.md](25_actions.md), D34. **Frontend untouched.**
- **Verification:** ruff + ruff format + mypy clean; **855 passed, 20 skipped**, green with **and** without `OPENAI_API_KEY`; **95.29% coverage** (gate 90%); migration `0013` verified offline (`--sql`). State machine (execution-requires-approval), suggester proposals, handlers + webhook dispatch, service audit trail + failure paths, the full suggest→approve→execute HTTP flow, `require_approver` (api-key/non-privileged rejected), LLM suggester + `suggest_actions` translation.
- **Lessons:** the safety story is carried by a **real state machine** (unlike ticket status) — executing an unapproved action is simply an illegal transition (409), not a special case; making `suggest_actions` a **concrete default-raise** on the ABC (not abstract) kept every existing provider/fake valid (a real `_FakeProvider` subclass exists in the eval tests); reusing the webhook dispatcher for destructive effects means the app never performs an irreversible external op itself while still delivering an auditable, integration-ready action; a single `DESTRUCTIVE_ACTIONS` source of truth keeps the suggester and handlers from disagreeing on what needs approval.

---

## PHASE 5 — AI moat: complete

Phase 5 is complete: **M5.1** (prompt versioning + eval harness), **M5.2** (RAG over the knowledge base), and **M5.3** (agentic resolution actions). The AI moat — measurable quality, grounded analyses, and human-approved auditable actions — is in place.

---

## Housekeeping commits
- **Docker networking cleanup** (`chore`): compose uses service names (`db:5432`, `cache:6379`); `.env`/`.env.example` keep `localhost` for host tools; README "host vs. containers" section.
- **`.env.example` port fix:** host `DATABASE_URL` → `localhost:5433` (matches the published Postgres port).

## Common lessons across milestones
- Always run the suite **with and without `OPENAI_API_KEY`** (alias gotcha).
- Verify migrations **offline** (`alembic upgrade head --sql`) when no live DB.
- Version‑independent constants (error codes) — don't derive from stdlib phrases.
- Catch the *actual* exception type at each boundary (`TokenError` vs `AuthError`).
- Keep response/cache shapes stable when adding metadata (use result wrappers).
