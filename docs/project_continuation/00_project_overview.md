# 00 — Project Overview

## What this project is

**AI Ticket Analyzer** is an HTTP API that accepts a customer‑support ticket and returns a structured analysis: a one/two‑sentence **summary**, a **category** (8 enum values), a **priority** (Low/Medium/High/Critical), and a list of suggested **next actions**. The analysis is produced by an LLM using **structured outputs** (a Pydantic schema passed as `response_format`), so the response is always schema‑valid.

The core endpoint is `POST /analyze`. Everything else (auth, tenancy, persistence, cache, metrics) is production scaffolding built around that core.

## Why it exists

It began as an interview assignment (a single‑file FastAPI + OpenAI wrapper) and is being deliberately evolved into a **production‑quality, multi‑tenant SaaS** ("TriageAI" — a Zendesk/Freshdesk‑style AI triage layer). The evolution is done in **small, individually‑reviewable milestones**, each of which:

- is small and testable,
- compiles green (ruff + mypy + pytest),
- never breaks existing behavior or tests,
- adds one capability behind a clean abstraction.

This milestone discipline is itself a design decision (see [12_design_decisions.md](12_design_decisions.md)). It is *why* the codebase is unusually clean for its feature count.

## Current maturity

- **Phase 0 (hardening) — complete.** CI, linting/typing, config correctness, security headers, error envelope, AI provider abstraction.
- **Phase 1 (persistence, cache, observability) — complete.** DI/app‑factory, Postgres+Alembic, best‑effort persistence, Redis cache, structured logs + metrics + token capture, readiness + graceful shutdown.
- **Phase 2 (multi‑tenancy, auth, billing) — complete.** Tenancy schema (M2.1), auth (M2.2), API keys + tenant context (M2.3), versioned `/v1/analyze` + RBAC (M2.4), usage metering + plan quotas (M2.5a), Stripe billing provider + webhooks (M2.5b).
- **Phase 3 (helpdesk features) — complete (core + M3.6).** Tickets read/history (M3.1), feedback + re‑analyze (M3.2), async batch + job status (M3.3a), outbound webhooks (M3.3b), routing rules + SLA policies (M3.4a), inbound channels — email + CSV (M3.5), and **M3.6 (ticket lifecycle & workspace APIs — `tickets.status` + `PATCH /v1/tickets/{id}` + `ticket_id` in analyze responses + richer `GET /v1/tickets` filters)**. Deferred advanced items: **M3.3c** (arq worker + concurrency caps + durable retries) and **M3.4b** (custom per‑tenant categories / dynamic structured‑output schema).
- **Phase 4 (analytics & frontend) — complete.** Analytics API (M4.1); **frontend M4.2 (scaffold) + M4.3 (agent workspace, incl. the M3.6 integration) + M4.4 (analytics dashboard) + M4.5 (admin panel)** — a sibling `web/` Next.js 16 BFF (httpOnly‑cookie auth + app shell; tickets list/detail with **status controls, manual assignee, status/assignee/source/search filters + sort**, feedback, re‑analyze, apply‑routing, AI co‑pilot analyze with **`ticket_id` deep‑linking**; analytics stat tiles + timeseries + distributions; `/settings` admin: API keys, webhooks, routing/SLA config, usage). The backend gaps M4.3 surfaced were closed by **M3.6** and are **fully consumed by the workspace frontend**. See [22_frontend.md](22_frontend.md).
- **Phase 5 (AI moat) — complete.** **M5.1 + M5.2 + M5.3 done.** M5.1 added a versioned prompt registry recorded on `analyses.prompt_version` + a provider‑agnostic eval harness (`app/eval/`) with a CLI/CI quality gate; M5.2 added a provider‑agnostic embeddings layer (`app/embeddings/`) + a tenant‑isolated vector store (`documents`/`document_chunks`, migration `0012`) + `RagService` + KB endpoints, with opt‑in best‑effort grounding fed into `run_analysis` (append‑only prompt `v2`); **M5.3 added human‑approved agentic resolution actions** (`app/actions/`) — a pluggable suggester proposes, a pure state machine forces approval before execution, handlers apply the effect (destructive ones via signed webhooks), and every transition is written to an append‑only tenant‑scoped audit log (`resolution_actions`/`audit_logs`, migration `0013`). See [23_prompts_eval.md](23_prompts_eval.md), [24_rag.md](24_rag.md), [25_actions.md](25_actions.md), [14_remaining_roadmap.md](14_remaining_roadmap.md).

The service is a **feature‑rich, architecturally production‑grade backend**. Not yet fully production‑*operational*: no live infra in the dev environment (Postgres/Redis/Stripe/mail‑provider all fake‑tested), no rate limiting, refresh tokens are stateless (no rotation), the in‑process job runner is single‑instance (arq deferred). See [15_handoff.md](15_handoff.md) for the full status.

## Architecture philosophy (the "DNA")

1. **Depend on abstractions, never on implementations.** The LLM, the cache, auth, and the DB (via ports) are all behind interfaces + registries. Business logic (routes/services) imports the abstraction, never the concrete SDK. This is the single most important rule.
2. **Graceful degradation.** Optional subsystems (DB, Redis, auth) are truly optional. The app boots and serves `/analyze` with an in‑memory cache and no DB. Misconfiguration fails *fast and clearly* (e.g., selecting `openai` with no key) or *degrades to a documented default* (no `REDIS_URL` → in‑memory cache).
3. **Explicit resource ownership.** `create_app()` builds resources and stores them on `app.state`; `lifespan` disposes them. No import‑time global singletons for stateful resources.
4. **Best‑effort side effects.** Persistence and cache writes never break the request. A dead DB or Redis logs a warning and returns a correct response.
5. **Strong, fast tests without live infra.** Ports + fakes + mocked sessions let the whole HTTP surface be tested with no Postgres/Redis. Real‑infra paths are `skipif`‑guarded integration tests.
6. **Provider‑agnostic everything.** Whenever a class of external system has multiple possible backends (LLMs, auth methods, caches), we build the abstraction *before* we need the second implementation.

## Major technologies

| Concern | Technology | Notes |
|---|---|---|
| Language | Python 3.12+ (3.13 local venv) | `mypy` targets 3.12 |
| Web | FastAPI + Starlette | app factory + `APIRouter`s |
| Validation/Settings | Pydantic v2 + pydantic‑settings | `LLM_*` config with `OPENAI_*` aliases |
| LLM | `openai` SDK + `tenacity` | OpenAI‑compatible family (OpenAI/Groq/Together/OpenRouter/Ollama/custom) |
| DB | SQLAlchemy 2 (async) + `psycopg` v3 | `postgresql+psycopg://` works sync (Alembic) *and* async (app) |
| Migrations | Alembic | offline SQL verified; **thirteen** migrations (`0001`→`0013`) |
| Embeddings / RAG | `openai` SDK + keyless `hash` provider | provider‑agnostic embeddings; tenant‑isolated JSONB vector store behind a port (M5.2) |
| Cache | `redis` (redis‑py asyncio) | optional; in‑memory fallback |
| Auth | `PyJWT` + `argon2-cffi` + `email-validator` | JWT access/refresh, Argon2 hashing |
| Billing | `stripe` (lazy import) | inbound webhook verification (M2.5b); behind `BillingProvider` |
| HTTP client | `httpx` (`AsyncClient` on `app.state`) | outbound webhook delivery (M3.3b) |
| Observability | `prometheus-client` + stdlib logging | JSON logs, `/metrics` (11 metric families) |
| Tooling | ruff, mypy, pytest, pytest‑cov, coverage gate | GitHub Actions CI |

See [01_architecture.md](01_architecture.md) for how these fit together and [03_database.md](03_database.md) for the schema.

## Production‑readiness goals (the finish line)

The blueprint (a Zendesk‑AI competitor) targets: multi‑tenant auth + RBAC, per‑tenant persistence and analytics, API keys + rate limiting + billing (Stripe), a ticket lifecycle and agent workspace, batch/async processing + webhooks, a frontend, and an AI moat (RAG, eval harness, auto‑resolve). The [14_remaining_roadmap.md](14_remaining_roadmap.md) sequences the path there. **We have completed the full backend feature set through Phase 3 + M3.6, and the entire Phase 4 frontend (M4.1–M4.5 + the M3.6 frontend integration) — a Next.js BFF covering auth, the agent workspace, analytics, and admin.** **The AI moat (Phase 5) is now complete too — M5.1 (prompt versioning + eval harness), M5.2 (RAG), and M5.3 (auto‑resolve / agentic actions) — so the whole blueprint roadmap is delivered.** What remains is deferred/infra‑dependent work and housekeeping (M3.3c arq worker, M2.5c outbound Stripe, M3.4b custom categories, refresh‑token rotation, RBAC deepening, rate limiting, frontend follow‑ups for KB/actions, `models.py` split).
