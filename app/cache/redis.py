"""
Redis cache implementation.

A shared, multi-instance cache with native TTL. Best-effort by design: any Redis
error (connection, decode) degrades to a cache miss or a skipped write so the
API keeps working if Redis is unavailable.
"""

import logging
from typing import TYPE_CHECKING

from app.models import TicketAnalysis

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

DEFAULT_KEY_PREFIX = "analysis:"


class RedisCache:
    """Ticket-analysis cache backed by Redis (async interface)."""

    def __init__(
        self,
        client: "Redis",
        ttl_seconds: int = 300,
        key_prefix: str = DEFAULT_KEY_PREFIX,
    ) -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._prefix = key_prefix

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def get(self, key: str) -> TicketAnalysis | None:
        """Return a cached analysis, or ``None`` on miss/expiry/error."""
        if self._ttl <= 0:
            return None
        try:
            raw = await self._client.get(self._full_key(key))
        except Exception:
            logger.warning("Redis get failed; treating as cache miss", exc_info=True)
            return None
        if raw is None:
            return None
        try:
            return TicketAnalysis.model_validate_json(raw)
        except Exception:
            logger.warning("Failed to decode cached analysis; ignoring", exc_info=True)
            return None

    async def set(self, key: str, value: TicketAnalysis) -> None:
        """Store an analysis with native Redis TTL (best-effort)."""
        if self._ttl <= 0:
            return
        try:
            await self._client.set(self._full_key(key), value.model_dump_json(), ex=self._ttl)
        except Exception:
            logger.warning("Redis set failed; skipping cache write", exc_info=True)

    async def ping(self) -> bool:
        """Return True if Redis responds to PING."""
        try:
            return bool(await self._client.ping())
        except Exception:
            logger.warning("Redis ping failed", exc_info=True)
            return False

    async def aclose(self) -> None:
        """Close the Redis client connection pool."""
        try:
            await self._client.aclose()
        except Exception:
            logger.warning("Redis close failed", exc_info=True)
