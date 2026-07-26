"""SQLAlchemy implementation of the billing ``WebhookEventStore`` port."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProcessedWebhookEvent


class SqlAlchemyWebhookEventStore:
    """Record and look up processed webhook events via SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists(self, *, provider: str, event_id: str) -> bool:
        result = await self._session.execute(
            select(ProcessedWebhookEvent.id).where(
                ProcessedWebhookEvent.provider == provider,
                ProcessedWebhookEvent.event_id == event_id,
            )
        )
        return result.first() is not None

    async def record(
        self, *, provider: str, event_id: str, event_type: str
    ) -> ProcessedWebhookEvent:
        event = ProcessedWebhookEvent(provider=provider, event_id=event_id, event_type=event_type)
        self._session.add(event)
        await self._session.flush()
        return event
