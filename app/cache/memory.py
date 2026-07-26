"""
In-memory cache implementation.

Process-local LRU cache with per-entry TTL. Suitable for single-instance
deployments and the default when no shared cache (Redis) is configured.
"""

import time
from collections import OrderedDict
from collections.abc import Callable

from app.models import TicketAnalysis

DEFAULT_MAX_SIZE = 128


class TTLCache:
    """In-memory LRU cache with per-entry time-to-live (async interface).

    Entries expire ``ttl_seconds`` after insertion. A non-positive
    ``ttl_seconds`` disables caching entirely (``get`` always misses, ``set`` is
    a no-op). A custom ``clock`` (monotonic seconds) can be injected for
    deterministic testing.

    Process-local — use a shared backend (e.g. Redis) for multi-instance
    deployments.
    """

    def __init__(
        self,
        max_size: int = DEFAULT_MAX_SIZE,
        ttl_seconds: int = 300,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._clock = clock
        # key -> (expiry_monotonic, value)
        self._store: OrderedDict[str, tuple[float, TicketAnalysis]] = OrderedDict()

    async def get(self, key: str) -> TicketAnalysis | None:
        """Return a cached analysis, or ``None`` on miss or expiry."""
        if self._ttl <= 0:
            return None
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= self._clock():
            del self._store[key]  # expired — evict lazily
            return None
        self._store.move_to_end(key)
        return value

    async def set(self, key: str, value: TicketAnalysis) -> None:
        """Store an analysis with TTL and LRU eviction."""
        if self._ttl <= 0:
            return
        self._store[key] = (self._clock() + self._ttl, value)
        self._store.move_to_end(key)
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    async def ping(self) -> bool:
        """The in-memory cache is always reachable."""
        return True

    async def aclose(self) -> None:
        """No resources to release for the in-memory cache."""
        return None

    def clear(self) -> None:
        """Remove all cached entries (synchronous; used by tests/admin)."""
        self._store.clear()
