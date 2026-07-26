"""
Cache factory.

Selects the cache backend from settings: Redis when ``REDIS_URL`` is set,
otherwise the in-memory ``TTLCache``. Business logic depends only on the
``Cache`` protocol, so the choice here is invisible to callers.
"""

import logging

from app.cache.base import Cache
from app.cache.memory import TTLCache
from app.config import Settings

logger = logging.getLogger(__name__)


def build_cache(settings: Settings) -> Cache:
    """Build the configured cache backend.

    Returns a ``RedisCache`` when ``settings.redis_url`` is set (shared,
    multi-instance), otherwise an in-memory ``TTLCache``.
    """
    if settings.redis_url:
        # Imported lazily so the in-memory path works even without redis.
        from redis.asyncio import Redis

        from app.cache.redis import RedisCache

        client = Redis.from_url(settings.redis_url)
        logger.info("Using Redis cache")
        return RedisCache(client, ttl_seconds=settings.cache_ttl_seconds)

    logger.info("Using in-memory cache")
    return TTLCache(ttl_seconds=settings.cache_ttl_seconds)
