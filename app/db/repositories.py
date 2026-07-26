"""
Data-access helpers (repository functions) for tickets and analyses.

These encapsulate the SQLAlchemy queries used to persist analyses, keeping the
service layer free of ORM query details. They operate on a provided
``AsyncSession`` and do not manage transactions themselves.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Analysis, Ticket
from app.models import TicketAnalysis

logger = logging.getLogger(__name__)


async def get_or_create_ticket(
    session: AsyncSession,
    *,
    raw_text: str,
    text_hash: str,
    organization_id: uuid.UUID | None = None,
    source: str = "api",
) -> Ticket:
    """Return the existing ticket for ``text_hash`` (scoped to the org) or create one.

    Dedupe is scoped by ``organization_id`` so different tenants never share a
    ticket, and legacy (org-less) rows stay isolated from tenant rows.
    """
    stmt = select(Ticket).where(Ticket.text_hash == text_hash)
    if organization_id is None:
        stmt = stmt.where(Ticket.organization_id.is_(None))
    else:
        stmt = stmt.where(Ticket.organization_id == organization_id)
    ticket = (await session.execute(stmt)).scalars().first()
    if ticket is not None:
        return ticket

    ticket = Ticket(
        raw_text=raw_text,
        text_hash=text_hash,
        organization_id=organization_id,
        source=source,
    )
    session.add(ticket)
    await session.flush()  # populate ticket.id for the FK below
    return ticket


async def get_ticket_id_by_hash(
    session: AsyncSession,
    *,
    text_hash: str,
    organization_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Return the id of the ticket for ``text_hash`` (scoped to the org), or None.

    Used to resolve the ticket id on a cache hit (M3.6), when no analysis is
    persisted but the caller still wants to deep-link to the ticket.
    """
    stmt = select(Ticket.id).where(Ticket.text_hash == text_hash)
    if organization_id is None:
        stmt = stmt.where(Ticket.organization_id.is_(None))
    else:
        stmt = stmt.where(Ticket.organization_id == organization_id)
    return (await session.execute(stmt)).scalars().first()


async def add_analysis(
    session: AsyncSession,
    *,
    ticket: Ticket,
    analysis: TicketAnalysis,
    model: str | None = None,
    prompt_version: str | None = None,
    token_usage: dict[str, int] | None = None,
) -> Analysis:
    """Append a new (versioned) analysis row for a ticket."""
    row = Analysis(
        ticket_id=ticket.id,
        organization_id=ticket.organization_id,
        summary=analysis.summary,
        category=analysis.category.value,
        priority=analysis.priority.value,
        next_actions=list(analysis.next_actions),
        model=model,
        prompt_version=prompt_version,
        token_usage=token_usage,
    )
    session.add(row)
    return row
