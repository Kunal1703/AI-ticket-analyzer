"""
Cache package for AI Ticket Analyzer.

Public surface: the ``Cache`` protocol, the deterministic ``cache_key`` helper,
the concrete backends, and the ``build_cache`` factory.
"""

from app.cache.base import Cache, cache_key
from app.cache.factory import build_cache
from app.cache.memory import TTLCache
from app.cache.redis import RedisCache

__all__ = ["Cache", "RedisCache", "TTLCache", "build_cache", "cache_key"]
