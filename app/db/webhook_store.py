"""SQLAlchemy implementation of the outbound ``WebhookStore`` port."""

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Webhook


class SqlAlchemyWebhookStore:
    """Webhook registration persistence via short, self-committing sessions."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        url: str,
        secret: str,
        event_types: list[str],
    ) -> Webhook:
        async with self._sessionmaker() as session:
            webhook = Webhook(
                organization_id=organization_id,
                url=url,
                secret=secret,
                event_types=event_types,
            )
            session.add(webhook)
            await session.flush()
            await session.refresh(webhook)
            await session.commit()
            return webhook

    async def list_by_org(self, organization_id: uuid.UUID) -> Sequence[Webhook]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(Webhook)
                .where(Webhook.organization_id == organization_id)
                .order_by(Webhook.created_at)
            )
            return result.scalars().all()

    async def get(self, organization_id: uuid.UUID, webhook_id: uuid.UUID) -> Webhook | None:
        async with self._sessionmaker() as session:
            webhook = await session.get(Webhook, webhook_id)
            if webhook is None or webhook.organization_id != organization_id:
                return None
            return webhook

    async def delete(self, organization_id: uuid.UUID, webhook_id: uuid.UUID) -> bool:
        async with self._sessionmaker() as session:
            result = await session.execute(
                delete(Webhook).where(
                    Webhook.id == webhook_id,
                    Webhook.organization_id == organization_id,
                )
            )
            await session.commit()
            return result.rowcount > 0

    async def list_active_for_event(
        self, organization_id: uuid.UUID, event_type: str
    ) -> Sequence[Webhook]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(Webhook).where(
                    Webhook.organization_id == organization_id,
                    Webhook.active.is_(True),
                )
            )
            # Subscription membership is filtered in Python (webhook counts per org
            # are small) to stay independent of JSONB containment operators.
            return [w for w in result.scalars().all() if event_type in (w.event_types or [])]
