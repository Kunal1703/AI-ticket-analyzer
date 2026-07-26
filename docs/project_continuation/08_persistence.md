# 08 — Persistence

How data reaches Postgres. Implemented in M1.1 (foundation) and M1.2 (best‑effort writes); extended by M1.4 (token usage) and M2.1/M2.3 (tenancy stores). See [03_database.md](03_database.md) for the schema.

## Layers

```
route (/analyze)                       route (/v1/auth/*, /v1/orgs/*)
   │ best-effort, its own session          │ request-scoped session (get_db_session)
   ▼                                        ▼
analysis_service.persist_analysis      Services (AuthService, Org/ApiKeyService)
   │                                        │
   ▼                                        ▼
db/repositories.py (functions)         Stores (UserStore, OrgStore, ApiKeyStore)
   │                                        │
   ▼                                        ▼
ORM models (app/db/models.py) ── SQLAlchemy async engine ── PostgreSQL
```

Two different session strategies coexist deliberately (see below).

## Engine & session factories (`app/db/session.py`)

Pure factory functions, **no global state**:
```python
def create_db_engine(url, *, echo=False) -> AsyncEngine   # lazy; pool_pre_ping
def create_sessionmaker(engine) -> async_sessionmaker[AsyncSession]  # expire_on_commit=False
```
`create_app` builds them only when `DATABASE_URL` is set, stores `db_engine`/`db_sessionmaker` on `app.state`, and `lifespan` disposes the engine. Engine creation opens **no** socket (lazy), so a configured‑but‑down DB doesn't block startup.

## Two session strategies (why)

1. **Best‑effort, self‑contained (analyze path).** `persist_analysis(sessionmaker, ...)` opens its **own** short session, writes, commits, and **swallows any exception**. It receives the *sessionmaker* (or `None`), not a session, because the analyze request must complete and return even if persistence fails or no DB exists. This is the "persistence must never break `/analyze`" rule.

2. **Request‑scoped, transactional (auth/tenancy path).** `get_db_session` (a FastAPI dependency) yields a session and **commits at the end of the request**, rolling back on exception, 503 if no DB. Auth/tenancy operations are the request's purpose, so their failure *should* fail the request (correctly, with rollback).

Do not merge these strategies — they encode different intents.

## Repositories (`app/db/repositories.py`) — ticket/analysis data access

Function‑style repository (not a class) operating on a provided `AsyncSession`:
- `get_or_create_ticket(session, *, raw_text, text_hash, organization_id=None, source="api")` — dedupe by `(text_hash, organization_id)` (org‑scoped since M2.4); flush to assign `id`. `source` (`api`/`email`/`csv`, M3.5) is set on creation.
- `add_analysis(session, *, ticket, analysis, model=None, token_usage=None)` — append a **versioned** analysis row (inherits the ticket's `organization_id`).

**Why "get or create + append":** re‑analysis appends a new `Analysis` under the same `Ticket`, preserving history. Note: `text_hash` is **not** UNIQUE, so concurrent misses could create duplicate tickets — acceptable for best‑effort; add a UNIQUE index / upsert if persistence becomes authoritative.

## Service (`app/services/analysis_service.py`)

`persist_analysis(sessionmaker, *, ticket_text, text_hash, analysis, model, usage, organization_id=None, source="api")`:
- `None` sessionmaker → no‑op.
- else: open session → `get_or_create_ticket` → `add_analysis` (converts `TokenUsage` → dict via `asdict`) → commit; `except Exception: logger.exception(...)` — swallowed.

The route passes `model=provider.model` (provider‑agnostic — not `settings.openai_model`) and `usage=result.usage`.

## Stores (ports + SQLAlchemy impls)

Two binding styles (this is the key thing to know):

**Request‑scoped** (bound to `get_db_session`; share one committed‑at‑end session): `SqlAlchemyUserStore`, `SqlAlchemyOrgStore` (+ `get(org_id)`), `SqlAlchemyApiKeyStore`, `SqlAlchemyUsageStore` (M2.5a), `SqlAlchemyWebhookEventStore` (M2.5b inbound idempotency), `SqlAlchemyTicketStore` (M3.1), `SqlAlchemyFeedbackStore` (M3.2), `SqlAlchemyRoutingRuleStore`/`SqlAlchemySlaPolicyStore` (M3.4a), `SqlAlchemyAnalyticsStore` (M4.1 — aggregate `GROUP BY`/counts), `SqlAlchemyVectorStore` (M5.2 — KB documents/chunks; also used with an **own** session for best‑effort analyze‑path retrieval), `SqlAlchemyActionStore`/`SqlAlchemyAuditStore` (M5.3 — resolution actions + the append‑only audit log).

**Sessionmaker‑backed** (each op opens its **own** short, self‑committing session, so a row created in a request is visible to a later background task): `SqlAlchemyBatchJobStore` (M3.3a), `SqlAlchemyWebhookStore` + `SqlAlchemyWebhookDeliveryStore` (M3.3b). Their `get_*` deps read `app.state.db_sessionmaker` and 503 if absent. This is the **third session strategy** (alongside best‑effort self‑contained and request‑scoped transactional).

## Why failures never break `/analyze`

- No DB configured → `persist_analysis` no‑ops (sessionmaker is `None`).
- DB configured but the write fails → the `try/except Exception` in `persist_analysis` logs and returns; the analyze response was already computed.
- This is explicitly tested (`test_persistence_failure_does_not_break_response`: a failing sessionmaker still yields 200).

## Migrations

Hand‑written, verified offline (`alembic upgrade head --sql`). Chain `0001 → 0002 → 0003 → 0004 → 0005 → 0006 → 0007 → 0008 → 0009 → 0010 → 0011 → 0012 → 0013` (thirteen). See [03_database.md](03_database.md). Never edit a shipped migration — add a new one. `add_analysis` records `model`/`prompt_version` (M5.1)/`token_usage` alongside the versioned analysis.

## Future improvements (tracked debt)

- **Split `app/db/models.py`** — now **18 models**, well past the ~8 threshold; overdue. Tracked as a standalone post‑Phase‑3 maintenance milestone (imports must keep working via the package `__init__`).
- **`text_hash` UNIQUE / upsert** if per‑org persistence becomes authoritative (currently best‑effort; concurrent misses can dup a ticket).
- **Background persistence / durable jobs**: the in‑process `JobRunner` (M3.3a) is single‑instance; a Redis/arq worker (M3.3c) is deferred until real infra.
- **CI Postgres/Redis**: add `services:` jobs to un‑skip the ~16 DB integration tests and run `alembic upgrade head` / `alembic check` end‑to‑end.
