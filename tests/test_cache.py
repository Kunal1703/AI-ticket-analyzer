"""
Tests for the cache backends and factory (Milestone M1.3).

Covers backend selection, Redis serialization round-trip, and best-effort
degradation when Redis errors — all without a live Redis server.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.cache import RedisCache, TTLCache, build_cache
from app.cache.redis import RedisCache as RedisCacheImpl
from app.config import Settings
from app.models import TicketAnalysis, TicketCategory, TicketPriority


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"llm_api_key": "sk-test-dummy"}
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type, call-arg]


def _analysis() -> TicketAnalysis:
    return TicketAnalysis(
        summary="Customer cannot log in.",
        category=TicketCategory.ACCOUNT_ACCESS,
        priority=TicketPriority.HIGH,
        next_actions=["Reset password"],
    )


class TestBuildCache:
    def test_defaults_to_in_memory(self) -> None:
        cache = build_cache(_settings())
        assert isinstance(cache, TTLCache)

    def test_redis_url_selects_redis(self) -> None:
        cache = build_cache(_settings(redis_url="redis://localhost:6379/0"))
        assert isinstance(cache, RedisCache)


class TestRedisCache:
    @pytest.mark.anyio
    async def test_set_then_get_round_trip(self) -> None:
        store: dict[str, str] = {}
        client = MagicMock()

        async def _set(key: str, value: str, ex: int | None = None) -> None:
            store[key] = value

        async def _get(key: str) -> str | None:
            return store.get(key)

        client.set = AsyncMock(side_effect=_set)
        client.get = AsyncMock(side_effect=_get)

        cache = RedisCacheImpl(client, ttl_seconds=300)
        analysis = _analysis()
        await cache.set("k", analysis)
        loaded = await cache.get("k")
        assert loaded is not None
        assert loaded.category == TicketCategory.ACCOUNT_ACCESS
        # Stored under the namespaced key with a TTL.
        client.set.assert_awaited_once()
        assert client.set.await_args is not None
        assert client.set.await_args.kwargs["ex"] == 300

    @pytest.mark.anyio
    async def test_get_miss_returns_none(self) -> None:
        client = MagicMock()
        client.get = AsyncMock(return_value=None)
        cache = RedisCacheImpl(client, ttl_seconds=300)
        assert await cache.get("missing") is None

    @pytest.mark.anyio
    async def test_get_error_degrades_to_miss(self) -> None:
        client = MagicMock()
        client.get = AsyncMock(side_effect=RuntimeError("connection refused"))
        cache = RedisCacheImpl(client, ttl_seconds=300)
        assert await cache.get("k") is None  # best-effort: no raise

    @pytest.mark.anyio
    async def test_set_error_is_swallowed(self) -> None:
        client = MagicMock()
        client.set = AsyncMock(side_effect=RuntimeError("connection refused"))
        cache = RedisCacheImpl(client, ttl_seconds=300)
        await cache.set("k", _analysis())  # must not raise

    @pytest.mark.anyio
    async def test_corrupt_value_degrades_to_miss(self) -> None:
        client = MagicMock()
        client.get = AsyncMock(return_value="not-json")
        cache = RedisCacheImpl(client, ttl_seconds=300)
        assert await cache.get("k") is None

    @pytest.mark.anyio
    async def test_zero_ttl_disables_cache(self) -> None:
        client = MagicMock()
        client.get = AsyncMock()
        client.set = AsyncMock()
        cache = RedisCacheImpl(client, ttl_seconds=0)
        await cache.set("k", _analysis())
        assert await cache.get("k") is None
        client.set.assert_not_awaited()
        client.get.assert_not_awaited()

    @pytest.mark.anyio
    async def test_aclose_closes_client(self) -> None:
        client = MagicMock()
        client.aclose = AsyncMock()
        cache = RedisCacheImpl(client, ttl_seconds=300)
        await cache.aclose()
        client.aclose.assert_awaited_once()

    @pytest.mark.anyio
    async def test_aclose_error_is_swallowed(self) -> None:
        client = MagicMock()
        client.aclose = AsyncMock(side_effect=RuntimeError("already closed"))
        cache = RedisCacheImpl(client, ttl_seconds=300)
        await cache.aclose()  # must not raise

    @pytest.mark.anyio
    async def test_ping_ok(self) -> None:
        client = MagicMock()
        client.ping = AsyncMock(return_value=True)
        cache = RedisCacheImpl(client, ttl_seconds=300)
        assert await cache.ping() is True

    @pytest.mark.anyio
    async def test_ping_failure_returns_false(self) -> None:
        client = MagicMock()
        client.ping = AsyncMock(side_effect=RuntimeError("no route"))
        cache = RedisCacheImpl(client, ttl_seconds=300)
        assert await cache.ping() is False


class TestInMemoryPing:
    @pytest.mark.anyio
    async def test_ttl_cache_ping_is_true(self) -> None:
        assert await TTLCache(ttl_seconds=300).ping() is True
