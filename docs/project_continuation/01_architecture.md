# 01 — Architecture

This document explains every layer, why it exists, how layers communicate, their responsibilities, boundaries, and extension points. Read [12_design_decisions.md](12_design_decisions.md) alongside it.

## Layer map

```
HTTP client
   │
   ▼
┌─────────────────────────────────────────────────────────────────────┐
│ FastAPI app (created by app.main.create_app)                        │
│                                                                     │
│  Middleware (outer→inner):                                          │
│    RequestContextMiddleware  → sets X-Request-ID + contextvar        │
│    request_timing_middleware → duration, X-Process-Time, http metric │
│    SecurityHeadersMiddleware → nosniff / frame-deny / referrer       │
│    CORSMiddleware            → configurable origins                  │
│                                                                     │
│  Routers:                                                           │
│    app.main.router      → /analyze, /v1/analyze, /health, /ready, ... │
│    app.auth.routes      → /v1/auth/*                                 │
│    app.tenancy.routes   → /v1/orgs, /v1/orgs/{id}/api-keys, /v1/tenant│
│    app.billing.routes   → /v1/billing/webhook, /v1/orgs/{id}/usage    │
│    app.tickets.routes   → /v1/tickets[/{id}][/feedback|/reanalyze]    │
│    app.jobs.routes      → /v1/analyze/batch[/{job_id}]                 │
│    app.webhooks.routes  → /v1/orgs/{id}/webhooks[/{id}]                │
│    app.routing.routes   → /v1/orgs/{id}/{routing-rules,sla-policies}   │
│                           + /v1/tickets/{id}/route                      │
│    app.channels.routes  → /v1/channels/{email,import}                   │
│    app.analytics.routes → /v1/analytics/{summary,timeseries}            │
│    app.rag.routes       → /v1/orgs/{id}/documents[/{id}|/search]        │
│    app.actions.routes   → /v1/tickets/{id}/actions/… + /orgs/{id}/audit-logs │
│                                                                     │
│  Exception handlers → standardized {"error": {...}} envelope         │
└─────────────────────────────────────────────────────────────────────┘
   │ Depends(...)                          app.state: settings, cache,
   ▼                                       provider, db_engine,
┌──────────────┐   ┌──────────────┐        db_sessionmaker, token_service
│ Dependencies │──▶│ app.state     │
│ (app.depend- │   └──────────────┘
│  encies)     │
└──────┬───────┘
       │ inject
       ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│ AI provider   │  │ Cache         │  │ Auth          │  │ Tenancy       │
│ (app.ai)      │  │ (app.cache)   │  │ (app.auth)    │  │ (app.tenancy) │
│ AnalysisProv. │  │ Cache proto   │  │ AuthProvider  │  │ TenantContext │
└──────┬────────┘  └──────┬────────┘  └──────┬────────┘  └──────┬────────┘
       │                  │                  │ ports            │ ports
       ▼                  ▼                  ▼                  ▼
   OpenAI SDK        Redis / memory   ┌───────────────────────────────────┐
   (or compatible)                    │ Persistence (app.db, app.services)│
                                      │ ORM models, repositories, stores, │
                                      │ session/engine, Alembic migrations│
                                      └───────────────────────────────────┘
                                                     │
                                                     ▼
                                                 PostgreSQL
```

## Why an application factory (`create_app`)

`app/main.py::create_app(settings)` constructs the FastAPI app, builds shared resources, registers middleware/handlers/routers, and returns it. A module‑level `app = create_app()` is exposed for `uvicorn app.main:app`.

- **Why:** deterministic, testable startup. Tests build isolated apps (`create_app(custom_settings)`) and override dependencies. There are **no import‑time stateful singletons** — the earlier code cached a global OpenAI client + settings at import, which was a footgun (the review's #1 finding). See [10_dependency_injection.md](10_dependency_injection.md).
- **Boundary:** `create_app` owns *construction*; `lifespan` owns *teardown* (closing provider client, cache client, DB engine). Nothing else disposes resources.
- **Extension point:** to add a resource (e.g., a message queue), build it in `create_app`, store on `app.state`, expose a `Depends`, and dispose it in `lifespan`.

## Dependency Injection (`app/dependencies.py`)

All request‑time wiring lives here. Endpoints declare `Depends(get_x)`; tests override via `app.dependency_overrides`. Key dependencies:

- Resource accessors: `get_app_settings`, `get_analysis_provider`, `get_cache`, `get_db_sessionmaker`.
- Session: `get_db_session` (yields a session, commits on success / rolls back on error, 503 if no DB).
- Auth: `get_token_service` (503 if no `JWT_SECRET`), `get_user_store`, `get_auth_service`, `get_current_user` (HTTP Bearer).
- Tenancy: `get_org_store`, `get_api_key_store`, `get_org_service`, `get_api_key_service`, `require_org_membership` (403), `get_tenant_context` (X‑API‑Key or JWT), `get_optional_token_service` (no 503 — used so API‑key resolution doesn't require `JWT_SECRET`).

**Why the ports (`UserStore`, `OrgStore`, `ApiKeyStore`, `Cache`) are `Protocol`s:** so routes/services can be tested against in‑memory fakes with zero DB. This is the backbone of the testing strategy ([11_testing_strategy.md](11_testing_strategy.md)).

## AI provider layer (`app/ai/`)

`AnalysisProvider` (ABC) exposes `name`, `model`, `analyze(text) -> AnalysisResult`, `aclose()`. Concrete providers translate SDK exceptions into a **provider‑agnostic error hierarchy** (`ProviderError` + `Provider{Timeout,RateLimit,Connection,Response}Error`). A registry (`_PROVIDERS` of `ProviderSpec`) + `build_provider(settings)` selects the backend. `OpenAIProvider` serves OpenAI **and every OpenAI‑compatible endpoint** via `base_url`. Full detail: [04_ai_provider_system.md](04_ai_provider_system.md).

- **Boundary:** the route (`/analyze`) catches only `Provider*` exceptions; it never imports the OpenAI SDK. This is the reason adding Anthropic/Gemini needs *zero* business‑logic change.

## Cache layer (`app/cache/`)

Async `Cache` protocol (`get`/`set`/`ping`/`aclose`). `TTLCache` (in‑memory LRU + TTL) and `RedisCache` (shared, best‑effort). `build_cache(settings)` picks the backend from `REDIS_URL`. Detail: [07_cache.md](07_cache.md).

## Authentication layer (`app/auth/`)

Provider‑agnostic, mirroring the AI layer: `AuthProvider` (ABC) → `AuthenticatedIdentity`; shared `TokenService` (JWT) + Argon2 `password.py`; `LocalAuthProvider`; `AuthService` orchestrates signup/login/refresh/current‑user; `UserStore` port. Detail: [05_authentication.md](05_authentication.md).

## Tenancy layer (`app/tenancy/`)

`TenantContext` (org + principal), `OrgStore`/`ApiKeyStore` ports, `OrganizationService`/`ApiKeyService`, API‑key gen/hash. `get_tenant_context` resolves the org from an API key or a user JWT. Detail: [06_tenancy.md](06_tenancy.md).

## Billing / usage metering (`app/billing/`)

Meters analyses and enforces per‑plan monthly quotas, and ingests billing webhooks. `UsageStore` port + `SqlAlchemyUsageStore`; `BillingService.check_quota`; a configurable `plans` registry (placeholder limits); best‑effort `record_analysis_usage`. Enforcement is a `require_quota` dependency on `/v1/analyze` (**402** before the LLM call); metering is best‑effort on the tenant path. A provider‑agnostic `BillingProvider` (+ `StripeBillingProvider`, lazy SDK) turns webhooks into a neutral `BillingEvent`; `WebhookService` ingests them idempotently (`processed_webhook_events`) and syncs `Organization.plan`. Legacy `/analyze` is untouched. Detail: [16_billing.md](16_billing.md).

## Persistence layer (`app/db/`, `app/services/`)

ORM models (`Ticket`, `Analysis`, `Organization`, `User`, `Membership`, `ApiKey`), repositories (ticket/analysis data access), the auth/tenancy stores (user/org/api‑key), the async engine/sessionmaker factories, and Alembic. `analysis_service.persist_analysis` writes best‑effort. Detail: [08_persistence.md](08_persistence.md), [03_database.md](03_database.md).

## Observability (`app/core/logging.py`, `app/observability/`, `app/readiness.py`)

Structured JSON logs correlated with `X-Request-ID` (a `contextvar`), Prometheus metrics at `/metrics`, and liveness (`/health`) vs readiness (`/ready`). Detail: [09_observability.md](09_observability.md).

## Embeddings & RAG (`app/embeddings/`, `app/rag/`) — M5.2

Retrieval‑augmented generation grounds analyses in a tenant's knowledge base.
`app/embeddings/` is a **sibling of the AI provider layer** — `EmbeddingProvider`
(ABC) + `Embedding*` errors + `EmbeddingConfig` + a `_EMBEDDING_PROVIDERS` registry
(`OpenAIEmbeddingProvider` + a keyless deterministic `hash` provider), built
defensively on `app.state.embedding_provider`. `app/rag/` holds a `VectorStore`
port (`SqlAlchemyVectorStore` over `documents`/`document_chunks`), **pure** chunking
+ cosine/top‑k helpers, a `RagService` (ingest/retrieve), KB routes, and a
best‑effort `ContextRetriever` fed into `run_analysis` (opt‑in, tenant‑scoped).
Every vector is scoped by `organization_id`. Detail: [24_rag.md](24_rag.md).

## Agentic resolution actions (`app/actions/`) — M5.3

The human‑in‑the‑loop action layer. An `ActionSuggester` (rule‑based offline
default, or LLM‑backed reusing the `AnalysisProvider`) **proposes** actions; a
**pure state machine** (`state.py`) gates transitions so **execution requires
prior approval**; `ActionHandler`s execute the effect (internal ticket mutations,
or signed webhooks for destructive/outward actions, reusing M3.3b); and every
transition is written to an append‑only, tenant‑scoped `audit_logs` row.
`ActionService` orchestrates; `require_approver` limits approve/execute to a
privileged **human** (owner/admin user, never an API key). Nothing runs
automatically. Detail: [25_actions.md](25_actions.md).

## Cross‑cutting HTTP concerns (`app/core/`)

- `middleware.py` — `RequestContextMiddleware` (request id), `SecurityHeadersMiddleware`, and the `SECURITY_HEADERS`/`REQUEST_ID_HEADER` constants.
- `errors.py` — the standardized error envelope `{"error": {"code", "message", "request_id", "details"?}}` with **stable, version‑independent** code slugs (see [12_design_decisions.md](12_design_decisions.md) — a real bug came from deriving codes from `HTTPStatus.phrase`).
- `logging.py` — `JsonFormatter`, `RequestIdFilter`, `configure_logging`.

## How layers communicate (the rules)

- **Downward only, through abstractions.** Routes → services/providers → ports → concrete impls. Higher layers never import lower concretions (a route never imports `openai` or `SqlAlchemyUserStore`).
- **Errors translate at boundaries.** SDK/DB exceptions are caught at the provider/store boundary and re‑raised as domain errors (`Provider*`, `AuthError`, `TenantError`), which routes/deps map to HTTP.
- **State flows via `app.state` + `Depends`.** Never via module globals.

## Extension points (summary)

| Want to add… | Do this | Never touch |
|---|---|---|
| An LLM backend | new `AnalysisProvider` + `_PROVIDERS` entry | `/analyze` route, `Provider*` errors |
| An auth method | new `AuthProvider` + registry entry | `AuthService`, `TokenService`, routes |
| A cache backend | new `Cache` impl + `build_cache` branch | endpoint cache calls |
| A DB‑backed capability | new ORM model + migration + store/repo + service + dependency | existing migrations |
| An endpoint | new router or route function + `Depends` | error envelope, middleware order |
| A meter/quota | new `event_type` + `require_quota`‑style gate; limits via the `plans` registry | best‑effort metering, legacy `/analyze` |
| A billing backend | new `BillingProvider` + `_PROVIDERS` entry (SDK behind the port) | webhook idempotency, `BillingEvent` shape |
| A tenant‑scoped read API | new read `Protocol` store + `SqlAlchemy*Store` + `get_*_store` dep + route | scope every query by `organization_id` |
| A background job type | reuse services under the `JobRunner`; a background‑visible store is sessionmaker‑backed | `JobRunner` port, no second analyze pipeline |
| An outbound event | dispatch via `WebhookDispatcher` (signed, best‑effort); add an `event_type` | never break the caller; httpx client injected |
| Per‑tenant helpdesk config | config table + request‑scoped store + a **pure** engine + an explicit apply endpoint | don't couple `run_analysis`; keep the engine pure |
| An inbound channel | thin adapter reusing `run_analysis`/`submit_analyze_batch`; thread a `source` | no second analyze path; stay tenant‑scoped + metered |
| An analytics metric | aggregate in SQL on the `AnalyticsStore` port; assemble in `AnalyticsService` | read‑only + tenant‑scoped; keep aggregation in the DB |
| An embeddings backend | new `EmbeddingProvider` + `_EMBEDDING_PROVIDERS` entry | `Embedding*` translation; keyless offline default |
| An agentic action type | new `ActionType` + `ActionHandler` (+ `DESTRUCTIVE_ACTIONS` if outward) registered in `build_action_handlers` | the approval gate, state machine, and audit trail |

Full recipes: [developer_guide.md](developer_guide.md).
