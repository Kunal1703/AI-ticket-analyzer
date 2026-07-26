# 03 — Database

Files: `app/db/base.py` (declarative `Base` + naming convention), `app/db/models.py` (all ORM models), `app/db/session.py` (engine/sessionmaker factories), `alembic/` (migrations). See also [08_persistence.md](08_persistence.md).

## Ground rules (why the DB is the way it is)

- **PostgreSQL only.** Models use PG‑specific types (`UUID(as_uuid=True)`, `JSONB`). No SQLite compatibility — it wasn't worth constraining the schema, and tests use fakes/mocked sessions instead (see [11_testing_strategy.md](11_testing_strategy.md)).
- **One driver, two modes.** `psycopg` v3 (`postgresql+psycopg://`) is used by the *async* app engine **and** the *sync* Alembic engine. This is why a single URL works everywhere; do not reintroduce asyncpg/psycopg2.
- **Explicit constraint naming.** `Base.metadata` uses a `NAMING_CONVENTION` (`ix_`, `uq_`, `ck_`, `fk_`, `pk_`) so Alembic autogenerate and hand‑written migrations produce identical, stable names. Migrations use `op.f("...")` with these names.
- **The app runs without a DB.** `database_url` is optional. Importing `app.main` does not open a connection; the engine is built in `create_app` only when configured, and disposed in `lifespan`.

## Tables

### `tickets`
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK, `default=uuid4` |
| `organization_id` | UUID | **yes** | FK → `organizations.id` `ON DELETE CASCADE`, indexed. Nullable for back‑compat (added M2.1). |
| `raw_text` | Text | no | |
| `text_hash` | String(64) | no | indexed; sha256 of normalized text (dedupe key) |
| `source` | String(32) | no | default `"api"`; ingestion channel — `api`/`email`/`csv` (M3.5) |
| `status` | String(32) | no | default `"open"` (`server_default`); lifecycle `open`/`in_progress`/`pending`/`resolved`/`closed` — M3.6; enum *value* string, updated via `PATCH /v1/tickets/{id}` |
| `assignee` | String(255) | **yes** | routing outcome (M3.4a) **or** manual assignment (M3.6, `PATCH`); set by `POST /v1/tickets/{id}/route` or `PATCH /v1/tickets/{id}` |
| `sla_due_at` | timestamptz | **yes** | SLA deadline (M3.4a) |
| `created_at` | timestamptz | no | `server_default=now()` |

Relationship: `analyses` (one‑to‑many, cascade delete‑orphan); `organization` (many‑to‑one, nullable).

### `analyses` (append‑only / versioned)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `organization_id` | UUID | **yes** | FK → orgs, cascade, indexed (M2.1) |
| `ticket_id` | UUID | no | FK → `tickets.id` cascade, indexed |
| `summary` | Text | no | |
| `category` | String(64) | no | stored as the enum *value* string |
| `priority` | String(32) | no | enum value string |
| `next_actions` | JSONB | no | list[str] |
| `model` | String(128) | **yes** | model id that produced it (`provider.model`) — added M1.2 |
| `prompt_version` | String(32) | **yes** | prompt version that produced it (`app.prompts`) — added M5.1 |
| `token_usage` | JSONB | **yes** | `{prompt_tokens, completion_tokens, total_tokens}` — added M1.4 |
| `created_at` | timestamptz | no | `server_default=now()` |

**Why versioned:** re‑analyzing the same ticket (after cache TTL) appends a *new* `Analysis` row under the same `Ticket` (deduped by `text_hash`). We never overwrite an analysis — this preserves history and enables future analytics.

### `organizations` (tenant root — M2.1)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `name` | String(255) | no | |
| `slug` | String(255) | no | **unique**; generated as `slugify(name)-<hex>` |
| `plan` | String(32) | no | default `"free"` |
| `status` | String(32) | no | default `"active"` |
| `stripe_customer_id` | String(255) | yes | **unique**; Stripe customer linkage (M2.5b), null until linked |
| `created_at` | timestamptz | no | |

Relationships: `memberships`, `api_keys` (cascade delete‑orphan).

### `users` (M2.1; populated by auth M2.2)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `email` | String(320) | no | **unique** |
| `password_hash` | String(255) | **yes** | Argon2 hash; nullable so federated (OAuth) users can exist without a password |
| `name` | String(255) | yes | |
| `is_verified` | Boolean | no | `server_default=false` |
| `created_at` | timestamptz | no | |

Relationship: `memberships`.

### `memberships` (user ↔ org, with role)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `organization_id` | UUID | no | FK → orgs cascade, indexed |
| `user_id` | UUID | no | FK → users cascade, indexed |
| `role` | String(32) | no | default `"member"`; owner set on org creation. **Enforced via `require_role` (M2.4)**; stored as a free‑text string holding a `Role` enum value (not a DB enum). Member invites / role assignment deferred, so orgs have only their owner today. |
| `created_at` | timestamptz | no | |
| — | — | — | **UNIQUE(organization_id, user_id)** (`uq_memberships_organization_id`) |

### `api_keys` (M2.1 schema; lifecycle M2.3)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `organization_id` | UUID | no | FK → orgs cascade, indexed |
| `name` | String(255) | no | |
| `key_hash` | String(128) | no | **unique**; sha256 of the plaintext. **Plaintext is never stored.** |
| `prefix` | String(16) | no | indexed; non‑secret display hint (`atk_xxxx…`) |
| `scopes` | JSONB | yes | list[str] (default `["analyze"]`); **enforced for API‑key principals via `require_scope`** (M2.4) |
| `last_used_at` | timestamptz | yes | best‑effort, updated on auth |
| `revoked_at` | timestamptz | yes | non‑null ⇒ revoked; a revoked key stops resolving |
| `created_at` | timestamptz | no | |

### `usage_events` (billing/metering — M2.5a)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `organization_id` | UUID | **no** | FK → orgs cascade. **NOT NULL** — metering only exists on the authenticated `/v1/analyze` path (unlike tickets/analyses). |
| `event_type` | String(32) | no | default `"analysis"`; the metered unit |
| `quantity` | Integer | no | default `1`; summed for quota counting |
| `model` | String(128) | yes | model id that produced the analysis |
| `total_tokens` | Integer | yes | denormalized token total (from `TokenUsage`) |
| `created_at` | timestamptz | no | `server_default=now()` |
| — | — | — | composite index **`ix_usage_events_organization_id_created_at`** `(organization_id, created_at)` backs the per‑period quota count |

Append‑only. One row per real (cache‑miss) tenant‑scoped analysis, written best‑effort (see [16_billing.md](16_billing.md)). No FK to `analyses` (that row is best‑effort and may not exist).

### `processed_webhook_events` (webhook idempotency — M2.5b)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `provider` | String(32) | no | billing backend (e.g. `"stripe"`) |
| `event_id` | String(255) | no | **unique**; the provider's event id — replays are ignored |
| `event_type` | String(128) | no | provider event type |
| `created_at` | timestamptz | no | `server_default=now()` |

No FK (webhook events aren't tenant‑owned rows). The unique `event_id` is the idempotency guard (see [16_billing.md](16_billing.md)).

### `feedback` (human feedback on analyses — M3.2)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `organization_id` | UUID | **no** | FK → orgs cascade, indexed (tenant‑scoped) |
| `ticket_id` | UUID | **no** | FK → tickets cascade, indexed |
| `analysis_id` | UUID | **no** | FK → analyses cascade; the rated analysis version |
| `rating` | String(16) | no | `positive` / `negative` |
| `corrected_category` | String(64) | yes | human's corrected category (training label) |
| `corrected_priority` | String(32) | yes | human's corrected priority |
| `comment` | Text | yes | free‑text note |
| `created_at` | timestamptz | no | `server_default=now()` |

Additive training signal (see [17_tickets.md](17_tickets.md)). Feedback references a specific analysis; never mutates it.

### `batch_jobs` (async batch‑analyze tracking — M3.3a)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `organization_id` | UUID | **no** | FK → orgs cascade, indexed (tenant‑scoped) |
| `status` | String(32) | no | `queued`/`running`/`completed`/`completed_with_errors`/`failed` |
| `total` | Integer | no | number of items submitted |
| `completed` | Integer | no | items analyzed OK |
| `failed` | Integer | no | items that errored |
| `created_at` | timestamptz | no | `server_default=now()` |
| `updated_at` | timestamptz | no | `server_default=now()`, `onupdate=now()` |

Tracks a batch job's progress; the individual results are ordinary tickets/analyses under the org (see [18_jobs.md](18_jobs.md)).

### `webhooks` (outbound webhook registrations — M3.3b)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `organization_id` | UUID | **no** | FK → orgs cascade, indexed |
| `url` | String(2048) | no | delivery endpoint |
| `secret` | String(255) | no | per‑webhook HMAC signing key — **retained** (we sign with it), unlike hashed API keys; encrypt at rest in prod |
| `event_types` | JSONB | no | subscription list (e.g. `["batch.completed"]`) |
| `active` | Boolean | no | `server_default true` |
| `created_at` | timestamptz | no | `server_default=now()` |

### `webhook_deliveries` (delivery audit/log — M3.3b)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `webhook_id` | UUID | **no** | FK → webhooks cascade, indexed |
| `organization_id` | UUID | **no** | FK → orgs cascade, indexed |
| `event_type` | String(64) | no | |
| `payload` | JSONB | no | the delivered body |
| `status` | String(16) | no | `pending`/`delivered`/`failed` |
| `attempts` | Integer | no | attempts made |
| `response_status` | Integer | yes | last HTTP status |
| `error` | String(512) | yes | last error |
| `created_at`/`updated_at` | timestamptz | no | `server_default=now()` (updated_at `onupdate`) |

Outbound delivery is the mirror of the inbound Stripe verification (see [18_jobs.md](18_jobs.md)).

### `routing_rules` (per‑tenant routing — M3.4a)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `organization_id` | UUID | **no** | FK → orgs cascade, indexed |
| `name` | String(255) | no | |
| `position` | Integer | no | evaluation order (ascending; first active match wins) |
| `conditions` | JSONB | no | subset of `{category, priority}` (all present keys must match) |
| `actions` | JSONB | no | `{assignee?, tags?}` |
| `active` | Boolean | no | `server_default true` |
| `created_at` | timestamptz | no | `server_default=now()` |

### `sla_policies` (per‑tenant SLA — M3.4a)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `organization_id` | UUID | **no** | FK → orgs cascade, indexed |
| `priority` | String(32) | no | the priority this policy targets |
| `resolution_minutes` | Integer | no | deadline = `ticket.created_at + minutes` |
| `active` | Boolean | no | `server_default true` |
| `created_at` | timestamptz | no | `server_default=now()` |

Per‑tenant helpdesk config, applied by `POST /v1/tickets/{id}/route` (see [19_routing.md](19_routing.md)).

### `documents` (RAG knowledge base — M5.2)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `organization_id` | UUID | **no** | FK → orgs cascade, indexed (tenant‑scoped) |
| `title` | String(512) | no | |
| `content` | Text | no | full document (source of truth) |
| `source` | String(32) | no | provenance — `manual` (uploaded) / `ticket` |
| `created_at` | timestamptz | no | `server_default=now()` |

Relationship: `chunks` (one‑to‑many, cascade delete‑orphan).

### `document_chunks` (embedded retrieval units — M5.2)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `organization_id` | UUID | **no** | FK → orgs cascade, indexed — **denormalized** (like `analyses.organization_id`) so similarity search filters by tenant without a join |
| `document_id` | UUID | no | FK → `documents.id` cascade, indexed |
| `chunk_index` | Integer | no | position within the document |
| `content` | Text | no | the chunk text |
| `embedding` | JSONB | no | list[float] — provider/dimension‑agnostic; a pgvector column is a deferred scale optimization |
| `created_at` | timestamptz | no | `server_default=now()` |

Tenant‑scoped knowledge base for retrieval‑augmented analysis (see [24_rag.md](24_rag.md)). Ranking is done in pure Python over the loaded chunks (`app/rag/similarity.py`); the JSONB embedding keeps it offline‑verifiable and model‑agnostic.

### `resolution_actions` (agentic actions — M5.3)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `organization_id` | UUID | **no** | FK → orgs cascade, indexed (tenant‑scoped) |
| `ticket_id` | UUID | no | FK → `tickets.id` cascade, indexed |
| `analysis_id` | UUID | yes | FK → `analyses.id` **SET NULL**; the analysis it was proposed from |
| `action_type` | String(32) | no | `set_status`/`assign`/`add_note`/`send_reply`/`escalate` (enum value string) |
| `params` | JSONB | no | per‑type parameters (e.g. `{"status": "in_progress"}`) |
| `rationale` | Text | yes | why the suggester proposed it |
| `status` | String(16) | no | `server_default 'proposed'`; enforced state machine (`proposed`→`approved`→`executed`/`failed`; `rejected` terminal) |
| `is_destructive` | Boolean | no | `server_default false`; destructive types always require approval |
| `suggested_by` | String(64) | yes | suggester name (`rule`/`llm`) |
| `approved_by` | UUID | yes | the approving user |
| `result` | JSONB | yes | handler outcome / error detail |
| `created_at`/`updated_at` | timestamptz | no | `server_default=now()` (updated_at `onupdate`) |

### `audit_logs` (append‑only audit trail — M5.3)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `organization_id` | UUID | **no** | FK → orgs cascade (tenant‑scoped) |
| `actor_type` | String(16) | no | `user` / `system` / `ai` |
| `actor_id` | String(255) | yes | user id, or the suggester name |
| `action` | String(64) | no | e.g. `action.proposed`/`action.approved`/`action.executed` |
| `resource_type` | String(32) | no | e.g. `resolution_action` |
| `resource_id` | UUID | yes | the affected resource |
| `detail` | JSONB | yes | event payload |
| `created_at` | timestamptz | no | `server_default=now()` |
| — | — | — | composite index **`ix_audit_logs_organization_id_created_at`** backs tenant‑scoped listing |

Append‑only: every resolution‑action transition is recorded so agentic behavior is fully traceable (see [25_actions.md](25_actions.md)).

## Relationships (ER, simplified)

```
organizations 1───* memberships *───1 users
      │ 1                                
      ├──* api_keys                       
      ├──* tickets  1───* analyses        
      └──* analyses  (denormalized org_id) 
```

`analyses.organization_id` is **denormalized** (also derivable via `ticket`) to allow direct tenant‑scoped queries/indexes without a join. Both `tickets.organization_id` and `analyses.organization_id` are **nullable** — the legacy root `/analyze` path writes `NULL`, while the tenant‑scoped paths (`/v1/analyze`, reanalyze, batch, channels) **populate them** (since M2.4). Kept nullable so legacy rows stay valid.

## Migrations (`alembic/versions/`)

Each migration is hand‑written (matching the ORM) and verified **offline** (`alembic upgrade head --sql` with a dummy `DATABASE_URL`) because no live Postgres exists in the dev environment. The chain: `0001_initial → 0002_analysis_token_usage → 0003_tenancy → 0004_usage_events → 0005_billing_webhooks → 0006_feedback → 0007_batch_jobs → 0008_webhooks → 0009_routing_sla → 0010_ticket_status → 0011_analysis_prompt_version → 0012_documents → 0013_resolution_actions` (**thirteen**).

### `0001_initial` — tickets + analyses
Creates the two core tables. *Why:* M1.1 introduced persistence. This is the baseline schema for the analyze pipeline.

### `0002_analysis_token_usage` — `ALTER TABLE analyses ADD COLUMN token_usage JSONB`
*Why:* M1.4 added token/cost capture; usage is persisted per analysis for cost analytics. Additive + nullable, so it never breaks existing rows.

### `0003_tenancy` — organizations, users, memberships, api_keys + `organization_id` on tickets/analyses
*Why:* M2.1 introduced the tenancy data model. Creates the four tenant tables (with unique `slug`, unique `email`, unique `key_hash`, unique `(org,user)` membership, FK cascades, indexes) and adds the **nullable** `organization_id` FK columns to `tickets`/`analyses`. Nullable is deliberate: it's a non‑breaking, back‑compatible addition — nothing is enforced yet.

### `0004_usage_events` — the `usage_events` metering table
*Why:* M2.5a introduced usage metering + plan quotas. Creates `usage_events` (org‑scoped, NOT NULL FK cascade, composite `(organization_id, created_at)` index). Additive; nothing else changes. See [16_billing.md](16_billing.md).

### `0005_billing_webhooks` — webhook idempotency + Stripe customer linkage
*Why:* M2.5b added Stripe webhook ingestion. Creates `processed_webhook_events` (unique `event_id`) and adds a nullable, unique `stripe_customer_id` to `organizations`. Additive/back‑compatible. See [16_billing.md](16_billing.md).

### `0006_feedback` — the `feedback` training‑signal table
*Why:* M3.2 added feedback capture. Creates `feedback` (tenant‑scoped NOT NULL FKs to orgs/tickets/analyses, indexed by org + ticket). Additive. See [17_tickets.md](17_tickets.md).

### `0007_batch_jobs` — async batch‑analyze job tracking
*Why:* M3.3a added async batch analyze. Creates `batch_jobs` (tenant‑scoped NOT NULL FK, status + counts, indexed by org). Additive. See [18_jobs.md](18_jobs.md).

### `0008_webhooks` — outbound webhook registrations + delivery log
*Why:* M3.3b added outbound webhooks. Creates `webhooks` (tenant‑scoped, signing secret, subscriptions) and `webhook_deliveries` (per‑delivery audit). Additive. See [18_jobs.md](18_jobs.md).

### `0009_routing_sla` — routing rules, SLA policies + ticket routing columns
*Why:* M3.4a added per‑tenant routing/SLA. Creates `routing_rules` + `sla_policies` (tenant‑scoped) and adds nullable `assignee`/`sla_due_at` to `tickets`. Additive. See [19_routing.md](19_routing.md).

### `0010_ticket_status` — `ALTER TABLE tickets ADD COLUMN status`
*Why:* M3.6 added ticket lifecycle. Adds a NOT NULL `status` column with `server_default 'open'` (backfills existing rows so the NOT NULL add is safe). Additive/back‑compatible. See [17_tickets.md](17_tickets.md).

### `0011_analysis_prompt_version` — `ALTER TABLE analyses ADD COLUMN prompt_version`
*Why:* M5.1 added prompt versioning. Adds a nullable `prompt_version` column recording which prompt version produced each analysis. Additive/back‑compatible (like `model`). See [23_prompts_eval.md](23_prompts_eval.md).

### `0012_documents` — `documents` + `document_chunks` (RAG knowledge base)
*Why:* M5.2 added retrieval‑augmented generation. Creates `documents` and `document_chunks` (tenant‑scoped NOT NULL FKs, chunk `embedding` as JSONB, org denormalized on the chunk + indexed). Additive. See [24_rag.md](24_rag.md).

### `0013_resolution_actions` — `resolution_actions` + `audit_logs` (agentic actions)
*Why:* M5.3 added human‑approved agentic actions. Creates `resolution_actions` (tenant‑scoped, state‑machine `status`, `is_destructive`, `analysis_id` SET NULL) and the append‑only `audit_logs` (composite `(organization_id, created_at)` index). Additive. See [25_actions.md](25_actions.md).

**Alembic env (`alembic/env.py`):** reads `DATABASE_URL` from the environment (not from `Settings`, so migrations don't require `OPENAI_API_KEY`), imports `Base.metadata` + `app.db.models` for autogenerate, runs synchronously via `engine_from_config`. `alembic.ini` leaves `sqlalchemy.url` blank on purpose.

## How the host vs. container URLs differ

- Host tools (Alembic, pytest, local scripts) → `localhost:5433` (the published Postgres port).
- Containers on the Compose network → `db:5432` (service name), set in `docker-compose.yml`, overriding `.env`.

This is documented in the top‑level README ("Networking: host vs. containers"). Do not "unify" them.

## Future expansion

The blueprint schema (see [14_remaining_roadmap.md](14_remaining_roadmap.md)) adds: `teams`/`team_members`, `integrations`, `audit_logs`. (`usage_events` + `processed_webhook_events` (billing), `feedback` (M3.2), `batch_jobs` (M3.3a), `webhooks`/`webhook_deliveries` (M3.3b), and `routing_rules`/`sla_policies` (M3.4a) are **done**.) There are now **18** ORM models — **well past** the ~8 threshold, so **splitting `app/db/models.py` into an `app/db/models/` package** is an overdue standalone chore, tracked as a post‑Phase‑3 maintenance milestone (imports must keep working via the package `__init__`; see [12_design_decisions.md](12_design_decisions.md)). Add each table as its own migration; never edit a shipped migration — add a new one.
