"""
Persistence service for ticket analyses.

Provides best-effort persistence that is intentionally decoupled from the
request/response path: if no database is configured, or if a write fails, the
API response is unaffected. All errors are logged and swallowed.
"""

import logging
import uuid
from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.base import TokenUsage
from app.db import repositories
from app.models import TicketAnalysis

logger = logging.getLogger(__name__)


async def persist_analysis(
    sessionmaker: async_sessionmaker[AsyncSession] | None,
    *,
    ticket_text: str,
    text_hash: str,
    analysis: TicketAnalysis,
    model: str | None = None,
    usage: TokenUsage | None = None,
    prompt_version: str | None = None,
    organization_id: uuid.UUID | None = None,
    source: str = "api",
) -> uuid.UUID | None:
    """Persist a ticket and its analysis (best-effort; never raises).

    Args:
        sessionmaker: Async session factory, or ``None`` when persistence is
            disabled (no ``DATABASE_URL``).
        ticket_text: The (stripped) ticket text.
        text_hash: Deterministic hash used to deduplicate tickets.
        analysis: The structured analysis to store.
        model: Identifier of the model/backend that produced the analysis.
        usage: Optional token-usage metadata to record alongside the analysis.
        prompt_version: Prompt version that produced the analysis (M5.1).

    Returns:
        The id of the persisted ticket, or ``None`` when persistence is disabled
        or the write failed (both swallowed — the API response is unaffected).
    """
    if sessionmaker is None:
        return None
    token_usage = asdict(usage) if usage is not None else None
    try:
        async with sessionmaker() as session:
            ticket = await repositories.get_or_create_ticket(
                session,
                raw_text=ticket_text,
                text_hash=text_hash,
                organization_id=organization_id,
                source=source,
            )
            ticket_id = ticket.id
            await repositories.add_analysis(
                session,
                ticket=ticket,
                analysis=analysis,
                model=model,
                prompt_version=prompt_version,
                token_usage=token_usage,
            )
            await session.commit()
            return ticket_id
    except Exception:
        # Persistence must never break the API response.
        logger.exception("Failed to persist ticket analysis (best-effort, ignoring)")
        return None


async def resolve_ticket_id(
    sessionmaker: async_sessionmaker[AsyncSession] | None,
    *,
    text_hash: str,
    organization_id: uuid.UUID,
) -> uuid.UUID | None:
    """Look up an existing ticket id by content hash (best-effort; never raises).

    Used on a cache hit — where nothing is persisted — so the tenant-scoped
    analyze endpoints can still return a ``ticket_id`` to deep-link to. Opens its
    own short session and swallows any error, mirroring ``persist_analysis``.
    """
    if sessionmaker is None:
        return None
    try:
        async with sessionmaker() as session:
            return await repositories.get_ticket_id_by_hash(
                session, text_hash=text_hash, organization_id=organization_id
            )
    except Exception:
        logger.exception("Failed to resolve ticket id (best-effort, ignoring)")
        return None
