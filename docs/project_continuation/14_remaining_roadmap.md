# 14 — Remaining Roadmap

Where the project is going. **Backend Phases 0–3 + M3.6 are done; Phase 4 frontend (M4.1–M4.5 + the M3.6 frontend integration) is done; Phase 5 is COMPLETE — M5.1 (prompt versioning + eval harness), M5.2 (RAG over the knowledge base), and M5.3 (agentic resolution actions) are all done.** With Phase 5 complete, the **whole original blueprint roadmap is delivered**. What remains is **deferred/infra‑dependent + housekeeping** work (no new core milestone): **M3.3c** (arq worker + concurrency caps + durable retries), **M3.4b** (custom per‑tenant categories), **M2.5c** (outbound Stripe), refresh‑token rotation, RBAC deepening, rate limiting, per‑milestone frontend follow‑ups, and the `app/db/models.py` package split. This doc gives the plan, order, dependencies, risks, and how the architecture should evolve. It reflects the original blueprint (a Zendesk/Freshdesk‑style AI triage SaaS) and the milestone plan. The historical "DONE" entries below record each milestone as completed.

## ✅ DONE: M2.4 — Versioned `/v1/analyze` + tenant‑scoped persistence + RBAC

**Completed.** `POST /v1/analyze` (auth via JWT or `X-API-Key`+`analyze` scope) persists under the resolved org, sharing `run_analysis` with the legacy `/analyze`; a global `ProviderError` handler centralizes error mapping; `require_role`/`require_scope` + a `Role` enum add RBAC (API‑key create/revoke require owner/admin); `organization_id` is threaded through persistence with per‑org dedupe and org‑namespaced cache keys. Legacy `/analyze` unchanged. See [13_completed_milestones.md](13_completed_milestones.md).

**Still open from the RBAC theme (fold into M2.5 or a small M2.4.x):** member **invitation + role assignment** endpoints (today an org has only its owner, so non‑owner roles can't be created via the API — tested by injecting a membership directly); a `readonly` gate on read endpoints as they appear.

## ✅ DONE: M2.5a — Usage metering + plan quota enforcement

**Completed.** `usage_events` metering per analysis + a configurable plan registry (placeholder limits) enforced on `/v1/analyze` via a `require_quota` dependency (**402** on cap, before the LLM call). Metering is best‑effort (own session, cache‑miss only); legacy `/analyze` is untouched. See [16_billing.md](16_billing.md) and [13_completed_milestones.md](13_completed_milestones.md).

## ✅ DONE: M2.5b — Stripe billing provider + webhooks + plan sync + usage endpoint

**Completed.** A provider‑agnostic `BillingProvider` + `StripeBillingProvider` (lazy SDK import); signature‑verified, **idempotent** `POST /v1/billing/webhook` (dedupe via `processed_webhook_events`); plan sync → `Organization.plan` (org from event metadata, plan from the configurable `stripe_price_plan_map`); and the `GET /v1/orgs/{org_id}/usage` endpoint. See [16_billing.md](16_billing.md).

## Immediate next: M2.5c — Outbound Stripe (checkout/subscriptions)

- **Goal:** create Stripe Checkout Sessions / subscriptions (setting `metadata.organization_id`), persist the `stripe_customer_id` linkage, and replace the M2.5a placeholder plan limits with real plan/price definitions. Needs a live Stripe account + the SDK to verify, so it was split out of the offline‑testable M2.5b slice. Depends on M2.5b (done). Historical sketch below.

### Historical sketch of M2.4 (for reference)

- **Goal:** introduce an authenticated, tenant‑scoped `/v1/analyze` **alongside** the legacy unauthenticated `/analyze` (which stays for back‑compat, per D22); add RBAC roles + row‑level tenant filtering.
- **Implementation sketch (reuse existing seams):**
  - `/v1/analyze` depends on `get_tenant_context` (API key or JWT) → gets `organization_id`.
  - Persist with `organization_id` populated (pass it into `get_or_create_ticket`/`add_analysis`; scope dedupe per‑org).
  - **RBAC:** turn `Membership.role` into an enum (`Owner/Admin/Manager/Agent/ReadOnly`); add a `require_role(...)` dependency layered on `require_org_membership` (which already returns the `Membership`).
  - **Scope enforcement:** add `require_scope("analyze:write")` gating API‑key‑authenticated writes using `TenantContext.scopes`.
  - Namespace cache keys by `organization_id` (so tenants don't share cached analyses).
  - Consider making `/v1/analyze` persistence authoritative (checked) vs. the legacy best‑effort path.
- **Risks:** tenant‑leakage bugs (high — centralize scoping in one place and test cross‑tenant denial exhaustively); double `/analyze` maintenance (legacy delegates to a shared service).
- **Depends on:** M2.1 (org_id columns), M2.2 (auth), M2.3 (tenant context) — all done.

## Remaining Phase 2 (after M2.4)

- **M2.5c — Outbound Stripe:** checkout/subscription creation + real plan/price definitions. (M2.5a metering + `402` enforcement and M2.5b provider/webhooks/plan‑sync/usage are **done**.)
- **Org/member management depth:** invites, role management, member CRUD (`/v1/orgs/{id}/members`), team support (`teams`/`team_members`). Some of this rides on M2.4 RBAC.
- **Refresh‑token rotation/revocation:** `refresh_tokens` table (jti + revoked_at); rotate on refresh; denylist. (Auth debt from M2.2.)
- **Rate limiting:** per‑API‑key/IP quotas (protect the LLM budget). SlowAPI or gateway‑level.

## Phase 3 — Helpdesk features

- **✅ M3.1 Tickets read / history API — DONE.** Tenant‑scoped `GET /v1/tickets` (paginate + category/priority filter) and `GET /v1/tickets/{id}` (versioned analysis history), read‑only behind a `TicketStore` port. Explicit ticket create/update/delete deferred (tickets originate on the analyze path). See [17_tickets.md](17_tickets.md).
- **✅ M3.2 Feedback capture + re‑analyze — DONE.** `feedback` table + `POST`/`GET /v1/tickets/{id}/feedback` (feedback on a specific analysis; corrected category/priority = training label) and `POST /v1/tickets/{id}/reanalyze` (metered + quota‑gated; reuses `run_analysis` with `bypass_cache=True` to append a fresh versioned analysis). See [17_tickets.md](17_tickets.md).
- **✅ M3.3a Async batch + job status — DONE.** `JobRunner` port + `BackgroundJobRunner` (in‑process default; arq registry‑ready); `batch_jobs` table + `BatchService`; `POST /v1/analyze/batch` (202) + `GET /v1/analyze/batch/{id}`; items reuse `run_analysis`. See [18_jobs.md](18_jobs.md).
- **✅ M3.3b Outbound webhooks — DONE.** `webhooks`/`webhook_deliveries` + `WebhookDispatcher` (HMAC‑signed, bounded inline retries, best‑effort), `batch.completed` delivery on job completion, owner/admin registration endpoints. See [18_jobs.md](18_jobs.md).
- **⬜ M3.3c Worker + concurrency caps:** a Redis‑backed arq `JobRunner`, per‑tenant concurrency caps, and **durable scheduled retries** (`next_attempt_at` + a sweeper) — needs live Redis/worker to verify.
- **M3.2 Feedback capture + re‑analyze** (`feedback` table; `POST /v1/tickets/{id}/reanalyze`) — training signal.
- **M3.3 Async batch analyze + job queue + webhooks** — **M3.3a + M3.3b done** (async batch + job status; outbound webhooks); **M3.3c pending** (arq worker + per‑tenant concurrency caps + durable retries). See above + [18_jobs.md](18_jobs.md).
- **M3.4 Routing rules, SLA policies, custom categories** — **M3.4a done** (routing rules + SLA policies + `POST /v1/tickets/{id}/route`, see [19_routing.md](19_routing.md)); **M3.4b pending** (custom per‑tenant categories = dynamic structured‑output schema generation). (`routing_rules`, `sla_policies`; per‑tenant taxonomy — note: dynamic categories vs. the structured‑output schema needs per‑tenant schema generation).
- **✅ M3.5 Inbound channels — DONE.** `POST /v1/channels/email` (authenticated email‑to‑ticket) + `POST /v1/channels/import` (CSV → async batch); `source` tagging; reuses `run_analysis`/batch. Mail‑provider inbound webhook (per‑org address/token + signature) deferred. See [20_channels.md](20_channels.md).

## Phase 4 — Analytics & frontend

- **✅ M4.1 Analytics API — DONE.** `GET /v1/analytics/summary` (totals + category/priority distributions) + `GET /v1/analytics/timeseries` (daily tickets/analyses); SQL aggregation behind an `AnalyticsStore` port, tenant‑scoped + date‑windowed. OLAP/materialized views deferred (scale concern). See [21_analytics.md](21_analytics.md).
- **✅ M4.2 Frontend scaffold (Next.js) — DONE.** A **sibling `web/`** Next.js 16 App Router app (React 19 + TS + Tailwind + pnpm); **BFF with httpOnly cookies** (Server Actions + server‑only session DAL + refresh Route Handler + proxy), a typed server‑only API client, and an auth + app‑shell scaffold (login/signup/logout, org context, protected dashboard placeholders). Backend untouched (no CORS change). Feature screens deferred to M4.3/M4.4. See [22_frontend.md](22_frontend.md).
- **✅ M4.3 Agent workspace + AI co‑pilot panel — DONE (read‑first, existing API only).** `/tickets` (list + filters), `/tickets/[id]` (analysis history, feedback, re‑analyze, apply routing), `/analyze` (AI co‑pilot). Built strictly on the current backend; missing endpoints recorded as tech debt (see below + [22_frontend.md](22_frontend.md)). See [22_frontend.md](22_frontend.md).
- **✅ M3.6 Ticket Lifecycle & Workspace APIs — DONE (integration‑driven backend milestone).** Resolved the write‑half gaps M4.3 surfaced: `tickets.status` lifecycle (`open`/`in_progress`/`pending`/`resolved`/`closed`) + migration `0010`; `PATCH /v1/tickets/{id}` (status + manual assignee, any member); `ticket_id` in `/v1/analyze` + `/reanalyze` responses (`AnalyzeResponse`); richer `GET /v1/tickets` filters (`status`/`assignee`/`source`/`search`) + `sort`. Small, additive, backend‑only. See [17_tickets.md](17_tickets.md), D30 in [12_design_decisions.md](12_design_decisions.md). **Frontend consumption (wiring these into the M4.3 workspace) is a frontend follow‑up.**
- **✅ M4.4 Analytics dashboard — DONE (analytics UI only).** `/analytics` in `web/` consumes `/v1/analytics/{summary,timeseries}` — stat tiles, a daily timeseries chart, and by‑priority/by‑category distributions with a metric + date‑window filter; native charts (no dep). The **admin panel** part of the original M4.4 (API keys / webhooks / routing‑config UI) is **split out to M4.5** to keep the milestone reviewable. See [22_frontend.md](22_frontend.md).
- **✅ M4.5 Admin panel — DONE.** `/settings` in `web/` — Overview (org + usage/plan), API keys (create/secret‑once/revoke), Webhooks (create/secret‑once/delete), Routing rules + SLA policies (create/delete), all over existing org‑scoped endpoints. Backend enforces owner/admin (role not in the session → non‑privileged members get a graceful 403). See [22_frontend.md](22_frontend.md).
- **✅ M3.6 frontend integration — DONE (completed the M4.3 workspace).** Ticket status controls + manual assignee editing (`PATCH /v1/tickets/{id}`), the new list filters (`status`/`assignee`/`source`/`search`) + `sort`, and `ticket_id` deep‑linking from `/v1/analyze` (the co‑pilot now redirects to the created ticket). Frontend‑only. See [22_frontend.md](22_frontend.md).
- **⬜ Still open (frontend follow‑ups):** surfacing the caller's **role** in the session to role‑hide admin controls (small backend change); webhook enable/disable + secret rotation and routing‑rule edit (need backend endpoints); ticket delete / bulk actions (need backend endpoints).

## Phase 5 — AI moat (post‑PMF)

### ✅ M5.1 — Prompt versioning + eval harness — DONE

Versioned prompt registry (`app/prompts.py`, `get_prompt` fail‑safe) recorded on
`analyses.prompt_version` (migration `0011`); a provider‑agnostic eval harness
(`app/eval/`) scoring category/priority accuracy against `GOLDEN_CASES`, with a
`python -m app.eval` CLI + opt‑in `eval.yml` CI gate (skipped without a key
secret). Default tests score a fake provider (no live LLM). Design decision:
**D32**. See [23_prompts_eval.md](23_prompts_eval.md) and
[13_completed_milestones.md](13_completed_milestones.md).

<details><summary>Original M5.1 spec (for reference)</summary>

- **Goal:** make the analysis prompt an explicit, **versioned** artifact, and add
  an **eval harness** that measures analysis quality against known‑good labels so
  prompt/model changes can be **gated in CI** (no silent quality regressions).
- **Suggested shape (follow the existing ports/abstractions DNA — D2/D3):**
  - **Prompt versioning:** extract the prompt construction that currently lives
    inside `OpenAIProvider` into a small versioned prompt module/registry (e.g.
    `app/ai/prompts.py` with a `PromptVersion`/`PROMPT_VERSIONS` map and a current
    selector, mirroring the `_PROVIDERS` registry). Record the **prompt version**
    used alongside each analysis (like `model` today) — either a new nullable
    `analyses.prompt_version` column (**migration `0011`**, additive/back‑compat)
    or carried in metrics/logs first. Keep the provider’s structured‑output
    contract (`TicketAnalysis`) unchanged.
  - **Eval harness:** a harness that replays a **golden set** (a small curated
    fixture of tickets + expected category/priority) and/or the captured
    **`feedback`** rows (`corrected_category`/`corrected_priority` as ground‑truth
    labels) through a chosen provider + prompt version, computing accuracy
    (category/priority match rate, etc.). Offline‑runnable with a fake/recorded
    provider (default suite, no live LLM); a `skipif`/opt‑in mode uses the real
    provider. Live behind an abstraction so any provider works.
  - **CI gate:** a pytest‑based eval (or a script) that fails when accuracy drops
    below a threshold — the "gate prompt/model changes" deliverable.
- **Invariants to preserve:** `Provider*` translation + `TicketAnalysis` contract;
  best‑effort persistence; never edit shipped migrations (add `0011`); green at
  every step; the eval default path needs **no live infra** (fake/recorded
  provider), matching the testing DNA ([11_testing_strategy.md](11_testing_strategy.md)).
- **Depends on:** the `feedback` table (M3.2, done) for real labels; the AI
  provider abstraction (done).

</details>

### ✅ M5.2 — RAG over the knowledge base — DONE

Provider‑agnostic **embeddings** abstraction (`app/embeddings/`, OpenAI‑compatible
+ a keyless `hash` provider) + a **tenant‑isolated vector store** behind a port
(`documents`/`document_chunks`, JSONB embeddings, migration `0012`) + pure
chunking/similarity helpers + a `RagService` and KB endpoints
(`/v1/orgs/{id}/documents[/search]`). Grounding is opt‑in (`RAG_ENABLED` +
`LLM_PROMPT_VERSION=v2`, an append‑only context‑aware prompt): `run_analysis`
retrieves **best‑effort** on the tenant path and folds context into the provider
call (additive `analyze(context=…)`) and the cache key. Every vector is scoped by
`organization_id`. Design decision **D33**. See [24_rag.md](24_rag.md) and
[13_completed_milestones.md](13_completed_milestones.md).

<details><summary>Original M5.2 spec (for reference)</summary>

Vector store + retrieval to ground analyses/replies in an org's knowledge base and
resolved tickets; **tenant‑isolated** embeddings (scope every vector by
`organization_id`, like every other store). Likely adds an embeddings provider
abstraction (mirroring the LLM provider), a `documents`/`embeddings` schema
(pgvector or an external vector DB behind a port), and a retrieval step feeding
context into `run_analysis`. Depends on M5.1 (so retrieval changes are eval‑gated).

</details>

### ✅ M5.3 — Auto‑resolve + agentic actions (human‑approved, audited) — DONE

A suggester (`RuleBasedActionSuggester` offline default / `LlmActionSuggester`
opt‑in, reusing the provider) **proposes** resolution actions; a pure state
machine gates them so **execution requires prior human approval**; approved
actions run through `ActionHandler`s (internal ticket mutations or signed webhooks
for destructive/outward effects, reusing M3.3b); and **every transition is written
to an append‑only, tenant‑scoped audit log**. Endpoints:
`/v1/tickets/{id}/actions/{suggest,,{aid}/{approve,reject,execute}}` +
`/v1/orgs/{org_id}/audit-logs`. Migration `0013`. Design decision **D34**. See
[25_actions.md](25_actions.md) and [13_completed_milestones.md](13_completed_milestones.md).

**Phase 5 (the AI moat) is complete.** Natural follow‑ups (not a core milestone):
more action types + a real refund integration, opt‑in auto‑approval of safe
internal actions, a frontend action/approval UI + audit viewer, grounding
suggestions in RAG context; plus the M5.2 follow‑ups (RAG on batch/channel paths,
past‑ticket indexing, pgvector, KB UI).

## Recommended order & dependencies

```
M2.4 (RBAC + /v1/analyze) ──► M2.5 (billing) ──► rate limiting / refresh rotation
        │
        └─► Phase 3 (tickets, feedback, batch, routing, channels)
                    │
                    └─► Phase 4 (analytics, frontend) ──► Phase 5 (AI moat)
```

- Everything downstream depends on **M2.4** landing tenant scoping + RBAC cleanly (it's the linchpin).
- Billing (M2.5) depends on `usage_events` + tenancy.
- Frontend (Phase 4) depends on auth (done) + tickets API (M3.1).

## Cross‑cutting infra to add along the way

- **CI Postgres/Redis services** → un‑skip integration tests, run `alembic upgrade head`, add `alembic check`.
- **Split `app/db/models.py`** into `app/db/models/` — **now at 18 models (well past the ~8 threshold); overdue standalone chore.** Keep imports working via the package `__init__`.
- **OpenTelemetry tracing** + Grafana dashboards; per‑tenant metric labels (watch cardinality).
- **Secrets manager** instead of `.env` for production.
- **Multi‑stage Dockerfile** + pinned base digest; SBOM/image scan in CI.

## Expected architecture evolution

- The **ports/registry pattern generalizes**: RBAC = a `require_role` dependency; billing = a `BillingService` + `usage_events` store; queue = a `TaskQueue` port with a Celery/arq impl; webhooks = a `WebhookDispatcher`. Keep following D2/D3‑style abstractions.
- `app/api/v1/` may become the home for versioned routers as they multiply (currently routers live beside their domain: `app/auth/routes.py`, `app/tenancy/routes.py`).
- Analytics likely needs an OLAP store (ClickHouse/BigQuery or Postgres materialized views) separate from OLTP.

Phase 5 is complete, so there is no next *core* milestone — see [15_handoff.md](15_handoff.md) for how to pick up the deferred/housekeeping work (or a Phase 5 follow‑up) safely.
