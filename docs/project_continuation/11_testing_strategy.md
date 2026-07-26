# 11 — Testing Strategy

Tests are a first‑class part of the architecture — the abstractions exist partly *so that* the whole HTTP surface can be tested without live infrastructure. **Backend: 855 tests passing, 20 skipped (DB‑integration + the opt‑in live eval), 95.29% coverage**, gate at **90%** (`fail_under` in `pyproject.toml`), across **41 test modules** under `tests/` (as of M5.3). The M5.1 **eval harness** follows the same DNA — `run_eval` takes any `AnalysisProvider`, so `tests/test_eval.py` scores a **fake provider** deterministically with no live LLM (a real‑provider run is a `skipif` opt‑in gated on `RUN_LIVE_EVAL` + a key). **Frontend (`web/`): 41 vitest unit tests across 7 test files** (pure Next.js‑free modules — error‑envelope parsing, open‑redirect guard, cookie config, analytics/tickets query helpers, admin parsers); gates are `pnpm lint` + `pnpm typecheck` + `pnpm test` + `pnpm build`, run in a separate `web-ci.yml` (see [22_frontend.md](22_frontend.md)). The rest of this document covers the **backend** strategy.

## Philosophy

1. **No live infra required for the default suite.** Postgres/Redis/OpenAI are never contacted. This keeps tests fast, deterministic, and runnable anywhere.
2. **Test through the real app where it matters.** Route tests hit the actual FastAPI app via `httpx.ASGITransport`, overriding only the *ports* (stores, provider, cache, token service). This exercises real routing, validation, middleware, error envelopes, and DI wiring.
3. **Ports + fakes.** Every external dependency is a Protocol with an in‑memory fake, so services and routes run against realistic behavior with zero mocking of internals.
4. **Mock the session only for store unit tests.** SQLAlchemy stores are unit‑tested with a `MagicMock` session (asserting `execute/add/flush` usage), covering the store code without a DB.
5. **`skipif` for real infra.** Genuine DB round‑trips are integration tests guarded by `@pytest.mark.skipif(not os.environ.get("DATABASE_URL"))`. They're written and correct but skipped in the dev env (~16 skips) — they run when Postgres is available.
6. **Optional SDKs are faked, not required.** The `stripe` SDK is exercised by injecting a fake `stripe` module into `sys.modules` (M2.5b); outbound webhook HTTP uses a fake httpx client (M3.3b); async jobs use an **inline** `JobRunner` for deterministic completion (M3.3a).

## The fakes (reused across tests)

- `FakeUserStore` — `tests/test_auth.py`; `FakeOrgStore` (has `get`/`get_membership`), `FakeApiKeyStore` — `tests/test_tenancy_service.py`.
- `FakeUsageStore` — `tests/test_billing.py`; `FakeBillingProvider`/`FakeWebhookEventStore` — `tests/test_billing_webhooks.py`.
- `FakeTicketStore`, `_ticket(...)` builder, `ORG` — `tests/test_tickets.py` (reused widely); `FakeFeedbackStore` — `tests/test_feedback.py`.
- `FakeBatchJobStore` + `InlineJobRunner` — `tests/test_batch.py` (reused by channels); `FakeWebhookStore`/`FakeDeliveryStore`/`FakeHttpClient`/`RecordingDispatcher` — `tests/test_webhooks.py`.
- `FakeRuleStore`/`FakePolicyStore` — `tests/test_routing.py`; `FakeAnalyticsStore` — `tests/test_analytics.py`.
- `FakeVectorStore` + the keyless `hash` embedding provider — `tests/test_rag.py` (M5.2: RAG runs fully offline, no LLM).
- `FakeActionStore`/`FakeAuditStore`/`FakeDispatcher` — `tests/test_actions.py` (reused by `tests/test_actions_routes.py`); the rule-based suggester keeps the agentic flow deterministic and LLM-free (M5.3).
- Mock `AnalysisProvider` — a `MagicMock` with `.analyze` `AsyncMock` returning `AnalysisResult(...)` and `.name`/`.model` set (so metric labels are clean).
- Injectable `clock` for `TTLCache`; `AsyncMock` for `asyncio.sleep` (tenacity retry counts).
- **Sessionmaker‑backed store tests** use a `_FakeSession` async‑context stand‑in wrapped by `MagicMock(return_value=session)` (see `tests/test_batch.py`, `tests/test_webhooks.py`).

## Fixtures (`tests/conftest.py`)

- `clear_cache` (autouse) — clears the app cache before/after each test (guarded `getattr(..., "clear")` so a Redis env doesn't break).
- `client` — `AsyncClient(ASGITransport(app))`.
- `override_provider`, `override_db_sessionmaker`, `override_cache` — set `app.dependency_overrides[...]` and pop on teardown.

Auth/tenancy route tests define their own fixtures that override the stores + token service with shared fake instances (a single instance per test so state persists across requests).

## Async test setup (important quirk)

- `pytest.ini` sets `asyncio_mode = auto`; tests use `@pytest.mark.anyio`.
- **anyio runs each async test on both `asyncio` and `trio` backends** if trio is installed. Trio **is** present locally but **not** in `requirements*.txt`, so **CI runs only the asyncio backend**. Result: locally you see `[asyncio]`/`[trio]` params (test count doubles for async tests); CI runs fewer. This is a known inconsistency — if you pin the backend, do it deliberately and update both.

## The `Settings` kwarg gotcha (must know)

`Settings(_env_file=None, ...)` in tests must use **canonical `llm_*` names**, never the `OPENAI_*` aliases as kwargs — when `OPENAI_API_KEY` is present in the environment (as CI sets it), passing `openai_api_key=` raises `extra_forbidden`. Always run the suite **both** with and without `OPENAI_API_KEY` set before trusting green (see [04_ai_provider_system.md](04_ai_provider_system.md)). The standard verification command pair:
```
venv/Scripts/python -m pytest -q
OPENAI_API_KEY=sk-ci venv/Scripts/python -m pytest -q
```

## Coverage philosophy

- Gate at 90% via `[tool.coverage.report] fail_under = 90`.
- Cover **real branches**, not just lines. When a helper had an untested branch (e.g., exception translation, best‑effort swallow, federated auto‑provision), we added a test that exercises the *behavior*.
- Intentionally‑uncovered lines: Protocol `...` stubs, real `AsyncOpenAI`/`Redis` client construction (no live infra), the `_request_id` fallback, lifespan startup logging under `ASGITransport`. Don't chase these.

## What must stay tested (regression‑critical)

- The `/analyze` HTTP contract (status codes, response shape, caching, timing header, error envelope).
- Provider exception **translation** (each `Provider*` mapping) and retry count from settings.
- Best‑effort persistence (a failing sessionmaker still yields 200).
- Cache TTL/expiry/disable; Redis best‑effort degradation.
- Auth: password hash/verify, token decode/expiry/wrong‑type, signup/login/refresh/me, 401/409/422/503, **federated auto‑provisioning**.
- Tenancy: API key gen/hash, create/authenticate/revoke, **cross‑tenant 403**, revoked‑key 401, tenant resolution (API key vs JWT, single/multi org).
- **RBAC/quota:** `require_role`/`require_scope` (403), `require_quota` **402** over cap; metering best‑effort/no‑op without a DB.
- **Billing:** plan registry + `check_quota`; Stripe webhook idempotency + signature‑error 400 + plan sync (fake `stripe`).
- **Tickets/feedback/routing/channels/analytics:** tenant‑isolation 404 (cross‑org), re‑analyze reuses `run_analysis`, feedback target resolution, webhook signing + bounded retries (best‑effort), routing engine first‑match + SLA, CSV parse errors → 400, analytics window math + SQL aggregation.

## How to write a new test

- **Route test:** use the `client` fixture; override the relevant ports with fakes; assert status + body + side effects. See `tests/test_auth_routes.py`, `tests/test_tenancy_routes.py`.
- **Service/unit test:** construct the service with fake stores; assert behavior and raised domain errors.
- **Store test (no DB):** `MagicMock` session with `execute`=`AsyncMock(return_value=result)` where `result.scalars().first()` is set; assert `add/flush` calls. See `tests/test_auth.py::TestSqlAlchemyUserStore`, `tests/test_tenancy_service.py::TestSqlAlchemyStores`.
- **Integration (DB):** guard with `skipif(not DATABASE_URL)`, `create_all` then round‑trip. See `tests/test_db.py`, `tests/test_tenancy.py`.

## How CI should evolve

- Current CI (`.github/workflows/ci.yml`): ruff check, ruff format --check, mypy, pytest --cov, on Python 3.12, with a dummy `OPENAI_API_KEY`.
- **Next:** add a `services: postgres` (and `redis`) job so the `skipif` integration tests run and Alembic `upgrade head` is exercised end‑to‑end. Consider `alembic check` (model↔migration drift) once Postgres is in CI.
- Consider pinning the async backend or adding trio to dev deps to make local == CI.
