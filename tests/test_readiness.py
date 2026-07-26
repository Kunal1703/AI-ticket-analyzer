"""
Tests for the readiness probe and checks (Milestone M1.5).

Readiness is distinct from liveness (/health): it verifies the service's own
dependencies (database, cache) and returns 503 when any is unavailable.
"""

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.readiness import check_readiness
from httpx import AsyncClient

SetSessionmaker = Callable[[object], None]
SetCache = Callable[[object], None]


class _FakeSession:
    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def execute(self, *args: object, **kwargs: object) -> MagicMock:
        return MagicMock()


def _ok_sessionmaker() -> MagicMock:
    return MagicMock(return_value=_FakeSession())


def _cache(ping_result: bool = True) -> MagicMock:
    cache = MagicMock()
    cache.ping = AsyncMock(return_value=ping_result)
    return cache


# ---------------------------------------------------------------------------
# /ready endpoint
# ---------------------------------------------------------------------------


class TestReadyEndpoint:
    @pytest.mark.anyio
    async def test_ready_by_default(self, client: AsyncClient) -> None:
        """No DB configured + in-memory cache => ready (200)."""
        resp = await client.get("/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ready"
        assert body["checks"]["database"] == "not_configured"
        assert body["checks"]["cache"] == "ok"
        assert body["checks"]["provider"] == "ok"

    @pytest.mark.anyio
    async def test_not_ready_when_database_down(
        self, client: AsyncClient, override_db_sessionmaker: SetSessionmaker
    ) -> None:
        override_db_sessionmaker(MagicMock(side_effect=RuntimeError("db down")))
        resp = await client.get("/ready")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["database"] == "error"

    @pytest.mark.anyio
    async def test_not_ready_when_cache_down(
        self, client: AsyncClient, override_cache: SetCache
    ) -> None:
        override_cache(_cache(ping_result=False))
        resp = await client.get("/ready")
        assert resp.status_code == 503
        assert resp.json()["checks"]["cache"] == "error"


# ---------------------------------------------------------------------------
# check_readiness unit tests
# ---------------------------------------------------------------------------


class TestCheckReadiness:
    @pytest.mark.anyio
    async def test_all_ok(self) -> None:
        ready, checks = await check_readiness(_ok_sessionmaker(), _cache(True), MagicMock())
        assert ready is True
        assert checks == {"database": "ok", "cache": "ok", "provider": "ok"}

    @pytest.mark.anyio
    async def test_no_db_is_ready(self) -> None:
        ready, checks = await check_readiness(None, _cache(True), MagicMock())
        assert ready is True
        assert checks["database"] == "not_configured"

    @pytest.mark.anyio
    async def test_cache_ping_exception_is_error(self) -> None:
        cache = MagicMock()
        cache.ping = AsyncMock(side_effect=RuntimeError("boom"))
        ready, checks = await check_readiness(None, cache, MagicMock())
        assert ready is False
        assert checks["cache"] == "error"

    @pytest.mark.anyio
    async def test_missing_provider_is_not_ready(self) -> None:
        ready, checks = await check_readiness(None, _cache(True), None)
        assert ready is False
        assert checks["provider"] == "error"
