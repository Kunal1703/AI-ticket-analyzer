# 02 — Request Flows

Concrete end‑to‑end flows. Middleware order (outermost first) is always:
`RequestContextMiddleware` → `request_timing_middleware` → `SecurityHeadersMiddleware` → `CORSMiddleware` → router. Every response gets `X-Request-ID`, `X-Process-Time-Ms`, and security headers; every error uses the envelope.

> **Why `RequestContextMiddleware` is outermost:** it sets the `request_id` contextvar *before* the timing middleware's access‑log line runs, so that line is correlated too. (This ordering was a deliberate fix in M1.5.)

## `POST /analyze` (the core flow)

```
Client ──POST /analyze {"ticket": "..."}──▶ FastAPI
  │
  ├─ Pydantic validates TicketRequest (min_length=1, max_length=5000)
  │     └─ invalid → 422 {"error": {"code":"validation_error", ...}}
  │
  ├─ ticket_text = payload.ticket.strip()
  ├─ key = cache_key(ticket_text)              # sha256(strip().lower())
  ├─ cached = await cache.get(key)
  │     ├─ HIT  → metrics.record_cache("hit")  → return cached (200)
  │     └─ MISS → metrics.record_cache("miss")
  │
  ├─ try: result = await provider.analyze(ticket_text)   # AnalysisResult
  │     ├─ ProviderTimeoutError    → record_analysis(error) → 504
  │     ├─ ProviderRateLimitError  → record_analysis(error) → 429
  │     ├─ ProviderResponseError   → record_analysis(error) → 502 "Invalid AI response"
  │     └─ ProviderError (base)    → record_analysis(error) → 502 "unavailable"
  │
  ├─ analysis = result.analysis
  ├─ metrics.record_analysis(provider.name, "success")
  ├─ if result.usage: metrics.record_tokens(provider.name, prompt, completion)
  ├─ await cache.set(key, analysis)                         # best-effort
  ├─ await persist_analysis(sessionmaker, ..., model=provider.model, usage=result.usage)
  │        └─ best-effort: no-op if no DB; swallow+log on failure
  └─ return analysis (200, response_model=TicketAnalysis)
```

Inside `provider.analyze` (OpenAIProvider): build prompts → `client.beta.chat.completions.parse(model, messages, response_format=TicketAnalysis, temperature)` wrapped in a `tenacity` `AsyncRetrying` (attempts = `llm_max_retries`, exponential backoff on connection/timeout/rate‑limit). Refusal / unparseable → `ValueError` → translated to `ProviderResponseError`. OpenAI SDK exceptions → translated to the matching `Provider*` error. Token usage extracted best‑effort into `TokenUsage`.

**Note:** `/analyze` is the **legacy root‑path** endpoint — it is *not* tenant‑scoped and does *not* require auth. M2.4 introduces a tenant‑scoped `/v1/analyze` alongside it (the legacy one stays for back‑compat). See [14_remaining_roadmap.md](14_remaining_roadmap.md).

## `GET /health` (liveness)

Pure liveness. Returns `{"status":"healthy","version": settings.app_version}` (200). **No dependency checks** — a health probe must not fail because Postgres is down. Contrast with `/ready`.

## `GET /ready` (readiness)

```
GET /ready ─▶ check_readiness(sessionmaker, cache, provider)
  ├─ database: SELECT 1 if configured, else "not_configured"
  ├─ cache:    await cache.ping()  (in-memory → True; Redis → PING)
  ├─ provider: "ok" if configured  (NO LLM call — see below)
  └─ ready = all statuses in {"ok","not_configured"}
       ├─ ready     → 200 {"status":"ready","checks":{...}}
       └─ not ready → 503 {"status":"not_ready","checks":{...}}
```

**Why the provider is not pinged:** a readiness probe must be cheap and must not depend on a paid/rate‑limited third party. If OpenAI blips, the pod should stay in rotation; `/analyze` returns a correct 502 instead. This is a deliberate decision — do not add an LLM call to `/ready`.

## Authentication — signup / login (JWT issuance)

```
POST /v1/auth/signup {email, password, name?}
  └─ get_auth_service → AuthService(user_store, token_service, settings)
       ├─ store.get_by_email(email)  → exists? → 409
       ├─ store.create(email, hash_password(password), name)   # Argon2
       └─ token_service.issue_pair(str(user.id)) → TokenResponse (201)

POST /v1/auth/login {email, password}
  └─ AuthService.login({"email","password"}, provider="local")
       ├─ build_auth_provider("local", ctx) → LocalAuthProvider
       ├─ provider.authenticate(creds) → AuthenticatedIdentity   (401 on bad creds)
       ├─ _resolve_user(identity, auto_provision=False) → User
       └─ token_service.issue_pair(...) → TokenResponse (200)
```

Requires `JWT_SECRET` **and** `DATABASE_URL`; otherwise the underlying dependencies return **503**. Passwords are Argon2‑hashed. Detail: [05_authentication.md](05_authentication.md).

## JWT flow (`GET /v1/auth/me` and any protected route)

```
Authorization: Bearer <access_jwt>
  └─ get_current_user
       ├─ HTTPBearer extracts credentials (missing → 401)
       ├─ AuthService.get_current_user(token)
       │     ├─ token_service.decode(token, expected_type="access")  # TokenError if bad/expired/wrong-type
       │     └─ user_store.get_by_id(sub) → User (None → InvalidCredentialsError)
       └─ catches (AuthError, TokenError) → 401
```

`POST /v1/auth/refresh {refresh_token}` decodes an `expected_type="refresh"` token, re‑loads the user, and issues a new pair. **Refresh tokens are stateless** (no server‑side revocation) — a known limitation, see [05_authentication.md](05_authentication.md).

## API key flow + tenant resolution

```
X-API-Key: atk_...                (machine/tenant principal)
  └─ get_tenant_context
       ├─ api_key_service.authenticate(plaintext)
       │     ├─ store.get_active_by_hash(sha256(plaintext))  # revoked → None → 401
       │     └─ store.touch(key)  (last_used_at)
       └─ TenantContext(org_id=key.org_id, principal_type="api_key", scopes=...)

Authorization: Bearer <jwt>        (user principal, no X-API-Key)
  └─ get_tenant_context (only if token_service configured)
       ├─ AuthService.get_current_user(token) → User
       └─ _tenant_context_for_user:
            ├─ orgs = org_store.list_for_user(user.id)
            ├─ none            → 403
            ├─ X-Organization-Id header → validate membership → context (403 if not member)
            ├─ exactly one org → context
            └─ multiple, no header → 400 "set X-Organization-Id"
```

**Why API‑key resolution uses `get_optional_token_service` (not `get_token_service`):** an API‑key call must not require `JWT_SECRET`. If `get_tenant_context` depended on `get_token_service`, an API‑key request would 503 when auth isn't configured. This is subtle and important — do not "simplify" it.

Org‑scoped management routes (`POST /v1/orgs/{org_id}/api-keys`, etc.) use `require_org_membership` — a dependency that reads `org_id` from the path and 403s if the current user isn't a member. That is the tenant‑isolation guard. Detail: [06_tenancy.md](06_tenancy.md).

## Persistence flow (best‑effort)

```
/analyze (cache miss, success) ─▶ persist_analysis(sessionmaker, ...)
  ├─ sessionmaker is None (no DATABASE_URL) → return  (no-op)
  └─ else:
       async with sessionmaker() as session:
         ├─ get_or_create_ticket(session, raw_text, text_hash)   # dedupe by hash
         ├─ add_analysis(session, ticket, analysis, model, token_usage)  # versioned
         └─ session.commit()
       except Exception: log.exception(...)   # SWALLOWED — never breaks the response
```

The route‑scoped session used by **auth/tenancy** routes is different: `get_db_session` yields a session and commits at the *end of the request* (rollback on error). Detail: [08_persistence.md](08_persistence.md).

## Cache flow

`get`/`set` are async (Redis is async I/O). In‑memory `TTLCache` uses a monotonic clock + `OrderedDict` LRU with lazy expiry. `RedisCache` stores `TicketAnalysis.model_dump_json()` under `analysis:<hash>` with native TTL (`ex=`); any Redis error degrades to a miss (`get`) or skipped write (`set`). Detail: [07_cache.md](07_cache.md).

## Database flow

The app never opens a connection unless a DB is configured. Engine creation is lazy (`create_async_engine` opens no socket). `postgresql+psycopg://` serves both the async app engine and the sync Alembic engine. Detail: [03_database.md](03_database.md), [08_persistence.md](08_persistence.md).

## LLM flow (provider internals)

See [04_ai_provider_system.md](04_ai_provider_system.md). Key point for request handling: `analyze` returns an `AnalysisResult(analysis, usage)`. The `analysis` is the API response and the cached value (a plain `TicketAnalysis`); `usage` flows to metrics + persistence only. This split kept the response/cache shape unchanged when token capture was added in M1.4.
