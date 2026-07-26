# AI Ticket Analyzer

[![CI](https://github.com/Kunal1703/AI-ticket-analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/Kunal1703/AI-ticket-analyzer/actions/workflows/ci.yml)

An AI-powered customer support ticket analysis service built with FastAPI. It classifies tickets by category and priority, generates concise summaries, and suggests actionable next steps — all via a single API endpoint. It is **provider-agnostic**: OpenAI, Groq, Together AI, OpenRouter, Ollama, and any OpenAI-compatible endpoint are supported out of the box.

## Overview

Customer support teams handle thousands of tickets daily. AI Ticket Analyzer automates the triage step by:

- **Summarizing** the ticket in one or two sentences
- **Categorizing** into one of eight support categories
- **Assessing priority** (Low → Critical)
- **Suggesting next actions** for the support agent

The service uses OpenAI's structured output capabilities to ensure strongly-typed, validated responses every time.

## Tech Stack

| Component       | Technology                     |
|-----------------|--------------------------------|
| Runtime         | Python 3.12+                   |
| Framework       | FastAPI                        |
| AI Providers    | OpenAI / Groq / Together / OpenRouter / Ollama / OpenAI-compatible |
| Validation      | Pydantic v2                    |
| Containerization| Docker                         |
| Testing         | pytest + httpx                 |

## Setup

### Prerequisites

- Python 3.12+
- OpenAI API key
- Docker (optional)

### Installation

```bash
# Clone the repository
git clone https://github.com/your-username/ai-ticket-analyzer.git
cd ai-ticket-analyzer

# Create virtual environment
python -m venv venv
source venv/bin/activate    # macOS/Linux
venv\Scripts\activate       # Windows

# Install dependencies
pip install -r requirements.txt
```

### Environment Variables

Copy the example environment file and configure a provider:

```bash
cp .env.example .env 
```

Edit `.env` to select a provider and its credentials. For OpenAI:

```
AI_PROVIDER=openai
LLM_API_KEY=sk-your-actual-api-key   # OPENAI_API_KEY also accepted
```

For a local, keyless provider:

```
AI_PROVIDER=ollama
LLM_MODEL=llama3.1
```

| Variable            | Required | Default              | Description                          |
|---------------------|----------|----------------------|--------------------------------------|
| `AI_PROVIDER`       | ❌        | `openai`             | Backend: `openai`, `groq`, `together`, `openrouter`, `ollama`, `openai-compatible` |
| `LLM_API_KEY`       | ⚠️        | —                    | Provider API key. Required except for keyless providers (e.g. `ollama`). Alias: `OPENAI_API_KEY` |
| `LLM_MODEL`         | ❌        | per-provider default | Model identifier. Alias: `OPENAI_MODEL` |
| `LLM_BASE_URL`      | ❌        | per-provider default | API base URL. Required for `openai-compatible` |
| `LLM_TIMEOUT`       | ❌        | `30`                 | Request timeout (seconds). Alias: `OPENAI_TIMEOUT` |
| `LLM_MAX_RETRIES`   | ❌        | `3`                  | Max attempts incl. first try. Alias: `OPENAI_MAX_RETRIES` |
| `LLM_TEMPERATURE`   | ❌        | `0.2`                | Sampling temperature                 |
| `CACHE_TTL_SECONDS` | ❌        | `300`                | Cache TTL for analyses (seconds); `0` disables caching |
| `LOG_LEVEL`         | ❌        | `INFO`               | Logging level (used when `DEBUG=false`) |
| `LOG_FORMAT`        | ❌        | `json`               | Log format: `json` (structured) or `text` |
| `DEBUG`             | ❌        | `false`              | When `true`, forces log level to `DEBUG` |
| `CORS_ALLOW_ORIGINS`| ❌        | localhost dev origins | Allowed browser origins (JSON array)   |
| `CORS_ALLOW_CREDENTIALS`| ❌    | `false`              | Allow credentialed CORS (not with `*`) |
| `DATABASE_URL`      | ❌        | —                    | SQLAlchemy URL for persistence (app runs without it) |
| `REDIS_URL`         | ❌        | —                    | Redis URL for a shared cache; falls back to in-memory when unset |
| `JWT_SECRET`        | ❌        | —                    | Enables auth endpoints (also requires `DATABASE_URL`) |
| `JWT_ALGORITHM`     | ❌        | `HS256`              | JWT signing algorithm |
| `ACCESS_TOKEN_TTL_SECONDS`  | ❌ | `900`                | Access-token lifetime |
| `REFRESH_TOKEN_TTL_SECONDS` | ❌ | `1209600`            | Refresh-token lifetime |

The service is **provider-agnostic** — OpenAI is just one backend. The
OpenAI-compatible providers (`openai`, `groq`, `together`, `openrouter`,
`ollama`, and any `openai-compatible` endpoint via `LLM_BASE_URL`) work today;
providers with different APIs (e.g. Anthropic, Gemini) can be added by
implementing `AnalysisProvider` and registering them — no business-logic,
route, service, or persistence changes required.

## Running Locally

```bash
# Start the development server
uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

## Running with Docker

```bash
# Build the image
docker build -t ai-ticket-analyzer .

# Run the container
docker run -p 8000:8000 --env-file .env ai-ticket-analyzer
```

Or using Docker Compose:

```bash
docker-compose up --build
```

### Networking: host vs. containers

The database and cache URLs differ depending on **where the code runs**:

- **Host tools** (Alembic, pytest, local scripts) connect over published ports on
  `localhost` — e.g. `DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5433/ticket_analyzer`
  and `REDIS_URL=redis://localhost:6379/0`. These are the values in `.env` /
  `.env.example`.
- **Containers** on the Compose network reach each other by **service name**, not
  `localhost` — the `api` service uses `@db:5432` and `redis://cache:6379/0`
  (set in `docker-compose.yml`, which overrides the `.env` values inside the
  container).

So `.env` stays host-oriented for your local workflow, while `docker-compose.yml`
supplies the in-network addresses for the running containers.

## API Usage

### `POST /analyze`

Analyze a customer support ticket.

#### Example Request

```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "ticket": "I upgraded yesterday but my account still shows the free plan. I have already been charged twice."
  }'
```

#### Example Response

```json
{
  "summary": "Customer upgraded but account remains on free plan and was charged twice.",
  "category": "Billing",
  "priority": "High",
  "next_actions": [
    "Verify payment records",
    "Check account subscription status",
    "Issue refund if duplicate charge confirmed"
  ]
}
```

### `GET /health`

Health check endpoint.

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

### `GET /ready`

Readiness probe — verifies the service's dependencies (database, cache) are
reachable. Returns `200` when ready, `503` otherwise. Does **not** call the AI
provider (a third-party outage should not flap the pod out of rotation).

```bash
curl http://localhost:8000/ready
```

```json
{
  "status": "ready",
  "checks": { "database": "not_configured", "cache": "ok", "provider": "ok" }
}
```

Use `/health` for **liveness** (process up) and `/ready` for **readiness**
(dependencies reachable).

### `GET /metrics`

Prometheus metrics (request counts/latency, analyses, cache hit/miss, LLM token
usage) in the standard exposition format.

```bash
curl http://localhost:8000/metrics
```

### Observability

- **Structured logs** — JSON by default (`LOG_FORMAT=text` for local dev), each line correlated with the request's `X-Request-ID`.
- **Metrics** — exposed at `/metrics` for Prometheus scraping.
- **Token usage** — prompt/completion/total tokens are captured per analysis: exported as metrics and persisted on the `analyses` row (`token_usage`) when a database is configured.

## Authentication

Authentication is **provider-agnostic** (mirrors the AI provider design). Local
email/password is implemented; federated providers (Google, GitHub, Microsoft
Entra, Auth0, any OIDC/OAuth2) can be added by implementing `AuthProvider` and
registering it — no changes to routes, services, or authorization. Auth requires
`JWT_SECRET` **and** `DATABASE_URL`; without them the endpoints return `503`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/auth/signup` | Register (email, password) → tokens |
| `POST` | `/v1/auth/login` | Authenticate → tokens |
| `POST` | `/v1/auth/refresh` | Exchange a refresh token for a new pair |
| `GET`  | `/v1/auth/me` | Current user (Bearer access token) |

Passwords are hashed with Argon2; sessions use signed JWT access + refresh
tokens.

## Multi-tenancy & API keys

Every request resolves to a **tenant context** (an organization). Callers
authenticate either as a **user** (JWT) or via an **API key**:

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/orgs` | Create an organization (caller becomes owner) |
| `GET`  | `/v1/orgs` | List the caller's organizations |
| `POST` | `/v1/orgs/{org_id}/api-keys` | Create an API key (secret shown once) |
| `GET`  | `/v1/orgs/{org_id}/api-keys` | List keys (metadata only) |
| `DELETE` | `/v1/orgs/{org_id}/api-keys/{key_id}` | Revoke a key |
| `GET`  | `/v1/tenant` | The resolved tenant context |

- **API key** callers send `X-API-Key: atk_…`; the key resolves directly to its
  organization. Keys are stored **hashed** (SHA-256), are **scoped**, and are
  **revocable** (a revoked key stops resolving).
- **User** callers send `Authorization: Bearer <jwt>`; the org is their single
  membership, or is selected with an `X-Organization-Id` header when they belong
  to several.
- Org-scoped endpoints enforce **membership** — a user cannot act on an
  organization they do not belong to (403).
- **RBAC:** membership `role` (`owner`/`admin`/`manager`/`agent`/`readonly`) is
  enforced via `require_role` — e.g. creating/revoking API keys requires
  `owner`/`admin`. API-key **scopes** are enforced via `require_scope`.

### `POST /v1/analyze` (tenant-scoped)

Authenticated, tenant-scoped analysis. Resolves the organization from a user JWT
or an `X-API-Key` (which must hold the `analyze` scope) and persists the result
under that organization. The legacy unauthenticated `POST /analyze` remains for
backward compatibility (not tenant-scoped). Both share one `run_analysis`
orchestration (cache → provider → metrics → best-effort persistence).

### Error Responses

| Status | `error.code`        | Description                             |
|--------|---------------------|-----------------------------------------|
| `422`  | `validation_error`  | Validation error (empty/missing ticket) |
| `429`  | `rate_limited`      | OpenAI rate limit exceeded              |
| `502`  | `upstream_error`    | OpenAI API failure                      |
| `504`  | `upstream_timeout`  | OpenAI API timeout                      |
| `500`  | `internal_error`    | Unexpected internal error               |

All error responses share a consistent envelope. Every response (success or
error) also includes an `X-Request-ID` header for correlation; clients may send
their own `X-Request-ID` to have it echoed back.

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "request_id": "3f9c1e2a4b5d6e7f8a9b0c1d2e3f4a5b",
    "details": [ ... ]
  }
}
```

`details` is present only for validation errors. Responses also carry standard
security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`).

## Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_models.py
pytest tests/test_api.py
```

## Development

Development tooling (linting, formatting, type checking, coverage) is declared in
`requirements-dev.txt` and configured in `pyproject.toml`. The same checks run in
CI via GitHub Actions (`.github/workflows/ci.yml`).

```bash
# Install runtime + development dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Lint
ruff check .

# Auto-format (and import sorting)
ruff format .

# Verify formatting without modifying files (as CI does)
ruff format --check .

# Static type checking (app package)
mypy

# Tests with coverage
pytest --cov --cov-report=term-missing
```

| Tool   | Purpose                          | Config              |
|--------|----------------------------------|---------------------|
| Ruff   | Linting + formatting             | `pyproject.toml`    |
| Mypy   | Static type checking             | `pyproject.toml`    |
| Pytest | Test runner + coverage           | `pytest.ini` / `pyproject.toml` |

## Database & Migrations

Persistence uses PostgreSQL via SQLAlchemy 2 (async, psycopg driver) with
Alembic migrations. **The service runs fine without a database.** When
`DATABASE_URL` is set, each successful (non-cached) analysis is persisted
**best-effort**: a ticket (deduplicated by content hash) plus a versioned
analysis row are written. Persistence failures are logged and never affect the
API response.

```bash
# Start a local Postgres (via docker compose)
docker compose up -d db

# Point the app/migrations at it
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/ticket_analyzer

# Apply migrations
alembic upgrade head
```

`DATABASE_URL` is read from the environment by both the application and Alembic.
The same `postgresql+psycopg://` URL works for the async app engine and the
synchronous migration engine.

## Project Structure

```
ai-ticket-analyzer/
├── .github/
│   └── workflows/
│       └── ci.yml         # CI: lint, format, type-check, test
├── app/
│   ├── __init__.py
│   ├── main.py            # App factory (create_app), routes, wiring
│   ├── dependencies.py    # FastAPI dependency providers (DI)
│   ├── cache/             # Cache protocol + backends (in-memory, Redis)
│   │   ├── __init__.py
│   │   ├── base.py        # Cache protocol + cache_key
│   │   ├── memory.py      # In-memory TTLCache
│   │   ├── redis.py       # RedisCache (shared, best-effort)
│   │   └── factory.py     # build_cache (backend selection)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── logging.py     # Log-level resolution + configuration
│   │   ├── middleware.py  # Request-id + security-headers middleware
│   │   └── errors.py      # Error envelope + exception handlers
│   ├── ai/                # Provider abstraction (pluggable AI backends)
│   │   ├── __init__.py
│   │   ├── base.py        # AnalysisProvider interface + Provider* errors
│   │   ├── config.py      # ProviderConfig (neutral provider config)
│   │   ├── openai_provider.py  # OpenAI / OpenAI-compatible implementation
│   │   └── factory.py     # Provider registry + build_provider
│   ├── auth/              # Provider-agnostic authentication
│   │   ├── __init__.py
│   │   ├── base.py        # AuthProvider interface, identity, UserStore, errors
│   │   ├── password.py    # Argon2 hashing
│   │   ├── tokens.py      # JWT access/refresh TokenService
│   │   ├── local_provider.py  # Email/password provider
│   │   ├── factory.py     # Auth provider registry
│   │   ├── service.py     # AuthService (signup/login/refresh/me)
│   │   └── routes.py      # /v1/auth/* endpoints
│   ├── tenancy/           # Organizations, API keys, tenant context
│   │   ├── __init__.py
│   │   ├── base.py        # TenantContext, OrgStore/ApiKeyStore ports, errors
│   │   ├── api_key.py     # API key generation + hashing
│   │   ├── service.py     # OrganizationService, ApiKeyService
│   │   └── routes.py      # /v1/orgs, /v1/orgs/{id}/api-keys, /v1/tenant
│   ├── db/                # Persistence layer (SQLAlchemy)
│   │   ├── __init__.py
│   │   ├── base.py        # Declarative Base + naming convention
│   │   ├── models.py      # ORM models (Ticket, Analysis, Organization, User, ...)
│   │   ├── repositories.py  # Ticket/analysis data-access helpers
│   │   ├── user_store.py  # SQLAlchemy user store (auth port impl)
│   │   ├── org_store.py   # SQLAlchemy org/membership store
│   │   ├── api_key_store.py  # SQLAlchemy API key store
│   │   └── session.py     # Async engine / sessionmaker factories
│   ├── services/          # Orchestration between API and persistence
│   │   ├── __init__.py
│   │   └── analysis_service.py  # Best-effort persistence
│   ├── observability/     # Prometheus metrics
│   │   ├── __init__.py
│   │   └── metrics.py
│   ├── openai_client.py   # Backward-compatible facade over app.ai
│   ├── readiness.py       # Dependency readiness checks (/ready)
│   ├── models.py          # Pydantic models, enums
│   ├── prompts.py         # System prompt, user prompt builder
│   └── config.py          # Environment variable management
├── alembic/               # Database migrations
│   ├── env.py
│   └── versions/
├── alembic.ini
├── tests/                 # pytest suite (unit + API integration)
│   └── ...
├── Dockerfile
├── docker-compose.yml
├── requirements.txt       # Runtime + test dependencies
├── requirements-dev.txt   # Lint/type/coverage tooling
├── pyproject.toml         # Ruff / Mypy / Coverage config
├── pytest.ini
├── .env.example
├── .gitignore
├── README.md
├── architecture.md
└── AI_USAGE.md
```

## Design Decisions

1. **Direct OpenAI API over LangChain** — The use case is a single prompt-response pattern. LangChain adds unnecessary abstraction, dependency weight, and complexity. See [architecture.md](architecture.md) for a full comparison.

2. **Structured Outputs over JSON parsing** — OpenAI's `response_format` with a Pydantic schema guarantees valid JSON conforming to our model, eliminating fragile regex/JSON parsing of free-form text.

3. **Tenacity for retries** — Provides exponential backoff with jitter, selective retry on transient errors (timeouts, rate limits, connection issues), and configurable stop conditions.

4. **In-memory LRU cache with TTL** — Avoids redundant API calls for identical tickets. Entries expire after `CACHE_TTL_SECONDS` (default 300s; set to `0` to disable). Simple and effective for single-instance deployments without adding Redis complexity.

5. **Pydantic v2 + pydantic-settings** — Type-safe configuration with automatic `.env` loading, validation, and environment variable override support.

6. **Provider abstraction (`app/ai`)** — Ticket analysis is performed through an `AnalysisProvider` interface resolved by a registry/factory. OpenAI is the only implementation today; new backends (e.g. Anthropic, Gemini, Ollama) can be added by implementing the interface and registering them — without changing any business logic.

## Future Improvements

- **Persistent caching** — Replace in-memory LRU with Redis for multi-instance deployments
- **Authentication** — Add API key or JWT authentication middleware
- **Rate limiting** — Per-client rate limiting to prevent abuse
- **Batch analysis** — Accept multiple tickets in a single request
- **Webhook support** — Async processing with callback notifications
- **Observability** — OpenTelemetry tracing and Prometheus metrics
- **Multi-language** — Support ticket analysis in non-English languages
- **Confidence scores** — Return model confidence for category/priority classification

## License

MIT
