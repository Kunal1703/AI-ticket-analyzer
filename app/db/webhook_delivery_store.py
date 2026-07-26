"""SQLAlchemy implementation of the ``WebhookDeliveryStore`` port."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import WebhookDelivery


class SqlAlchemyWebhookDeliveryStore:
    """Webhook delivery-record persistence via short, self-committing sessions."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(
        self,
        *,
        webhook_id: uuid.UUID,
        organization_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> WebhookDelivery:
        async with self._sessionmaker() as session:
            delivery = WebhookDelivery(
                webhook_id=webhook_id,
                organization_id=organization_id,
                event_type=event_type,
                payload=payload,
                status="pending",
                attempts=0,
            )
            session.add(delivery)
            await session.flush()
            await session.refresh(delivery)
            await session.commit()
            return delivery

    async def update(
        self,
        delivery_id: uuid.UUID,
        *,
        status: str,
        attempts: int,
        response_status: int | None,
        error: str | None,
    ) -> None:
        async with self._sessionmaker() as session:
            delivery = await session.get(WebhookDelivery, delivery_id)
            if delivery is None:
                return
            delivery.status = status
            delivery.attempts = attempts
            delivery.response_status = response_status
            delivery.error = error
            await session.commit()
