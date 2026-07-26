"""
Tests for configuration wiring introduced in Milestone M0.3.

Covers the three previously-unused settings that are now functional:

* ``cache_ttl_seconds`` -> ``TTLCache`` expiry / disable behavior
* ``openai_max_retries`` -> retry attempt count
* ``debug`` -> effective logging level
"""

import pytest
from app.cache import TTLCache
from app.config import Settings
from app.core.logging import resolve_log_level
from app.models import TicketAnalysis, TicketCategory, TicketPriority
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_analysis() -> TicketAnalysis:
    """Return a minimal valid TicketAnalysis for cache tests."""
    return TicketAnalysis(
        summary="Customer cannot log in.",
        category=TicketCategory.ACCOUNT_ACCESS,
        priority=TicketPriority.HIGH,
        next_actions=["Reset password"],
    )


def _settings(**overrides: object) -> Settings:
    """Build Settings without reading the local .env file."""
    base: dict[str, object] = {"llm_api_key": "sk-test-dummy"}
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type, call-arg]


# ---------------------------------------------------------------------------
# resolve_log_level (debug wiring)
# ---------------------------------------------------------------------------


class TestResolveLogLevel:
    """Tests for the debug -> log level resolution."""

    def test_debug_forces_debug_level(self) -> None:
        """When debug is true, the level is DEBUG regardless of log_level."""
        assert resolve_log_level(debug=True, log_level="WARNING") == "DEBUG"

    def test_non_debug_uses_log_level_uppercased(self) -> None:
        """When debug is false, the configured level is used (upper-cased)."""
        assert resolve_log_level(debug=False, log_level="warning") == "WARNING"


# ---------------------------------------------------------------------------
# TTLCache (cache_ttl_seconds wiring)
# ---------------------------------------------------------------------------


class TestTTLCache:
    """Tests for the in-memory TTL cache (async interface)."""

    @pytest.mark.anyio
    async def test_set_then_get_returns_value(self) -> None:
        """A freshly stored entry is returned on get."""
        cache = TTLCache(max_size=10, ttl_seconds=300)
        analysis = _sample_analysis()
        await cache.set("k", analysis)
        assert await cache.get("k") is analysis

    @pytest.mark.anyio
    async def test_entry_expires_after_ttl(self) -> None:
        """An entry is evicted once its TTL has elapsed (injected clock)."""
        now = [1000.0]
        cache = TTLCache(max_size=10, ttl_seconds=5, clock=lambda: now[0])
        await cache.set("k", _sample_analysis())
        assert await cache.get("k") is not None  # still valid
        now[0] += 6  # advance past TTL
        assert await cache.get("k") is None

    @pytest.mark.anyio
    async def test_non_positive_ttl_disables_cache(self) -> None:
        """A TTL of 0 disables caching entirely."""
        cache = TTLCache(max_size=10, ttl_seconds=0)
        await cache.set("k", _sample_analysis())
        assert await cache.get("k") is None

    @pytest.mark.anyio
    async def test_lru_eviction_on_max_size(self) -> None:
        """Exceeding max_size evicts the least-recently-used entry."""
        cache = TTLCache(max_size=2, ttl_seconds=300)
        a, b, c = _sample_analysis(), _sample_analysis(), _sample_analysis()
        await cache.set("a", a)
        await cache.set("b", b)
        await cache.set("c", c)  # should evict "a"
        assert await cache.get("a") is None
        assert await cache.get("b") is b
        assert await cache.get("c") is c

    @pytest.mark.anyio
    async def test_clear_removes_all_entries(self) -> None:
        """clear() empties the cache."""
        cache = TTLCache(max_size=10, ttl_seconds=300)
        await cache.set("k", _sample_analysis())
        cache.clear()
        assert await cache.get("k") is None


# ---------------------------------------------------------------------------
# openai_max_retries configuration validation
# (Retry-count behavior is covered in test_openai_provider.py.)
# ---------------------------------------------------------------------------


class TestRetryConfig:
    """Validation of the llm_max_retries setting."""

    def test_zero_retries_rejected_at_config(self) -> None:
        """llm_max_retries must be >= 1 (0 would never call the provider)."""
        with pytest.raises(ValidationError):
            _settings(llm_max_retries=0)
