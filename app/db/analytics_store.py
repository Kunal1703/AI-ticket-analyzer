"""SQLAlchemy implementation of the read-only ``AnalyticsStore`` port."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, Select, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Analysis, Ticket


class SqlAlchemyAnalyticsStore:
    """Aggregate metrics over tickets/analyses via SQL (`GROUP BY`, counts)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _window(
        stmt: Select[Any],
        created_at: Any,
        start: datetime | None,
        end: datetime | None,
    ) -> Select[Any]:
        if start is not None:
            stmt = stmt.where(created_at >= start)
        if end is not None:
            stmt = stmt.where(created_at < end)
        return stmt

    async def _count(
        self,
        column: Any,
        created_at: Any,
        organization_id: uuid.UUID,
        start: datetime | None,
        end: datetime | None,
    ) -> int:
        stmt = select(func.count()).where(column == organization_id)
        stmt = self._window(stmt, created_at, start, end)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def count_tickets(
        self, organization_id: uuid.UUID, *, start: datetime | None, end: datetime | None
    ) -> int:
        return await self._count(
            Ticket.organization_id, Ticket.created_at, organization_id, start, end
        )

    async def count_analyses(
        self, organization_id: uuid.UUID, *, start: datetime | None, end: datetime | None
    ) -> int:
        return await self._count(
            Analysis.organization_id, Analysis.created_at, organization_id, start, end
        )

    async def _count_by(
        self,
        field: Any,
        organization_id: uuid.UUID,
        start: datetime | None,
        end: datetime | None,
    ) -> dict[str, int]:
        stmt = select(field, func.count()).where(Analysis.organization_id == organization_id)
        stmt = self._window(stmt, Analysis.created_at, start, end).group_by(field)
        result = await self._session.execute(stmt)
        return {row[0]: int(row[1]) for row in result.all()}

    async def count_by_category(
        self, organization_id: uuid.UUID, *, start: datetime | None, end: datetime | None
    ) -> dict[str, int]:
        return await self._count_by(Analysis.category, organization_id, start, end)

    async def count_by_priority(
        self, organization_id: uuid.UUID, *, start: datetime | None, end: datetime | None
    ) -> dict[str, int]:
        return await self._count_by(Analysis.priority, organization_id, start, end)

    async def _per_day(
        self,
        column: Any,
        created_at: Any,
        organization_id: uuid.UUID,
        start: datetime | None,
        end: datetime | None,
    ) -> list[tuple[date, int]]:
        day = cast(created_at, Date)
        stmt = select(day, func.count()).where(column == organization_id)
        stmt = self._window(stmt, created_at, start, end).group_by(day).order_by(day)
        result = await self._session.execute(stmt)
        return [(row[0], int(row[1])) for row in result.all()]

    async def tickets_per_day(
        self, organization_id: uuid.UUID, *, start: datetime | None, end: datetime | None
    ) -> list[tuple[date, int]]:
        return await self._per_day(
            Ticket.organization_id, Ticket.created_at, organization_id, start, end
        )

    async def analyses_per_day(
        self, organization_id: uuid.UUID, *, start: datetime | None, end: datetime | None
    ) -> list[tuple[date, int]]:
        return await self._per_day(
            Analysis.organization_id, Analysis.created_at, organization_id, start, end
        )
