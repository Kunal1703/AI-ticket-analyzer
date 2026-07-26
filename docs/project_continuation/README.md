# Project Continuation — Engineering Handoff

> **If you are a future Claude Code session (or a new engineer): read these documents *before* writing any code.**
> They encode not just *what* exists but *why* — the reasoning, tradeoffs, and invariants behind every architectural decision. Skipping them will cause you to violate deliberate design choices.

This is **AI Ticket Analyzer** ("TriageAI"), a FastAPI service that analyzes customer‑support tickets with an LLM and is being evolved, milestone by milestone, from an interview assignment into a production‑quality multi‑tenant SaaS.

---

## Current status

- **ALL PHASES COMPLETE (0–5).** Backend: Phases 0–3 + M3.6 + **Phase 5 — M5.1 (prompt versioning + eval harness) + M5.2 (RAG over the knowledge base) + M5.3 (agentic resolution actions)**. Frontend (`web/`): M4.2 scaffold → M4.3 workspace (+ M3.6 integration) → M4.4 analytics dashboard → M4.5 admin panel.
- **Next: no core milestone remains.** Open work is deferred/housekeeping: M5.2/M5.3 follow‑ups (RAG on batch/channel/suggest paths, past‑ticket indexing, pgvector, more action types + opt‑in auto‑approval of safe internal actions, a frontend for KB/actions/audit); deferred Phase 3 **M3.3c**/**M3.4b**, M2.5c (outbound Stripe), RBAC deepening, refresh‑token rotation, rate limiting, `app/db/models.py` package split (18 models). See [14_remaining_roadmap.md](14_remaining_roadmap.md).
- **Branch:** `kunal-panwar-submission`.
- **Verified counts:** **13 migrations** (`0001`→`0013`), 18 ORM models, 12 routers, 11 metric families; frontend 12 pages + 1 route handler + `proxy.ts`.
- **Tests:** backend **855 passing, 20 skipped**, **95.29% coverage**, gate 90%, 41 test modules; frontend **41 vitest tests** (7 files). All quality gates green (`ruff`, `mypy`, `pytest --cov`; `pnpm lint`/`typecheck`/`test`/`build`).
- **Quality gates:** backend `ruff` (lint + format), `mypy` (strict‑ish), `pytest --cov`; frontend `pnpm lint` + `typecheck` + `test` + `build` — all green.

---

## Reading order

Read top‑to‑bottom the first time. Later, jump to the relevant topic doc.

| # | File | Read it to understand… |
|---|------|------------------------|
| 0 | [00_project_overview.md](00_project_overview.md) | What the product is, maturity, philosophy, tech stack |
| 1 | [01_architecture.md](01_architecture.md) | Every layer, responsibilities, boundaries, extension points |
| 2 | [02_request_flow.md](02_request_flow.md) | End‑to‑end flows (analyze, auth, API key, tenant, cache, DB) |
| 3 | [03_database.md](03_database.md) | Tables, relationships, nullability, all migrations |
| 4 | [04_ai_provider_system.md](04_ai_provider_system.md) | The AI provider abstraction (the template for all pluggability) |
| 5 | [05_authentication.md](05_authentication.md) | JWT/Argon2, provider‑agnostic auth, extension to OAuth/SSO |
| 6 | [06_tenancy.md](06_tenancy.md) | Orgs, memberships, API keys, tenant context, isolation |
| 7 | [07_cache.md](07_cache.md) | Cache protocol, in‑memory + Redis, fallback |
| 8 | [08_persistence.md](08_persistence.md) | Repositories, services, session/engine lifecycle, best‑effort writes |
| 9 | [09_observability.md](09_observability.md) | Structured logs, request IDs, Prometheus metrics, token usage |
| 10 | [10_dependency_injection.md](10_dependency_injection.md) | `create_app`, `app.state`, the dependency graph |
| 11 | [11_testing_strategy.md](11_testing_strategy.md) | Fakes, mocked sessions, skipif integration, coverage philosophy |
| 12 | [12_design_decisions.md](12_design_decisions.md) | **Every** major decision: reason, tradeoffs, never‑change |
| 13 | [13_completed_milestones.md](13_completed_milestones.md) | Every milestone M0.1 → M2.3, what/why/verification |
| 14 | [14_remaining_roadmap.md](14_remaining_roadmap.md) | M2.4 onward, order, dependencies, risks |
| 15 | [15_handoff.md](15_handoff.md) | **Start here for continuing work.** Checklists, invariants |
| 16 | [16_billing.md](16_billing.md) | Metering + quota enforcement (M2.5a); Stripe provider, webhooks, plan sync, usage (M2.5b) |
| 17 | [17_tickets.md](17_tickets.md) | Tickets read/history (M3.1); feedback + re‑analyze (M3.2) |
| 18 | [18_jobs.md](18_jobs.md) | Async batch (M3.3a) + outbound webhooks (M3.3b) |
| 19 | [19_routing.md](19_routing.md) | Routing rules + SLA policies (M3.4a) |
| 20 | [20_channels.md](20_channels.md) | Inbound channels — email + CSV import (M3.5) |
| 21 | [21_analytics.md](21_analytics.md) | Analytics API — summary + timeseries (M4.1) |
| 22 | [22_frontend.md](22_frontend.md) | Frontend — Next.js BFF: scaffold + auth (M4.2), agent workspace (M4.3), analytics dashboard (M4.4), admin panel (M4.5) |
| 23 | [23_prompts_eval.md](23_prompts_eval.md) | Prompt versioning + eval harness + CI quality gate (M5.1) |
| 24 | [24_rag.md](24_rag.md) | RAG — embeddings abstraction + tenant‑isolated vector store + KB endpoints + grounding (M5.2) |
| 25 | [25_actions.md](25_actions.md) | Agentic resolution actions — propose → human approve → execute, fully audited (M5.3) |
| — | [developer_guide.md](developer_guide.md) | Practical "how to add X" recipes |

**Fast path to continue development:** read [15_handoff.md](15_handoff.md), then [12_design_decisions.md](12_design_decisions.md), then the topic doc for whatever you're changing, then [developer_guide.md](developer_guide.md).

---

## The one‑paragraph mental model

The app is a **FastAPI application factory** (`create_app`) that owns its resources on `app.state` and injects them into endpoints via `Depends`. Every external system (the LLM, the cache, authentication, and — via ports — the database) sits behind an **abstraction with a registry/factory** so implementations can be swapped or added without touching business logic. Everything optional (`DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`) degrades gracefully: the app boots and serves `/analyze` even with none of them. This "abstraction + graceful degradation + strong tests" triad is the project's DNA — preserve it.

See [12_design_decisions.md](12_design_decisions.md) for the non‑negotiable invariants.
