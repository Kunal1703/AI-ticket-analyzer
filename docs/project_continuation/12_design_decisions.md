# 12 — Design Decisions (the canonical list)

The most important document after the handoff. For each decision: **what**, **why**, **benefits**, **tradeoffs**, **NEVER change**. If you're about to do something that contradicts a "NEVER change", stop and reconsider.

---

### D1 — Application factory (`create_app`) + `app.state`, no import‑time singletons
- **Why:** deterministic, testable startup; explicit resource lifecycle; the old global OpenAI client/settings couldn't be tested or closed and had a silent‑ignore footgun.
- **Benefits:** per‑test isolated apps; clean teardown; overridable dependencies.
- **Tradeoffs:** a little more ceremony than module‑level globals.
- **NEVER change:** don't reintroduce import‑time stateful singletons; `create_app` builds, `lifespan` disposes. (M1.0) See [10_dependency_injection.md](10_dependency_injection.md).

### D2 — Dependency Injection via `Depends` + Protocol ports
- **Why:** decouple business logic from concrete implementations; make everything overridable in tests.
- **Benefits:** the whole HTTP surface is testable with in‑memory fakes (no DB/Redis/LLM).
- **Tradeoffs:** more indirection; must remember to annotate `app.state` reads for mypy.
- **NEVER change:** stores/cache/provider are injected, not imported directly by routes/services.

### D3 — AI provider abstraction + provider‑agnostic error hierarchy
- **Why:** business logic must not depend on any LLM SDK; adding a backend must not touch routes/mapping.
- **Benefits:** OpenAI + Groq/Together/OpenRouter/Ollama/custom work today; Anthropic/Gemini are registry‑ready.
- **Tradeoffs:** one `OpenAIProvider` serves many backends (less per‑provider clarity); `beta.parse` SDK surface.
- **NEVER change:** the `Provider*` exception hierarchy and the rule that providers translate SDK errors into it; the route catches only `Provider*`. (M0.5 + provider‑agnostic refactor) See [04_ai_provider_system.md](04_ai_provider_system.md).

### D4 — `ProviderConfig` (neutral) instead of passing `Settings` to providers
- **Why:** providers depend only on what they need; decoupled from app config; trivially unit‑testable.
- **NEVER change:** providers take `ProviderConfig`, not `Settings`.

### D5 — Generic `LLM_*` settings with `OPENAI_*` **environment** aliases
- **Why:** provider‑agnostic config while preserving back‑compat for existing `.env`/CI using `OPENAI_*`.
- **Tradeoffs:** the alias works for env vars but **not** as an init kwarg when the env var is also set (`extra_forbidden`).
- **NEVER change:** tests must use canonical `llm_*` kwargs; keep the `OPENAI_*` env aliases for back‑compat. (provider‑agnostic refactor) See [04_ai_provider_system.md](04_ai_provider_system.md), [11_testing_strategy.md](11_testing_strategy.md).

### D6 — Graceful degradation for all optional subsystems (DB, Redis, auth)
- **Why:** the app must boot and serve `/analyze` with zero infra; production adds infra incrementally.
- **Benefits:** trivial local dev; resilient to a dependency being down.
- **Tradeoffs:** more `None`‑checks / 503 paths.
- **NEVER change:** the app runs without `DATABASE_URL`/`REDIS_URL`/`JWT_SECRET`; those endpoints return clear 503s when required but unset.

### D7 — Best‑effort persistence (never breaks `/analyze`)
- **Why:** analysis is the product; a persistence/DB failure must not fail the response.
- **Benefits:** resilience; persistence can be added without risk to the core path.
- **Tradeoffs:** silent data loss on DB failure (logged); `text_hash` not unique (possible dup tickets under concurrency).
- **NEVER change (for the legacy `/analyze`):** `persist_analysis` swallows exceptions and no‑ops without a DB. (M1.2) See [08_persistence.md](08_persistence.md).

### D8 — Best‑effort cache + async `Cache` protocol
- **Why:** Redis is async I/O; a cache failure must degrade to a miss, never break the request.
- **Tradeoffs:** in‑memory methods are `async` though they don't await.
- **NEVER change:** the `Cache` protocol shape and best‑effort semantics; `sha256(strip().lower())` key. (M1.3) See [07_cache.md](07_cache.md).

### D9 — Standardized error envelope with **stable** code slugs
- **Why:** consistent machine‑readable errors with correlation ids.
- **Tradeoffs:** error body shape differs from FastAPI default (`detail`).
- **NEVER change:** `{"error": {"code","message","request_id","details"?}}`; codes come from an explicit stable map, **not** `HTTPStatus.phrase` (Python 3.13 renamed 422 → a real bug we hit). Status codes are preserved. (M0.4) See [09_observability.md](09_observability.md), [01_architecture.md](01_architecture.md).

### D10 — Request‑ID correlation via middleware + contextvar + log filter
- **Why:** trace a request across all logs.
- **NEVER change:** `RequestContextMiddleware` outermost; `X-Request-ID` echoed; JSON logs include `request_id`. (M0.4/M1.4)

### D11 — Liveness (`/health`) vs Readiness (`/ready`); readiness does NOT call the LLM
- **Why:** probes must be cheap; a third‑party (LLM) outage must not remove the pod from rotation.
- **NEVER change:** `/health` has no dependency checks; `/ready` checks DB/cache only, never the provider. (M1.5) See [02_request_flow.md](02_request_flow.md).

### D12 — Provider‑agnostic authentication (identity vs session split)
- **Why:** local email/password now; OAuth/OIDC/SSO later with no business‑logic change.
- **Benefits:** federated auto‑provisioning works via `AuthService._resolve_user` (tested with a fake provider).
- **NEVER change:** providers return **identities**; `AuthService`/`TokenService` own sessions; `get_current_user` catches `AuthError` **and** `TokenError`. (M2.2) See [05_authentication.md](05_authentication.md).

### D13 — Argon2 for passwords, SHA‑256 for API keys
- **Why:** passwords are low‑entropy (need slow KDF); API keys are high‑entropy random tokens (fast hash, indexable lookup).
- **NEVER change:** don't Argon2‑hash API keys (breaks the hash‑lookup) or SHA‑256 passwords.

### D14 — Tenant context abstraction (`TenantContext`) resolved from API key OR JWT
- **Why:** uniform tenant identity regardless of credential type; business logic scopes to a tenant without knowing how it authenticated.
- **NEVER change:** API‑key resolution must **not** require `JWT_SECRET` (uses `get_optional_token_service`); org‑scoped routes enforce membership. (M2.3) See [06_tenancy.md](06_tenancy.md).

### D15 — API keys: hashed storage, plaintext once, scoped, revocable
- **NEVER change:** never store plaintext; return it once; revoked (`revoked_at`) keys stop resolving.

### D16 — Nullable `organization_id` on tickets/analyses (back‑compat)
- **Why:** additive, non‑breaking tenancy columns; legacy/best‑effort rows are `NULL`.
- **NEVER change:** keep them nullable; legacy rows must stay valid even after M2.4 starts populating them. (M2.1)

### D17 — One driver (`psycopg` v3) for async app + sync Alembic; PG‑only schema
- **Why:** a single `postgresql+psycopg://` URL serves both; PG types (UUID/JSONB) are the right fit.
- **Tradeoffs:** no SQLite; DB tests need fakes/mocks or a real Postgres.
- **NEVER change:** don't reintroduce asyncpg/psycopg2; don't dilute the schema for SQLite.

### D18 — Alembic migrations: hand‑written, verified offline, never edited after shipping
- **Why:** deterministic, reviewable, correct without a live DB (offline `--sql`).
- **NEVER change:** add a new migration; never edit `0001`/`0002`/`0003`. Use the naming convention. (M1.1/M1.4/M2.1) See [03_database.md](03_database.md).

### D19 — Milestone discipline (small, green, non‑breaking, review‑first)
- **Why:** the reason the codebase is clean at this feature count; enables safe evolution.
- **NEVER change:** each change compiles green (ruff+mypy+pytest), preserves existing tests/behavior, and is scoped to one capability. Wait for explicit approval before the next milestone; don't auto‑commit unless asked.

### D20 — Structured JSON logs by default; token usage captured + persisted
- **Why:** production observability; cost analytics.
- **Tradeoffs:** JSON console output locally (set `LOG_FORMAT=text`).
- **NEVER change:** `analyze` returns `AnalysisResult` (analysis + usage) so the response/cache shape stays a plain `TicketAnalysis`. (M1.4) See [09_observability.md](09_observability.md).

### D21 — Back‑compat shim `app/openai_client.py`
- **Why:** legacy `from app.openai_client import analyze_ticket` keeps working.
- **NEVER build new features on it** — it's a deprecated facade over `build_provider`.

### D22 — Legacy `/analyze` at root (unauthenticated) stays; `/v1/analyze` added later
- **Why:** preserve the original contract while introducing a tenant‑scoped, authenticated version in M2.4.
- **NEVER change:** don't break or remove the legacy `/analyze` contract without an explicit deprecation milestone.

### D23 — Usage metering + plan quotas: gate at the door (read), meter on the way out (best‑effort)
- **Why:** enforce plan limits before spending LLM budget, but never let metering break the analyze response.
- **How:** `require_quota` (a dependency layered on `require_scope("analyze")`) checks the org's plan quota via a **request‑scoped** session **before** the LLM call → **402** (`payment_required`) when at/over cap. `record_analysis_usage` writes one `usage_events` row via its **own** session, best‑effort (swallows errors), **after** a successful cache‑miss analysis — mirroring `persist_analysis`. Cache hits aren't metered; the legacy `/analyze` is neither metered nor limited (D22).
- **Config:** plan limits live in a **configurable** registry (`app/billing/plans.py`) with **placeholder** defaults, overridable via `Settings.plan_monthly_analysis_limits`. `get_plan` fails safe to the conservative default for unknown plans.
- **NEVER change:** legacy `/analyze` stays unmetered/unlimited; metering stays best‑effort (own session); enforcement stays before the provider call; `usage_events.organization_id` is NOT NULL; 402 = plan cap, 429 = provider rate limit. (M2.5a) See [16_billing.md](16_billing.md).

### D24 — Provider‑agnostic billing + idempotent, signature‑verified webhooks (Stripe SDK stays behind the port)
- **Why:** keep the Stripe SDK out of routes/services (same rule as the LLM/auth SDKs), and make webhook processing safe against replays and forged payloads.
- **How:** a `BillingProvider` ABC + registry/factory (`app/billing/provider.py`) turns a raw webhook into a neutral `BillingEvent`; `StripeBillingProvider` verifies via `stripe.Webhook.construct_event` and translates failures to `BillingProviderError` (→ 400). **The `stripe` import is lazy** so the app runs without the optional dependency. Ingestion is **idempotent** via a unique `event_id` in `processed_webhook_events`; the org is resolved from `metadata.organization_id` and the plan from the configurable `stripe_price_plan_map`. Billing is optional (503 without `stripe_webhook_secret`), like auth without `JWT_SECRET`.
- **NEVER change:** routes/services never import the Stripe SDK (it stays behind `BillingProvider`); webhooks stay idempotent + signature‑verified; the billing provider is built in `create_app` and stored on `app.state`. (M2.5b) See [16_billing.md](16_billing.md).

### D25 — Async batch behind a `JobRunner` port; in‑process default, worker registry‑ready
- **Why:** support async batch analysis with zero required infra (single‑instance/degraded mode) while keeping a clean seam for a Redis‑backed worker — without duplicating the analyze pipeline.
- **How:** a `JobRunner` port + registry (`app/jobs/`); `BackgroundJobRunner` (in‑process asyncio task) is the default, arq/Celery is a registry entry selected by `settings.job_queue`. `BatchService` creates a `batch_jobs` row and processes items by reusing `run_analysis` (results become normal tickets/analyses). **`BatchJobStore` wraps a sessionmaker** (own sessions) so the job is visible across the request and the background task. Submission is metered + quota‑gated like `/v1/analyze`.
- **NEVER change:** batch reuses `run_analysis` (no second analyze path); the external worker stays behind the `JobRunner` port; `BatchJobStore` stays sessionmaker‑backed; the default runner needs no infra. (M3.3a) See [18_jobs.md](18_jobs.md).

### D26 — Outbound webhooks: signed, best‑effort, behind a `WebhookDispatcher` port
- **Why:** notify tenants of async events (e.g. `batch.completed`) without ever letting a slow/failed webhook break the analysis/batch path; keep HTTP delivery abstracted + testable.
- **How:** the app signs each delivery HMAC‑SHA256 over `{timestamp}.{body}` (the outbound mirror of the Stripe inbound verification); `HttpWebhookDispatcher` (bounded inline retries, injected httpx client, sessionmaker‑backed stores) is best‑effort and **never raises**; `NoOpWebhookDispatcher` when there's no DB. `BatchService.submit(on_complete=…)` triggers dispatch. The per‑webhook signing **secret is retained** (we sign with it) and returned once — unlike hashed API keys — so it should be encrypted at rest.
- **NEVER change:** deliveries are signed + best‑effort (never break the caller); dispatch stays behind the `WebhookDispatcher` port (sessionmaker‑backed, background‑safe); webhook management is owner/admin; the SDK/httpx client is injected, not imported into routes. (M3.3b) See [18_jobs.md](18_jobs.md).

### D27 — Routing/SLA: a pure engine + explicit `POST /route` (not coupled to `run_analysis`)
- **Why:** add per‑tenant routing/SLA without touching the shared analyze pipeline or its latency, and keep evaluation trivially testable.
- **How:** `RoutingEngine`/`SlaCalculator` (`app/routing/engine.py`) are **pure** (take loaded ORM rows, no I/O); config is CRUD‑managed (`routing_rules`/`sla_policies`, owner/admin); `POST /v1/tickets/{id}/route` evaluates against the latest analysis and persists `assignee`/`sla_due_at` on the ticket. Matching is **string equality** on the stored analysis `category`/`priority` values — forward‑compatible with the custom taxonomies coming in M3.4b (no coupling to the fixed enums).
- **NEVER change:** routing is applied explicitly (not inside `run_analysis`); the engine stays pure; matching stays string‑based (forward‑compatible); config is tenant‑scoped + owner/admin. (M3.4a) See [19_routing.md](19_routing.md).

### D28 — Inbound channels are thin adapters over the shared analyze/batch pipeline
- **Why:** ingest tickets from email/CSV without a second analyze path or new infra; keep provenance.
- **How:** `POST /v1/channels/email` and `/v1/channels/import` are authenticated, tenant‑scoped, metered + quota‑gated, and reuse `run_analysis` (email) / the M3.3a batch via `submit_analyze_batch` (CSV). `source` is threaded `run_analysis → persist_analysis → get_or_create_ticket` (default `"api"`) to tag `email`/`csv`. CSV is the raw request body parsed with stdlib `csv` (no `python-multipart`); parse errors are 400. The mail‑provider inbound webhook (per‑org address/token + signature) is deferred.
- **NEVER change:** channels reuse the shared pipeline (no duplicate analyze logic); stay tenant‑scoped + metered; CSV stays dependency‑light (raw body, 400 on parse failure); `source` default `"api"` preserves existing behavior. (M3.5) See [20_channels.md](20_channels.md).

### D29 — Analytics: SQL aggregation behind an `AnalyticsStore` port + a window‑owning service (OLAP deferred)
- **Why:** tenant analytics over the existing OLTP tables without a second datastore, keeping aggregation in the DB and the logic testable.
- **How:** `SqlAlchemyAnalyticsStore` does all aggregation in SQL (`func.count`, `GROUP BY`, `cast(created_at, Date)`), tenant‑scoped + window‑bounded; `AnalyticsService` owns the calendar‑date → half‑open datetime window (end‑day inclusive) and assembles responses; routes are read‑only, guarded by `get_tenant_context` (any member). Distributions are analysis‑level (`GROUP BY analyses.category/priority`). An OLAP store / materialized views are a deferred scale concern.
- **NEVER change:** analytics is read‑only + tenant‑scoped (filter by `organization_id`); aggregation stays in SQL behind the port; the service stays HTTP‑free. (M4.1) See [21_analytics.md](21_analytics.md).

### D30 — Ticket lifecycle & workspace APIs: additive status/`ticket_id`/filters; PATCH via the request session; best‑effort id resolution
- **Why:** M4.3 (agent workspace) exposed real backend gaps during frontend integration — no ticket status, no manual assignment, no `ticket_id` to deep‑link to, thin list filtering. M3.6 closes exactly those, small and additive, without disturbing the analyze pipeline or the read port.
- **How:** `tickets.status` is an enum **value string** (`open`/`in_progress`/`pending`/`resolved`/`closed`, `server_default 'open'`) — same convention as `role`/`category`/`priority`, not a PG enum; **transitions are unrestricted** (no state machine). `PATCH /v1/tickets/{id}` (any org member, like `POST /route`) updates `status`/`assignee` using Pydantic `model_fields_set` (so `{"assignee": null}` clears vs. omitted leaves unchanged), mutating the loaded ORM object so the **request‑scoped session commits** — the `TicketStore` **read port stays read‑only**. `/v1/analyze` + `/reanalyze` return `AnalyzeResponse` (= `TicketAnalysis` **+ `ticket_id`**, additive); `run_analysis` returns an `AnalyzeOutcome`, `persist_analysis` returns the ticket id, and on a cache hit the tenant path resolves the id **best‑effort** (`resolve_ticket_id`, own session, swallows errors) — **skipped for the legacy org‑less path** so its cache‑hit path stays DB‑free. `GET /v1/tickets` gains additive `status`/`assignee`/`source`/`search` (escaped `ILIKE`) filters + `sort` (created_at asc/desc).
- **NEVER change:** legacy `/analyze` keeps a plain `TicketAnalysis` (unauthenticated, unchanged); status/`ticket_id`/filters stay additive/back‑compatible; PATCH stays any‑member + request‑session‑committed (read port read‑only); `ticket_id` resolution stays best‑effort and skips the legacy path; `status` stays a value string. (M3.6) See [17_tickets.md](17_tickets.md).

### D31 — Frontend is a Next.js BFF: httpOnly‑cookie auth, server‑only API client, no backend coupling
- **Why:** the `web/` frontend (Phase 4: M4.2 scaffold → M4.3 workspace + M3.6 integration → M4.4 analytics → M4.5 admin) must add UI without weakening the backend's security posture or contracts. The full detail lives in [22_frontend.md](22_frontend.md); this entry records the **invariants** so they sit alongside the backend D‑list.
- **How:** Next.js is a **Backend‑for‑Frontend** — the browser talks to Next.js **same‑origin**, Next.js talks to FastAPI **server‑to‑server**. JWTs live **only in httpOnly cookies** (never in browser JS/localStorage), set server‑side by Server Actions; a server‑only session DAL (`getSession`) + a token‑refresh Route Handler + a `proxy.ts` (Next 16's renamed middleware) do optimistic auth routing. A typed **server‑only API client** (`web/src/lib/api/*`) mirrors `app/models.py` and maps the error envelope to `ApiError`. Pure logic is kept **Next‑free** so it's unit‑testable (41 vitest tests). Charts are native (no charting dep). The admin panel relies on the **backend as the sole authz gate** (owner/admin enforced server‑side; a member gets a graceful 403).
- **NEVER change:** tokens stay httpOnly + server‑set (never exposed to JS); the BFF boundary stays same‑origin browser→Next / server‑side Next→FastAPI (no direct browser→FastAPI call — it would reintroduce CORS + token exposure); **the frontend adds no backend endpoints, schema, or CORS changes** (it consumes existing APIs); one‑time secrets (API key / webhook signing) are revealed once from action state, never re‑fetched; pure modules stay Next‑free/tested; the backend remains the authorization gate. (M4.2–M4.5 + M3.6 integration) See [22_frontend.md](22_frontend.md).

### D32 — Prompt versioning (append‑only registry) + provider‑agnostic eval harness gated in CI
- **Why:** prompt/model quality was invisible and unattributable; a prompt edit could silently regress classification. M5.1 makes prompts **versioned + recorded** and adds a **measurable, CI‑gateable** quality signal — the foundation for the Phase 5 AI moat.
- **How:** prompts are a **registry of `PromptVersion`s** (`app/prompts.py`, mirroring `_PROVIDERS`/plans); `get_prompt` fails safe to the default; the version is selected via `LLM_PROMPT_VERSION` and **recorded** on `AnalysisResult.prompt_version` → `analyses.prompt_version` (nullable, migration `0011`). The **eval harness** (`app/eval/`) is **provider‑agnostic** — `run_eval(provider, cases)` scores category/priority accuracy against labeled `GOLDEN_CASES`; the **default test suite scores it with a fake provider (no live LLM)**, while `python -m app.eval` (and an opt‑in `eval.yml` workflow, skipped without a key secret) runs the **real** provider and exits non‑zero below threshold — gating prompt/model changes.
- **NEVER change:** prompt versions are **append‑only** (never edit a shipped version's text — attribution + eval comparability, the prompt analogue of never editing a shipped migration); `get_prompt` stays fail‑safe; the `TicketAnalysis` contract + `Provider*` translation are unchanged and `prompt_version` stays additive; the eval harness stays provider‑agnostic and its **default path needs no live LLM** (fake provider); the live gate stays opt‑in (cost). (M5.1) See [23_prompts_eval.md](23_prompts_eval.md).

### D33 — RAG: provider-agnostic embeddings + tenant-isolated vector store behind a port; best-effort, opt-in grounding
- **Why:** ground analyses in an org's own knowledge base without coupling business logic to an embeddings SDK or a specific vector DB, without ever leaking one tenant's knowledge into another's analysis, and without letting retrieval break or slow the core analyze path.
- **How:** an **`EmbeddingProvider`** abstraction + registry (`app/embeddings/`, mirroring `AnalysisProvider`/D3) — `OpenAIEmbeddingProvider` for the OpenAI-compatible family plus a **keyless deterministic `hash`** provider so RAG runs fully offline; built defensively in `create_app` (→ 503 if unbuildable, app still boots). A **`VectorStore`** port (`app/rag/base.py`) + `SqlAlchemyVectorStore` stores `documents`/`document_chunks` (migration `0012`) with **`embedding` as JSONB** and `organization_id` NOT NULL on both (chunk org denormalized for tenant-scoped search); **pure** chunking + cosine/top-k helpers rank candidates the store loads (the routing "store loads rows, pure engine evaluates" split). KB CRUD under `/v1/orgs/{id}/documents` (owner/admin write, membership read; ingest embeds → 502 on failure). Grounding is **opt-in** (`RAG_ENABLED` + `LLM_PROMPT_VERSION=v2`): a new **append-only context-aware prompt `v2`** (v1 unchanged, D32) + an additive `analyze(ticket_text, *, context=None)` (contract + `Provider*` unchanged). `run_analysis(retrieve_context=…)` retrieves **best-effort** (own session, swallows errors, tenant path only), folds context into the **cache key** so grounded/ungrounded never collide, and passes it to the provider.
- **NEVER change:** every vector is tenant-scoped by `organization_id` (no cross-org leakage); the embeddings layer stays provider-agnostic with a keyless offline default and the app boots without it; analyze-path retrieval stays best-effort + tenant-only (never on legacy `/analyze`); `v2` is append-only and `v1` stays context-free; the SDK stays behind the port. (M5.2) See [24_rag.md](24_rag.md).

### D34 — Agentic actions: human-approved by default, enforced state machine, no auto-destructive execution, fully audited
- **Why:** turn analyses into resolution actions ("auto-resolve") without ever letting the AI take an irreversible/customer-facing action on its own; keep the suggester provider-agnostic and the whole flow traceable and tenant-safe.
- **How:** a suggester (`ActionSuggester` port) **proposes** actions — `RuleBasedActionSuggester` (deterministic, offline default) or `LlmActionSuggester` (`ACTION_SUGGESTER=llm`, reusing the provider via an **additive** `AnalysisProvider.suggest_actions` structured-output method whose default raises so existing providers stay valid). Proposals persist as `proposed` (`resolution_actions`, migration `0013`); a **pure state machine** (`app/actions/state.py`) gates transitions so **execution requires prior approval** (proposed→approved→executed/failed; rejected/executed/failed terminal). A privileged **human** (`require_approver`: a user — never an API key — who is owner/admin) approves/rejects/executes; `ActionHandler`s run the effect (internal handlers mutate the ticket; **destructive** ones — the single-source `DESTRUCTIVE_ACTIONS` set — dispatch a signed webhook, reusing M3.3b, and never auto-run). **Every** transition writes an append-only, tenant-scoped `audit_logs` row with the actor. Everything is additive (no change to analyze/tickets contracts).
- **NEVER change:** nothing executes without an explicit human approve→execute (the state machine makes executing an unapproved action a 409); destructive action types stay approval-gated and never auto-execute; every transition is audited; actions + audit stay tenant-scoped (cross-org 404; approval requires a member, never an API key); the suggester stays behind a port with an offline rule-based default; `suggest_actions` stays additive (default-raise; `TicketAnalysis` + `Provider*` unchanged). (M5.3) See [25_actions.md](25_actions.md).

---

## Quick "must never break" checklist
- `Provider*` translation • error envelope + stable codes • `Cache` protocol + best‑effort • best‑effort persistence • best‑effort metering (own session) • quota gate before the LLM call (402) • billing SDK behind `BillingProvider` (lazy import) • idempotent + signature‑verified webhooks • app‑factory/lifespan ownership • identity‑vs‑session auth split • API‑key hashing/plaintext‑once/revocation • nullable tenant FKs (tickets/analyses) • `usage_events.organization_id` NOT NULL • one‑driver PG • never edit shipped migrations • `/health` no‑deps + `/ready` no‑LLM • request‑id correlation • legacy `/analyze` contract (unauthenticated, unmetered) • ticket lifecycle: status value‑string + additive `ticket_id`/filters, PATCH via request session, best‑effort id resolution (D30) • frontend BFF: httpOnly‑cookie tokens, same‑origin BFF boundary, no backend coupling (D31) • prompt versions append‑only + recorded, eval harness provider‑agnostic with a no‑LLM default path (D32) • RAG: tenant‑scoped vectors (no cross‑org leakage), provider‑agnostic embeddings with a keyless offline default, best‑effort tenant‑only grounding, append‑only `v2` prompt (D33) • agentic actions: human‑approved by default, enforced state machine (no executing an unapproved action), no auto‑destructive execution, every transition audited, tenant‑scoped (D34).
