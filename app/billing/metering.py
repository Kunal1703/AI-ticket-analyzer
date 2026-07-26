"""
Best-effort usage metering on the analyze path.

This deliberately mirrors ``app.services.analysis_service.persist_analysis``: it
opens its **own** short-lived session from the sessionmaker, records one usage
event, commits, and **swallows any exception**. Metering must never break the
analyze response — a metering failure only means an unbilled analysis, which is
logged.

It is separate from the request-scoped session used by quota *enforcement*
(``get_db_session`` in a dependency): enforcement is a read whose failure should
fail the request, whereas metering is a fire-and-forget write on the response's
way out. These are the two session strategies described in the persistence docs.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing.service import ANALYSIS_EVENT
from app.db.usage_store import SqlAlchemyUsageStore
from app.observability import metrics

logger = logging.getLogger(__name__)


async def record_analysis_usage(
    sessionmaker: async_sessionmaker[AsyncSession] | None,
    *,
    organization_id: uuid.UUID | None,
    model: str | None = None,
    total_tokens: int | None = None,
) -> None:
    """Record one metered analysis usage event (best-effort; never raises).

    No-ops when persistence is disabled (``sessionmaker is None``) or the call is
    not tenant-scoped (``organization_id is None`` — the legacy path).
    """
    if sessionmaker is None or organization_id is None:
        return
    try:
        async with sessionmaker() as session:
            await SqlAlchemyUsageStore(session).record(
                organization_id=organization_id,
                event_type=ANALYSIS_EVENT,
                quantity=1,
                model=model,
                total_tokens=total_tokens,
            )
            await session.commit()
        metrics.record_usage_event(ANALYSIS_EVENT)
    except Exception:
        # Metering must never break the API response.
        logger.exception("Failed to record usage event (best-effort, ignoring)")
