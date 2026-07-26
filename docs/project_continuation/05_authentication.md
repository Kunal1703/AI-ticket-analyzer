# 05 — Authentication

Provider‑agnostic authentication, mirroring the AI provider system ([04_ai_provider_system.md](04_ai_provider_system.md)). Implemented in **M2.2**.

Files: `app/auth/base.py`, `password.py`, `tokens.py`, `local_provider.py`, `factory.py`, `service.py`, `routes.py`, `__init__.py`; `app/db/user_store.py`; auth deps in `app/dependencies.py`; schemas in `app/models.py`.

## Why provider‑agnostic (the design intent)

The user explicitly required that auth **not** be tightly coupled to local email/password, so Google/GitHub/Microsoft Entra/Auth0/any OIDC can be added later without touching business logic, routes, services, repositories, or authorization. The design separates **"verify a credential → identity"** (provider‑specific) from **"issue a session / resolve a user / authorize"** (provider‑agnostic, shared).

## Components

### `AuthProvider` (ABC) + `AuthenticatedIdentity` (`app/auth/base.py`)
```python
class AuthProvider(ABC):
    @property @abstractmethod
    def name(self) -> str: ...
    @property
    def auto_provision(self) -> bool: return False   # federated providers return True
    @abstractmethod
    async def authenticate(self, credentials: Mapping[str, Any]) -> AuthenticatedIdentity: ...

@dataclass(frozen=True)
class AuthenticatedIdentity:
    provider: str; subject: str; email: str
    email_verified: bool = False; display_name: str | None = None
```
A provider's only job is to verify an external credential and return a **normalized identity**. It never issues tokens or resolves users.

Errors: `AuthError` → `InvalidCredentialsError` (401), `UserAlreadyExistsError` (409), `AuthProviderError` (503).

### `UserStore` (Protocol, `app/auth/base.py`)
`get_by_email`, `get_by_id`, `create(email, password_hash, name)` → returns ORM `User`. SQLAlchemy impl: `app/db/user_store.py` (`SqlAlchemyUserStore`). Fake in tests: `FakeUserStore` (in `tests/test_auth.py`). This port is why the entire auth HTTP surface is testable without a DB.

### Password hashing (`app/auth/password.py`)
Argon2 via `argon2-cffi` — `hash_password`, `verify_password` (returns `bool`, never raises). **Why Argon2:** passwords are low‑entropy; a slow, memory‑hard KDF is the correct choice. (Contrast: API keys are high‑entropy → fast SHA‑256, see [06_tenancy.md](06_tenancy.md).)

### `TokenService` (`app/auth/tokens.py`) — provider‑agnostic sessions
Signed JWT access + refresh tokens via `PyJWT`. `create_access_token`, `create_refresh_token`, `issue_pair`, `decode(token, expected_type)`. Claims: `sub` (user id), `type` ("access"/"refresh"), `iat`, `exp`, `jti`. `decode` raises `TokenError` on bad signature/expiry/**wrong type**. TTLs from settings (`ACCESS_TOKEN_TTL_SECONDS`=900, `REFRESH_TOKEN_TTL_SECONDS`=1209600). Built in `create_app` when `JWT_SECRET` is set (else `app.state.token_service = None`).

**Why sessions are here, not in the provider:** every provider (local or federated) produces the *same* app session (our JWT). Session handling is identical across providers — so it's shared.

### `LocalAuthProvider` (`app/auth/local_provider.py`)
`authenticate({"email","password"})` → looks up the user, verifies the Argon2 hash, returns identity (or `InvalidCredentialsError`). Registered as `"local"` in the factory.

### Factory (`app/auth/factory.py`)
```python
@dataclass(frozen=True)
class AuthProviderContext: user_store: UserStore; settings: Settings
_PROVIDERS = {"local": lambda ctx: LocalAuthProvider(ctx.user_store)}
build_auth_provider(name, context) -> AuthProvider
```
The `AuthProviderContext` carries everything any provider might need (store + settings), so adding a federated provider needs no signature change.

### `AuthService` (`app/auth/service.py`) — the orchestrator
- `signup(email, password, name)` → create local user (Argon2) → issue pair. 409 if exists.
- `login(credentials, provider="local")` → `build_auth_provider(provider)` → `authenticate` → `_resolve_user` → issue pair.
- `refresh(refresh_token)` → decode refresh → reload user → issue new pair.
- `get_current_user(access_token)` → decode access → load user.
- `_resolve_user(identity, auto_provision)` → find by email; if missing and `auto_provision` (federated) → create (no password). **This is how OAuth users will auto‑provision on first login** — proven by a test that registers a fake federated provider.

Routes (`app/auth/routes.py`, prefix `/v1/auth`): `POST /signup` (201), `POST /login`, `POST /refresh`, `GET /me` (Bearer). All depend only on `AuthService` + `get_current_user`.

## DI (in `app/dependencies.py`)
`get_token_service` (503 if unconfigured), `get_user_store` (from `get_db_session`), `get_auth_service`, `get_current_user` (HTTPBearer; catches `AuthError` **and** `TokenError` → 401 — a bug was fixed here: `TokenError` is not an `AuthError`, so it must be caught explicitly). Auth requires `JWT_SECRET` **and** `DATABASE_URL`; otherwise dependencies return 503.

## Current routes recap

| Method | Path | Notes |
|---|---|---|
| POST | `/v1/auth/signup` | email+password (min 8) → tokens |
| POST | `/v1/auth/login` | → tokens |
| POST | `/v1/auth/refresh` | refresh token → new pair |
| GET | `/v1/auth/me` | current user |

## Future OAuth / SSO (extension points)

To add Google/GitHub/Entra/Auth0/OIDC:
1. Implement `AuthProvider.authenticate` doing the code→token→userinfo exchange, returning an `AuthenticatedIdentity` (set `auto_provision=True`).
2. Register it in `_PROVIDERS`.
3. Add the provider's **redirect + callback routes** (a small OAuth router) that call `AuthService.login(provider="google", credentials={...})`. The token issuance + user resolution + `get_current_user` are reused unchanged.
4. SAML/enterprise SSO follows the same pattern (a provider that validates the assertion → identity).

No changes to `AuthService`, `TokenService`, `UserStore`, `get_current_user`, or existing routes are needed — that's the whole point of the abstraction.

## What must NEVER change

- The separation: providers return **identities**, not sessions; `AuthService`/`TokenService` own sessions. Do not make a provider issue JWTs.
- `get_current_user` catching both `AuthError` and `TokenError`.
- `User.password_hash` staying **nullable** (federated users have no password).

## Known limitations / debt (see [15_handoff.md](15_handoff.md))

- **Refresh tokens are stateless** — no server‑side rotation/denylist, so a refresh token is valid until expiry. A `refresh_tokens` table (jti + revoked_at) is the fix; pairs well with future work.
- **No authorization yet** — `get_current_user` authenticates; RBAC (role enforcement) is **M2.4**.
- **No rate limiting** on auth endpoints (cost/abuse) — later.
- `SqlAlchemyUserStore` is only exercised via mocked‑session unit tests here (no live DB); a real signup/login round‑trip is a `skipif` integration test to add when CI gets Postgres.
