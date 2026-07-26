"""
Readiness checks for AI Ticket Analyzer.

Separates *readiness* (can the service do useful work?) from *liveness* (is the
process up?). Readiness verifies the service's own infrastructure — the database
and cache — but deliberately does **not** make a paid/rate-limited call to the
AI provider: third-party API blips should not flap the pod out of rotation. The
provider is reported as configured-or-not only.
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.base import AnalysisProvider
from app.cache.base import Cache

logger = logging.getLogger(__name__)

# Statuses that do not block readiness.
_OK_STATUSES = frozenset({"ok", "not_configured"})


async def _check_database(sessionmaker: async_sessionmaker[AsyncSession] | None) -> str:
    if sessionmaker is None:
        return "not_configured"
    try:
        async with sessionmaker() as session:
            await session.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        logger.warning("Readiness: database check failed", exc_info=True)
        return "error"


async def _check_cache(cache: Cache) -> str:
    try:
        return "ok" if await cache.ping() else "error"
    except Exception:
        logger.warning("Readiness: cache check failed", exc_info=True)
        return "error"


async def check_readiness(
    sessionmaker: async_sessionmaker[AsyncSession] | None,
    cache: Cache,
    provider: AnalysisProvider | None,
) -> tuple[bool, dict[str, str]]:
    """Run readiness checks and return ``(ready, per_component_statuses)``.

    The AI provider is reported as ``ok``/``error`` based only on whether it is
    configured — no upstream network call is made.
    """
    checks = {
        "database": await _check_database(sessionmaker),
        "cache": await _check_cache(cache),
        "provider": "ok" if provider is not None else "error",
    }
    ready = all(status in _OK_STATUSES for status in checks.values())
    return ready, checks
