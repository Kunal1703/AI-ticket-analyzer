# 10 — Dependency Injection & Application Lifecycle

The DI/app‑factory seam was introduced in **M1.0** to remove import‑time global singletons (the Phase‑0 review's top finding). Everything stateful is owned by `create_app` and injected via `Depends`.

## `create_app(settings)` (`app/main.py`)

Responsibilities, in order:
1. Resolve settings (arg or `get_settings()`), `configure_logging(settings)`.
2. Build the `FastAPI(lifespan=...)`.
3. Build shared resources onto `app.state`:
   - `settings`
   - `cache = build_cache(settings)`
   - `provider = build_provider(settings)`
   - `db_engine` / `db_sessionmaker` (only if `DATABASE_URL`; else `None`)
   - `token_service` (only if `JWT_SECRET`; else `None`)
   - `plans = build_plans(settings.plan_monthly_analysis_limits)` — the billing plan registry (M2.5a)
   - `billing_provider` (only if `STRIPE_WEBHOOK_SECRET`; else `None`) — M2.5b
   - `job_runner = build_job_runner(settings)` — in‑process by default (M3.3a)
   - `http_client = httpx.AsyncClient()` — outbound webhook delivery (M3.3b)
   - `embedding_provider` (**defensively** — `None` if unbuildable, so the app still boots) — RAG embeddings (M5.2)
4. Register middleware (CORS, SecurityHeaders, **timing then RequestContext so RequestContext is outermost**).
5. Register exception handlers (envelope) — including the global `ProviderError` handler (M2.4).
6. Include **12** routers: `main.router`, `auth_router`, `tenancy_router`, `billing_router`, `tickets_router`, `batch_router`, `webhooks_router`, `routing_router`, `channels_router`, `analytics_router`, `rag_router` (M5.2), `actions_router` (M5.3).

A module‑level `app = create_app()` is exposed for `uvicorn app.main:app`.

**Why:** deterministic startup, testable in isolation, no import‑time side effects beyond building the module‑level app (which itself only builds lazy resources — no network). Tests can `create_app(custom_settings)` and assert `app.state.*`.

## `app.state` (the resource container)

| `app.state.*` | Type | Built when | Disposed in lifespan |
|---|---|---|---|
| `settings` | `Settings` | always | — |
| `cache` | `Cache` | always | `await cache.aclose()` |
| `provider` | `AnalysisProvider` | always | `await provider.aclose()` |
| `db_engine` | `AsyncEngine \| None` | if `DATABASE_URL` | `await engine.dispose()` |
| `db_sessionmaker` | `async_sessionmaker \| None` | if `DATABASE_URL` | — |
| `token_service` | `TokenService \| None` | if `JWT_SECRET` | — |
| `plans` | `dict[str, Plan]` | always | — |
| `billing_provider` | `BillingProvider \| None` | if `STRIPE_WEBHOOK_SECRET` | — |
| `job_runner` | `JobRunner` | always | `await job_runner.aclose()` (drains in‑flight jobs) |
| `http_client` | `httpx.AsyncClient` | always | `await http_client.aclose()` |
| `embedding_provider` | `EmbeddingProvider \| None` | always (defensive) | `await embedding_provider.aclose()` (if built) |

## `lifespan` (teardown)

```python
@asynccontextmanager
async def lifespan(app):
    logger.info("Starting ...")
    yield
    await app.state.job_runner.aclose()      # drain in-flight background jobs (M3.3a)
    await app.state.http_client.aclose()     # close outbound webhook client (M3.3b)
    await app.state.provider.aclose()
    await app.state.cache.aclose()
    if app.state.db_engine is not None: await app.state.db_engine.dispose()
    logger.info("Shutting down ...")
```

`create_app` owns construction; `lifespan` owns teardown. Nothing else disposes these. (Note: httpx `ASGITransport` in tests doesn't trigger lifespan by default; lifespan is tested by driving the context manager directly.)

## The dependency graph (`app/dependencies.py`)

```
get_app_settings ─────────────► Settings (app.state.settings)
get_analysis_provider ────────► AnalysisProvider (app.state.provider)
get_cache ────────────────────► Cache (app.state.cache)
get_db_sessionmaker ──────────► async_sessionmaker | None

get_db_session ──(sessionmaker)──► yields AsyncSession (commit/rollback; 503 if None)
get_token_service ────────────► TokenService (503 if None)
get_optional_token_service ───► TokenService | None   (no 503)

get_user_store ──(session)────► SqlAlchemyUserStore
get_org_store ──(session)─────► SqlAlchemyOrgStore
get_api_key_store ──(session)─► SqlAlchemyApiKeyStore

get_auth_service ──(user_store, token_service)──► AuthService
get_org_service ──(org_store)─► OrganizationService
get_api_key_service ──(api_key_store)──► ApiKeyService

get_current_user ──(bearer, auth_service)──► User (401)
require_org_membership ──(org_id, current_user, org_service)──► Membership (403)
get_tenant_context ──(api_key_service, org_store, user_store, optional_token_service, settings)──► TenantContext
```

**Authorization factories (M2.4):** `require_role(*roles)` (layered on `require_org_membership`, 403) and `require_scope(*scopes)` (layered on `get_tenant_context`, gates API‑key principals) return dependency callables; build them as module‑level singletons (`Depends(factory(...))` trips ruff B008).

**Post‑M2.3 dependencies (added M2.5a → M4.1):**
```
require_quota ──(require_scope("analyze") → context, org_store, billing_service)──► TenantContext (402 over cap)   # M2.5a
get_usage_store / get_billing_service ─────► BillingService (metering + quota)                                     # M2.5a
get_billing_provider / get_webhook_event_store / get_webhook_service ─► WebhookService (Stripe inbound)            # M2.5b
get_ticket_store ──(session)──► TicketStore ; get_feedback_store ──(session)──► FeedbackStore                       # M3.1 / M3.2
get_batch_job_store (sessionmaker, 503) / get_job_runner (app.state) / get_batch_service ─► BatchService            # M3.3a
get_webhook_store (sessionmaker, 503) / get_webhook_dispatcher (app.state; NoOp without DB) ─► WebhookDispatcher     # M3.3b
get_routing_rule_store / get_sla_policy_store ──(session)──► routing/SLA stores                                     # M3.4a
get_analytics_store ──(session)──► AnalyticsStore ; get_analytics_service ─► AnalyticsService                       # M4.1
get_vector_store ──(session)──► VectorStore ; get_embedding_provider (app.state, 503) ; get_rag_service ─► RagService # M5.2
get_context_retriever ──(app.state.embedding_provider, sessionmaker, settings)──► ContextRetriever | None (RAG grounding) # M5.2
get_action_store / get_audit_store ──(session)──► ActionStore / AuditStore                                            # M5.3
get_action_suggester ──(app.state.provider, settings)──► ActionSuggester ; get_action_service ─► ActionService        # M5.3
require_approver ──(get_tenant_context, org_store)──► TenantContext (403 unless an owner/admin **user**)              # M5.3
```

**Two store‑binding styles:** most stores are **request‑scoped** (bound to `get_db_session`, committed at request end). A few must be visible to **background tasks** and so wrap the **sessionmaker** (own, self‑committing sessions): `BatchJobStore`, `WebhookStore`, `WebhookDeliveryStore` (see [08_persistence.md](08_persistence.md)).

**Caching:** FastAPI caches a dependency's result per request, so `get_db_session` is resolved **once** and all request‑scoped stores share that single session.

## Why globals are avoided

The pre‑M1.0 code cached a global `AsyncOpenAI` client and settings at import. Problems: couldn't test with different settings, couldn't close the client, `get_provider(settings)` silently ignored its argument once cached (a real footgun). M1.0 removed the global provider singleton entirely — the app owns lifecycle. Do not reintroduce import‑time stateful singletons.

## How to add a dependency

1. If it's a shared resource: build it in `create_app` → `app.state.x`; dispose in `lifespan`; add `get_x(request) -> X` returning `request.app.state.x` (annotate the local to satisfy `mypy`'s `warn_return_any` — `app.state` is `Any`).
2. If it's request‑scoped (needs a session): depend on `get_db_session`.
3. If auth is optional for the path: use `get_optional_token_service` (returns `None`, no 503).
4. Expose it via `Depends`; in tests, override with `app.dependency_overrides[get_x] = lambda: fake`.

See [developer_guide.md](developer_guide.md) for full recipes.

## What must NEVER change

- `create_app` builds / `lifespan` disposes — the ownership split.
- No import‑time stateful singletons.
- Ports injected via `Depends` (so tests override them) — this is the whole reason the HTTP surface is testable without infra.
