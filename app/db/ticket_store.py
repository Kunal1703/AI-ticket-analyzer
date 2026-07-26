"""SQLAlchemy implementation of the ``TicketStore`` read port."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Ticket
from app.models import TicketCategory, TicketPriority, TicketSort, TicketStatus


def _escape_like(term: str) -> str:
    """Escape LIKE wildcards so a search term matches literally."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SqlAlchemyTicketStore:
    """Tenant-scoped ticket reads via SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _apply_filters(
        stmt: Select[Any],
        organization_id: uuid.UUID,
        *,
        category: TicketCategory | None,
        priority: TicketPriority | None,
        status: TicketStatus | None,
        assignee: str | None,
        source: str | None,
        search: str | None,
    ) -> Select[Any]:
        stmt = stmt.where(Ticket.organization_id == organization_id)
        # Category/priority live on the (versioned) analyses; filter tickets that
        # have any analysis matching (EXISTS via the relationship's ``any``).
        if category is not None:
            stmt = stmt.where(Ticket.analyses.any(category=category.value))
        if priority is not None:
            stmt = stmt.where(Ticket.analyses.any(priority=priority.value))
        if status is not None:
            stmt = stmt.where(Ticket.status == status.value)
        if assignee is not None:
            stmt = stmt.where(Ticket.assignee == assignee)
        if source is not None:
            stmt = stmt.where(Ticket.source == source)
        if search:
            stmt = stmt.where(Ticket.raw_text.ilike(f"%{_escape_like(search)}%", escape="\\"))
        return stmt

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        category: TicketCategory | None = None,
        priority: TicketPriority | None = None,
        status: TicketStatus | None = None,
        assignee: str | None = None,
        source: str | None = None,
        search: str | None = None,
        sort: TicketSort = TicketSort.CREATED_DESC,
    ) -> Sequence[Ticket]:
        stmt = self._apply_filters(
            select(Ticket),
            organization_id,
            category=category,
            priority=priority,
            status=status,
            assignee=assignee,
            source=source,
            search=search,
        )
        order = (
            Ticket.created_at.asc() if sort is TicketSort.CREATED_ASC else Ticket.created_at.desc()
        )
        stmt = (
            stmt.order_by(order).limit(limit).offset(offset).options(selectinload(Ticket.analyses))
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        category: TicketCategory | None = None,
        priority: TicketPriority | None = None,
        status: TicketStatus | None = None,
        assignee: str | None = None,
        source: str | None = None,
        search: str | None = None,
    ) -> int:
        stmt = self._apply_filters(
            select(func.count()).select_from(Ticket),
            organization_id,
            category=category,
            priority=priority,
            status=status,
            assignee=assignee,
            source=source,
            search=search,
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def get_for_org(self, organization_id: uuid.UUID, ticket_id: uuid.UUID) -> Ticket | None:
        stmt = (
            select(Ticket)
            .where(Ticket.organization_id == organization_id, Ticket.id == ticket_id)
            .options(selectinload(Ticket.analyses))
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()
