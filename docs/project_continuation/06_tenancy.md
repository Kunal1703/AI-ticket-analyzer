# 06 — Tenancy (Organizations, API Keys, Tenant Context)

Implemented across **M2.1** (schema) and **M2.3** (API keys + tenant context). Files: `app/tenancy/base.py`, `api_key.py`, `service.py`, `routes.py`, `__init__.py`; `app/db/org_store.py`, `app/db/api_key_store.py`; tenancy deps in `app/dependencies.py`; ORM in `app/db/models.py` ([03_database.md](03_database.md)).

## The model

- **Organization** = a tenant. Owns tickets, analyses, memberships, API keys.
- **User** ↔ **Organization** is many‑to‑many via **Membership** (with a `role`).
- **API keys** belong to an organization (machine principals).
- Every request resolves to a **`TenantContext`** — the active org + the principal (user or api_key) — regardless of how it authenticated.

## Why a `TenantContext` abstraction

Two credential types (user JWT vs. API key) must both yield a well‑defined tenant. Rather than let each route special‑case "the user's org" vs "the key's org", business logic depends on one `TenantContext`:

```python
@dataclass(frozen=True)
class TenantContext:
    organization_id: uuid.UUID
    principal_type: str            # "user" | "api_key"
    user_id: uuid.UUID | None = None
    api_key_id: uuid.UUID | None = None
    scopes: tuple[str, ...] = ()
```

**Done (M2.4+):** `/v1/analyze` (via `require_quota` → `require_scope("analyze")` → `get_tenant_context`), plus reanalyze, batch, and channels, resolve the tenant and persist `organization_id`.

## API keys — generation, hashing, revocation (`app/tenancy/api_key.py`)

```python
KEY_PREFIX = "atk_"
def generate_api_key() -> (plaintext, prefix, key_hash)   # plaintext = atk_<token_urlsafe(24)>
def hash_api_key(plaintext) -> str                        # sha256 hex
```

- **Only the hash + a non‑secret `prefix` are stored.** The plaintext is returned **once** at creation (`ApiKeyCreatedResponse.api_key`) and never again.
- **Why SHA‑256, not Argon2:** API keys are high‑entropy random tokens; a fast hash is appropriate and lets `get_active_by_hash` be an indexed lookup. (Passwords use Argon2 — see [05_authentication.md](05_authentication.md).)
- **Revocation** = set `revoked_at`; `get_active_by_hash` filters `revoked_at IS NULL`, so a revoked key immediately stops resolving (tested).
- **Scopes** are stored (default `["analyze"]`), carried into `TenantContext`, and **enforced** for API‑key principals via `require_scope` (M2.4).

## Ports + stores

- `OrgStore` (Protocol): `create(name, slug, owner_id)` (creates org **and** owner membership), `list_for_user`, `get_membership`. Impl: `app/db/org_store.py`.
- `ApiKeyStore` (Protocol): `create`, `get_active_by_hash`, `list_by_org`, `get(org_id, key_id)`, `revoke`, `touch`. Impl: `app/db/api_key_store.py`.
- Fakes for tests live in `tests/test_tenancy_service.py` (`FakeOrgStore`, `FakeApiKeyStore`) and are reused by route tests.

## Services (`app/tenancy/service.py`)

- `OrganizationService`: `create_org` (slug = `slugify(name)-<hex>` to avoid collisions without a lookup), `list_orgs`, `require_membership` (raises `ForbiddenError` if not a member).
- `ApiKeyService`: `create_key` (returns ORM row + one‑time plaintext), `list_keys`, `revoke_key` (`ApiKeyNotFoundError` if missing), `authenticate(plaintext)` (hash → `get_active_by_hash` → `touch`; `TenantNotResolvedError` if invalid/revoked).

Errors: `TenantError` → `TenantNotResolvedError` (401), `ForbiddenError` (403), `ApiKeyNotFoundError` (404).

## Tenant resolution (`get_tenant_context` in `app/dependencies.py`)

```
X-API-Key present?
  yes → api_key_service.authenticate(key) → TenantContext(org=key.org, principal="api_key", scopes=...)
  no  → Authorization: Bearer <jwt> AND token_service configured?
          yes → AuthService.get_current_user(token) → user
                orgs = org_store.list_for_user(user.id)
                  none                       → 403
                  X-Organization-Id header   → validate membership → context (403 if not member)
                  exactly one                → context
                  multiple, no header        → 400 (must select)
          no  → 401
```

**Why it uses `get_optional_token_service` (not `get_token_service`):** an API‑key call must work even when `JWT_SECRET` is unset. Depending on `get_token_service` would 503 the API‑key path. Preserve this.

## Routes (`app/tenancy/routes.py`, prefix `/v1`)

| Method | Path | Guard | Purpose |
|---|---|---|---|
| POST | `/orgs` | `get_current_user` | Create org (caller = owner) |
| GET | `/orgs` | `get_current_user` | List my orgs |
| POST | `/orgs/{org_id}/api-keys` | `require_org_membership` | Create key (secret once) |
| GET | `/orgs/{org_id}/api-keys` | `require_org_membership` | List keys (no secret/hash) |
| DELETE | `/orgs/{org_id}/api-keys/{key_id}` | `require_org_membership` | Revoke (204) |
| GET | `/tenant` | `get_tenant_context` | The resolved tenant context |

`require_org_membership(org_id, current_user, org_service)` reads `org_id` from the path and 403s if the user isn't a member — this is the **tenant isolation** guard (a user cannot manage another org's keys; tested via `test_cross_tenant_denied`).

## Isolation guarantees (and tests)

- An API key resolves **only** to its own org (`TenantContext.organization_id = key.organization_id`).
- A user cannot create/list/revoke keys in an org they don't belong to (403).
- A revoked key → 401 on `/tenant`.
- `get(org_id, key_id)` scopes by org, so you can't revoke another org's key by id.

## RBAC / permissions (M2.4 done; deepening deferred)

- **Roles** — the `Role` enum (`Owner/Admin/Manager/Agent/ReadOnly`, `app/tenancy/base.py`) plus a `require_role(*roles)` dependency (layered on `require_org_membership`) are **implemented and enforced** (M2.4): API‑key create/revoke and routing/webhook config require `owner`/`admin`. `Membership.role` stores the enum *value* as a string.
- **Scope enforcement** — `require_scope(*scopes)` gates **API‑key** principals; `require_quota` (M2.5a) chains `require_scope("analyze")` on the analyze/batch/channel paths.
- **Row‑level tenant filtering** — `get_or_create_ticket`/queries take `organization_id`; the tickets/routing/analytics read stores all filter by org. **Done.**
- **Deferred (RBAC deepening):** member **invitation + role assignment** endpoints (today an org has only its owner, so non‑owner roles can only be created by injecting a `Membership`); a `readonly` gate on read endpoints as needed. See [14_remaining_roadmap.md](14_remaining_roadmap.md).

## What must NEVER change

- API keys stored **hashed** with plaintext returned once.
- Org‑scoped routes enforcing membership; `require_role`/`require_scope` guarding privileged actions.
- `get_tenant_context` resolving from **either** an API key or a JWT, and **not** requiring `JWT_SECRET` for the API‑key path.
- `organization_id` on tickets/analyses staying **nullable** (legacy root `/analyze` rows write `NULL`; tenant paths populate it) — legacy rows must remain valid.

## Tradeoffs / deferred

- **Explicit `POST /v1/orgs`** (vs. auto‑creating a personal org on signup): keeps auth and tenancy decoupled and left M2.2 signup behavior unchanged. Cost: a user must create an org before making keys. Acceptable.
- **Single‑membership assumption** for the JWT tenant path (else require `X-Organization-Id`): full org‑switching UX is later.
- `last_used_at` is best‑effort.
