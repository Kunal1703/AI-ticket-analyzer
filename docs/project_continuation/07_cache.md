# 07 — Cache

Implemented in M0.3 (in‑memory TTL), reshaped into a package with a Redis backend in **M1.3**, and given `ping()` in M1.5. Files: `app/cache/base.py`, `memory.py`, `redis.py`, `factory.py`, `__init__.py`.

## Why a cache at all

Identical tickets (same normalized text) shouldn't cost a second LLM call. The cache key is `sha256(ticket.strip().lower())` (`cache_key` in `app/cache/base.py`). A cache hit returns the stored `TicketAnalysis` and skips the provider entirely.

## The protocol (`app/cache/base.py`) — async

```python
class Cache(Protocol):
    async def get(self, key: str) -> TicketAnalysis | None: ...
    async def set(self, key: str, value: TicketAnalysis) -> None: ...
    async def ping(self) -> bool: ...
    async def aclose(self) -> None: ...
```

**Why async:** Redis I/O is async. Making the protocol async (M1.3) meant the endpoint `await`s `cache.get/set`, and both backends are async. This was a deliberate, behavior‑preserving change (the in‑memory ops don't await internally but the methods are `async`).

**Why a Protocol (structural), not an ABC:** backends don't need to inherit; fakes/mocks satisfy it structurally. Business logic depends only on `Cache`.

## In‑memory `TTLCache` (`app/cache/memory.py`)

- `OrderedDict` LRU (max_size default 128) with **per‑entry TTL** using a **monotonic** clock (immune to wall‑clock changes). Lazy expiry on `get`.
- `ttl_seconds <= 0` **disables** caching (get miss, set no‑op) — used to bypass the cache.
- Injectable `clock` for deterministic tests (advance time without sleeping).
- `ping()` → `True` (always healthy, it's local). `aclose()` → no‑op. `clear()` (sync) exists for tests — deliberately **off the protocol** so the sync test fixture (`conftest.clear_cache`) can call it without an async fixture. It's guarded (`getattr(..., "clear", None)`) so a Redis‑backed test env doesn't break.

## `RedisCache` (`app/cache/redis.py`) — shared, best‑effort

- Wraps a `redis.asyncio.Redis` client. Stores `value.model_dump_json()` under `analysis:<key>` with **native Redis TTL** (`set(..., ex=ttl)`).
- **Best‑effort by design:** any Redis error → `get` returns `None` (miss), `set` logs and skips, `ping` returns `False`, `aclose` swallows. A dead Redis never breaks `/analyze`.
- Decode failure (corrupt value) → treated as a miss.
- `ttl <= 0` disables (no calls to Redis).

## Factory + selection (`app/cache/factory.py`)

```python
def build_cache(settings) -> Cache:
    if settings.redis_url:
        client = Redis.from_url(settings.redis_url)   # lazy — no connection yet
        return RedisCache(client, ttl_seconds=settings.cache_ttl_seconds)
    return TTLCache(ttl_seconds=settings.cache_ttl_seconds)
```

`Redis.from_url` is lazy, so a configured‑but‑down Redis does **not** block startup — the first `get/set` degrades to best‑effort. `redis` is imported lazily inside `build_cache` so the in‑memory path works even if the package is stripped.

## Lifecycle

`create_app` calls `build_cache(settings)` → `app.state.cache`. `lifespan` calls `await cache.aclose()`. The `/analyze` route awaits `get`/`set`; `/ready` calls `ping()`.

## Fallback semantics (summary)

| Situation | Behavior |
|---|---|
| No `REDIS_URL` | In‑memory `TTLCache` |
| `REDIS_URL` set, Redis up | `RedisCache`, shared across instances |
| `REDIS_URL` set, Redis down | `RedisCache` best‑effort → effectively no caching, API keeps working |
| `CACHE_TTL_SECONDS=0` | Caching disabled |

## Config

`CACHE_TTL_SECONDS` (default 300; `0` disables), `REDIS_URL` (optional). Both in `app/config.py`.

## Future cache backends / extensions

- Add a backend by implementing the `Cache` protocol and a `build_cache` branch (e.g., Memcached, a two‑tier local+Redis).
- **Tenant‑scoped cache keys** (M2.4+): prefix keys with `organization_id` so tenants can't share cached analyses. Currently keys are global — fine while `/analyze` is unauthenticated, but M2.4's `/v1/analyze` should namespace by org.
- Cache hit/miss are already emitted as metrics (`cache_requests_total{result}`) — see [09_observability.md](09_observability.md).

## What must NEVER change

- The `Cache` protocol shape (`get/set/ping/aclose`) — many call sites and both backends depend on it.
- Best‑effort semantics — a cache failure must never surface to the client.
- The `sha256(strip().lower())` key derivation (would invalidate all existing cached entries and change dedupe behavior) unless intentionally versioning the cache.
