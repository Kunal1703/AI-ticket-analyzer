"""
Cache abstraction for ticket analyses.

Defines the async ``Cache`` protocol that business logic depends on, plus the
deterministic cache-key helper. Concrete backends (in-memory, Redis) live in
sibling modules so a backend can be swapped without touching callers.
"""

import hashlib
from typing import Protocol

from app.models import TicketAnalysis


def cache_key(ticket_text: str) -> str:
    """Generate a deterministic cache key from ticket text."""
    return hashlib.sha256(ticket_text.strip().lower().encode()).hexdigest()


class Cache(Protocol):
    """Async cache interface for ticket analyses.

    Implementations should be best-effort: a backend failure must degrade to a
    cache miss (``get``) or a no-op (``set``) rather than raising, so the API
    keeps working if the cache is unavailable.
    """

    async def get(self, key: str) -> TicketAnalysis | None:
        """Return a cached analysis, or ``None`` on miss/expiry/error."""
        ...

    async def set(self, key: str, value: TicketAnalysis) -> None:
        """Store an analysis."""
        ...

    async def ping(self) -> bool:
        """Return True if the cache backend is reachable/healthy."""
        ...

    async def aclose(self) -> None:
        """Release any resources held by the cache (e.g. network clients)."""
        ...
