# Developer Guide (practical recipes)

Concrete "how to add X" steps that follow the project's conventions. Always keep it green (`ruff` + `mypy` + `pytest`, run pytest **with and without `OPENAI_API_KEY`**). See [15_handoff.md](15_handoff.md) for the checklists and [12_design_decisions.md](12_design_decisions.md) for invariants.

## Coding standards

- **Python 3.12+ style:** builtin generics (`list[str]`, `X | None`), `collections.abc` imports, f‑strings. mypy is strict‑ish (`disallow_untyped_defs`, `warn_return_any`) — annotate everything; when reading `app.state.x` (typed `Any`), assign to an annotated local before returning.
- **ruff** does lint + format (line length 100, rules `E,W,F,I,UP,B,C4,SIM`). `Depends()` in defaults is allowed (`flake8-bugbear.extend-immutable-calls`). Run `ruff check --fix .` then `ruff format .`.
- **Docstrings** on modules/classes/public functions; explain *why*, not just *what*.
- **Errors translate at boundaries:** raise domain errors (`Provider*`, `AuthError`, `TenantError`) from providers/services; map to HTTP in routes/deps.
- **Never** import a concrete SDK/store in a route or business‑logic module — depend on the abstraction.

## Add an AI provider (OpenAI‑compatible → trivial)

1. If OpenAI‑compatible (Groq/Together/OpenRouter/custom): just add a `_PROVIDERS` entry in `app/ai/factory.py` with `default_base_url` (and `requires_api_key`/`default_model` as needed). Done — no new class.
2. If a **different** API (Anthropic/Gemini): add the SDK to `requirements.txt`; create `app/ai/<name>_provider.py` implementing `AnalysisProvider` (`name`, `model`, `analyze -> AnalysisResult`, `aclose`), **translating its errors into `Provider*`** and its structured‑output mechanism into `TicketAnalysis`; add a `_PROVIDERS[name] = ProviderSpec(<Provider>, ...)` entry.
3. Tests: translation of each error type, success, refusal/unparseable, retry count. Pattern: `tests/test_openai_provider.py`.
4. Docs: [04_ai_provider_system.md](04_ai_provider_system.md).

## Add an authentication provider (OAuth/OIDC/SSO)

1. Implement `AuthProvider.authenticate(credentials) -> AuthenticatedIdentity` in `app/auth/<name>_provider.py` (do the token/userinfo exchange; set `auto_provision=True`), translating failures into `AuthError`.
2. Register it in `app/auth/factory.py::_PROVIDERS` (lambda over `AuthProviderContext`).
3. Add a small router with the provider's **redirect + callback** routes that call `AuthService.login(provider="<name>", credentials=...)`. Reuse `TokenService`/`get_current_user` unchanged.
4. Tests: authenticate success/failure; a route test with a fake provider proving auto‑provision. Pattern: `tests/test_auth.py`.
5. Docs: [05_authentication.md](05_authentication.md).

## Add a repository / store

1. If it's a new port: define a `Protocol` in the domain's `base.py` (e.g., `app/tenancy/base.py`) returning ORM entities.
2. Implement `SqlAlchemy<Name>Store(session)` in `app/db/<name>_store.py` (async `select`/`add`/`flush`).
3. Add a dependency `get_<name>_store(session=Depends(get_db_session)) -> <Port>` in `app/dependencies.py`.
4. Tests: mocked‑session unit tests (assert `execute/add/flush`) + an in‑memory fake for route/service tests. Patterns: `app/db/user_store.py`, `tests/test_auth.py::TestSqlAlchemyUserStore`.

## Add a database model + migration

1. Add the ORM class to `app/db/models.py` (or a new `app/db/models/` module if you split the package). Use PG types (`UUID(as_uuid=True)`, `JSONB`), the naming convention, `server_default=func.now()` for timestamps, and appropriate FKs/indexes/constraints.
2. Create a **new** migration `alembic/versions/000N_<desc>.py` with `down_revision` = current head; hand‑write `upgrade`/`downgrade` using `op.f("...")` convention names to match the ORM. **Never edit a shipped migration.**
3. Verify offline: `DATABASE_URL=postgresql+psycopg://u:p@localhost:5433/db alembic upgrade head --sql` — inspect the emitted DDL.
4. Tests: metadata registration + a `skipif(not DATABASE_URL)` round‑trip. Pattern: `tests/test_tenancy.py`.
5. Docs: [03_database.md](03_database.md).

## Add an endpoint

1. Put it on an existing router (`app/main.py::router`, `app/auth/routes.py`, `app/tenancy/routes.py`) or a new router included in `create_app`.
2. Use Pydantic request/response models in `app/models.py` (`response_model=...`). Validation errors → 422 envelope automatically.
3. Guard with the right dependency: `get_current_user` (user), `get_tenant_context` (tenant, key or JWT), `require_org_membership` (org‑scoped), or none (public like `/analyze`).
4. Map domain errors to `HTTPException` (they flow through the envelope handler).
5. Tests: route test via the `client` fixture with overridden ports. Patterns: `tests/test_auth_routes.py`, `tests/test_tenancy_routes.py`.

## Add a dependency

- Shared resource: build in `create_app` → `app.state.x`; dispose in `lifespan`; add `get_x(request) -> X` returning `request.app.state.x` (annotate the local for mypy).
- Request‑scoped (needs a session): depend on `get_db_session`.
- Optional‑auth path: use `get_optional_token_service` (returns `None`, no 503).
- Expose via `Depends`; override in tests with `app.dependency_overrides`. Docs: [10_dependency_injection.md](10_dependency_injection.md).

## Add middleware

- Prefer a `BaseHTTPMiddleware` subclass in `app/core/middleware.py`. Register it in `create_app`. **Mind the order** — `RequestContextMiddleware` must remain outermost so logs are correlated (see [09_observability.md](09_observability.md)). If a response must be produced even outside the middleware stack (e.g., 500s), also set headers in the error handler (as `build_error_response` does).

## Add a cache backend

- Implement the async `Cache` protocol (`get/set/ping/aclose`) in `app/cache/<name>.py`; add a branch to `build_cache` in `app/cache/factory.py`. Keep it **best‑effort** (errors → miss / no‑op). Tests: mocked client (serialization, TTL, error degradation). Docs: [07_cache.md](07_cache.md).

## Add an embeddings backend / a RAG consumer (M5.2)

- **Embeddings backend:** if OpenAI‑compatible, add a `_EMBEDDING_PROVIDERS` entry
  in `app/embeddings/factory.py` (base_url/model/key‑requirement). If a different
  API, implement `EmbeddingProvider` (`name`, `model`, `embed`, `aclose`),
  translating its errors into the `Embedding*` hierarchy, and register it. Tests:
  translation + success, mirroring `tests/test_embeddings.py`. Keep a keyless
  offline path working (the `hash` provider is the default for tests/local).
- **RAG document source / retrieval consumer:** reuse the `VectorStore` port +
  `RagService`; scope every query by `organization_id`. Analyze‑path retrieval
  must stay **best‑effort** (own session, swallow errors → no context) — build it
  via `build_context_retriever` and pass it into `run_analysis(retrieve_context=…)`.
  Never add a second embed/retrieve path. Docs: [24_rag.md](24_rag.md).

## Add an agentic action type / suggester (M5.3)

- **Action type:** add an `ActionType` value, implement an `ActionHandler`
  (`action_type`, `is_destructive`, `execute(action, ctx) -> ActionResult`) in
  `app/actions/handlers.py`, and register it in `build_action_handlers`. If it is
  outward‑facing/irreversible, add it to `DESTRUCTIVE_ACTIONS` (`app/actions/base.py`)
  — the one source of truth — and have the handler **dispatch a webhook** rather
  than perform the external effect itself. The approval gate, state machine, and
  audit trail then apply automatically. Tests: handler behavior + a
  service/route flow (`tests/test_actions*.py`).
- **Suggester:** implement `ActionSuggester` (`name`, `actor_type`, `suggest`) and
  add a branch to `build_action_suggester`. A suggester only *proposes* — never
  change the approve/execute path. Keep an offline‑testable default.
- **Never** let anything execute without an explicit human approve → execute, and
  never auto‑execute a destructive action. Docs: [25_actions.md](25_actions.md).

## Add observability

- **Metric:** add a `Counter`/`Histogram` in `app/observability/metrics.py` + a `record_*` helper; call it from the relevant layer. Keep labels low‑cardinality (route templates, bounded enums).
- **Log field:** it's already correlated with `request_id`; use `logger.info("... %s", value)` (JSON formatter includes `request_id`).
- **Readiness check:** extend `check_readiness` in `app/readiness.py` (keep it cheap — no third‑party calls). Docs: [09_observability.md](09_observability.md).

## Add tests (quick reference)

- Route: `client` fixture + `app.dependency_overrides[port] = lambda: fake`.
- Service/unit: construct with fakes; assert behavior + raised domain errors.
- Store: `MagicMock` session (`execute=AsyncMock(return_value=result)`, `result.scalars().first()=...`).
- Integration: `@pytest.mark.skipif(not os.environ.get("DATABASE_URL"))`.
- Async tests: `@pytest.mark.anyio`. Use canonical `llm_*` kwargs when building `Settings` (never `openai_*` kwargs). Docs: [11_testing_strategy.md](11_testing_strategy.md).

## Commit conventions

- Conventional‑style messages (`feat:`, `fix:`, `chore:`, `docs:`). End the message with:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Stage only the intended files (the tree may carry unrelated uncommitted edits). Don't push unless asked. Don't commit unless asked (review‑first workflow).
