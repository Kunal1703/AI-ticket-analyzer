# 16 — Billing & Usage Metering

Implemented in **M2.5a** (usage metering + plan-based quota enforcement) and
**M2.5b** (Stripe billing provider + idempotent webhooks + plan sync + usage
endpoint). Files: `app/billing/{__init__,plans,base,service,metering,provider,
stripe_provider,routes}.py`, `app/db/{usage_store,webhook_event_store}.py`,
`app/db/models.py` (`UsageEvent`, `ProcessedWebhookEvent`),
`alembic/versions/{0004_usage_events,0005_billing_webhooks}.py`, billing deps in
`app/dependencies.py`. **Deferred to M2.5c:** outbound Stripe calls (checkout /
subscription creation) — they require a live account/SDK, so they were kept out
of the offline-verifiable slice.

## What M2.5a does

- **Meters** every real (cache-miss) analysis on the tenant-scoped `/v1/analyze`
  as one `usage_events` row for the caller's organization.
- **Enforces** a per-plan **monthly** analysis quota: when an org is at/over its
  plan's limit, `/v1/analyze` returns **HTTP 402** (`payment_required`) *before*
  calling the LLM.
- Leaves the legacy `/analyze` **completely untouched** — never metered, never
  limited (D22 contract preserved).

## The two halves (and why they use different sessions)

This mirrors the two persistence strategies in [08_persistence.md](08_persistence.md):

1. **Enforcement (read) — request-scoped, transactional.** A `require_quota`
   dependency runs before the endpoint body. It reads the org's plan and counts
   in-period usage via a request-scoped session (`get_db_session`). A failure here
   *should* fail the request. Gating happens **at the door**, before spending LLM
   budget.
2. **Metering (write) — best-effort, self-contained.** `record_analysis_usage`
   (`app/billing/metering.py`) opens its **own** short session from the
   sessionmaker, writes one event, commits, and **swallows any exception** — exactly
   like `persist_analysis`. A metering failure only means an unbilled analysis
   (logged); it must never break the response. Metering happens **on the way out**,
   after a successful provider call.

**Only cache misses are metered.** `run_analysis` returns early on a cache hit, so
cached results are not billed — consistent with how token metrics are recorded.
Enforcement, however, runs regardless of cache state (an over-quota org is blocked
even if the answer would have been cached).

## The plan registry (`app/billing/plans.py`)

```python
@dataclass(frozen=True)
class Plan:
    name: str
    monthly_analysis_limit: int | None   # None = unlimited

build_plans(overrides) -> dict[str, Plan]   # placeholder defaults + overrides
get_plan(plans, name) -> Plan               # falls back to DEFAULT_PLAN ("free")
```

- The default limits (`free`/`pro`/`enterprise`) are **placeholders**, not final
  pricing. They are **configurable** at deploy time via
  `Settings.plan_monthly_analysis_limits` (env `PLAN_MONTHLY_ANALYSIS_LIMITS`, a
  JSON object; a `null` value means unlimited). Overrides merge over the defaults,
  so a deployment can retune limits or add plans without code changes.
- The registry is built once in `create_app` and stored on `app.state.plans`;
  `get_billing_service` injects it into the `BillingService`.
- `get_plan` **fails safe**: an unknown plan resolves to the conservative default
  rather than "unlimited"; only a misconfigured registry missing the default falls
  open to unlimited.

## Port, store, service

- **Port** `UsageStore` (`app/billing/base.py`): `record(...)` and
  `count_since(org_id, *, since, event_type) -> int`. Impl `SqlAlchemyUsageStore`
  (`app/db/usage_store.py`); `count_since` sums `quantity` (so batch/quantity>1 is
  handled) over the current period.
- **Service** `BillingService` (`app/billing/service.py`): `check_quota(org_id,
  plan_name)` — resolves the plan, returns immediately for unlimited plans, else
  counts usage since `current_period_start()` (first of the month, 00:00 UTC) and
  raises `QuotaExceededError` when `used >= limit`. Errors: `BillingError →
  QuotaExceededError` (mapped to 402 at the dependency boundary).

## Data model (`usage_events`)

See [03_database.md](03_database.md). Tenant-scoped (`organization_id` **NOT
NULL** — unlike tickets/analyses, metering only exists on the authenticated path),
append-only, with a composite `(organization_id, created_at)` index backing the
per-period count (and serving FK lookups on the leading column). Migration
`0004_usage_events` (chained from `0003_tenancy`), verified offline with `--sql`.

## Wiring (`app/dependencies.py`)

```
/v1/analyze
  └─ Depends(require_quota)
        ├─ Depends(_require_analyze_scope)  → TenantContext (auth + "analyze" scope)
        ├─ Depends(get_org_store)           → OrgStore.get(org_id) → plan
        └─ Depends(get_billing_service)     → BillingService.check_quota → 402 if over
```

`require_quota` returns the `TenantContext`, so the endpoint signature is otherwise
unchanged (it still passes `organization_id` into `run_analysis`, which meters
best-effort). `OrgStore` gained a `get(organization_id)` method for the plan lookup.

## Observability

- `usage_events_total{event_type}` — metered events (incremented after a committed
  write).
- `quota_denied_total{event_type}` — requests rejected at the quota gate.

Labels are low-cardinality (bounded `event_type`), never per-org.

## What must NEVER change

- Legacy `/analyze` stays unmetered and unlimited (D22).
- Metering is **best-effort** (own session, swallows errors) — never breaks the
  response, exactly like `persist_analysis`.
- Enforcement happens **before** the LLM call (protects the budget); 402 for a plan
  cap (429 remains provider rate-limiting).
- `usage_events.organization_id` is NOT NULL (metering is tenant-scoped only).
- Webhooks are **idempotent** (unique `event_id` in `processed_webhook_events`) and
  **signature-verified** inside the provider; routes/services never import the Stripe
  SDK (it stays behind `BillingProvider`, imported lazily). Bad signature → 400.

## M2.5b — Stripe billing provider, webhooks, plan sync, usage endpoint

### Provider-agnostic billing abstraction (`app/billing/provider.py`)

Mirrors `AuthProvider`/`AnalysisProvider`: a `BillingProvider` ABC turns a raw
inbound webhook into a neutral `BillingEvent` (`provider`, `event_id`, `type`,
`organization_id`, `plan`, `customer_id`). A `_PROVIDERS` registry +
`build_billing_provider(settings)` selects the backend by `settings.billing_provider`.
Routes/services depend only on the ABC + the neutral event — never on the Stripe SDK.

### `StripeBillingProvider` (`app/billing/stripe_provider.py`)

Implements `parse_webhook(payload, signature_header)` via
`stripe.Webhook.construct_event` (signature verification delegated to the SDK).
**The `stripe` import is lazy** (inside the provider) so the app imports and the
whole suite runs without the optional dependency installed; a missing SDK, a bad
signature, or a malformed payload all translate to `BillingProviderError` (→ 400).
It maps event types → a target plan: subscription created/updated → the
`stripe_price_plan_map` lookup by price `lookup_key`/`id`; subscription deleted →
the default plan; `checkout.session.completed` → `metadata.plan`. The target org
comes from `metadata.organization_id` (the standard Stripe tenant-linking pattern).

### Idempotent webhook ingestion (`POST /v1/billing/webhook`)

Unauthenticated at the HTTP layer (authenticated by the provider signature),
request-scoped/transactional. `WebhookService.handle`:
1. `provider.parse_webhook(...)` → `BillingEvent` (bad signature → `BillingProviderError` → **400**).
2. **Idempotency:** if `WebhookEventStore.exists(provider, event_id)` → return `"duplicate"` (200, no reprocessing). Backed by `processed_webhook_events` (unique `event_id`).
3. Record the event id, then **plan sync**: load the org (`OrgStore.get`) and set `Organization.plan` (+ `stripe_customer_id` if newly linked). Missing org/plan → `"ignored"`.

Returns `{"status": "plan_updated" | "duplicate" | "ignored"}`. **503** when billing
is not configured (`get_billing_provider`, mirroring auth's 503 without `JWT_SECRET`).

### Usage endpoint (`GET /v1/orgs/{org_id}/usage`)

Org-scoped (`require_org_membership`). Returns `{plan, used, limit, period_start}`
using `BillingService.current_usage` + `plan_for`. (Deferred from M2.5a; landed here.)

### Config / observability

`billing_provider`, `stripe_api_key`, `stripe_webhook_secret` (gates the endpoint),
`stripe_price_plan_map` (configurable price→plan). `billing_webhooks_total{provider,
outcome}` metric. The provider is built once in `create_app` (only when
`stripe_webhook_secret` is set) and stored on `app.state.billing_provider`.

### Testing without a live Stripe

The `stripe` SDK isn't installed in the dev env, so `StripeBillingProvider` is
unit-tested by injecting a fake `stripe` module into `sys.modules` (verifying event
mapping + error translation + the missing-SDK path); the route/service/idempotency/
plan-sync logic is tested with a `FakeBillingProvider` (no SDK). Migration `0005`
verified offline (`--sql`).

## Deferred to M2.5c and beyond

- Outbound Stripe API calls: checkout-session / subscription creation (needs a live
  account + SDK to be meaningful/testable).
- USD cost (currently tokens/quantity only), per-seat/other meters, hard vs. soft
  caps, and rate limiting (separate concern).
