"""SQLAlchemy implementation of the billing ``UsageStore`` port."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UsageEvent


class SqlAlchemyUsageStore:
    """Record and aggregate usage events via SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        organization_id: uuid.UUID,
        event_type: str,
        quantity: int,
        model: str | None,
        total_tokens: int | None,
    ) -> UsageEvent:
        event = UsageEvent(
            organization_id=organization_id,
            event_type=event_type,
            quantity=quantity,
            model=model,
            total_tokens=total_tokens,
        )
        self._session.add(event)
        await self._session.flush()  # assign id
        return event

    async def count_since(
        self,
        organization_id: uuid.UUID,
        *,
        since: datetime,
        event_type: str,
    ) -> int:
        """Return the summed quantity of matching events since ``since`` (inclusive)."""
        stmt = select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
            UsageEvent.organization_id == organization_id,
            UsageEvent.event_type == event_type,
            UsageEvent.created_at >= since,
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())
