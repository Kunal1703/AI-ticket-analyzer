"""SQLAlchemy implementation of the ``FeedbackStore`` port."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Feedback


class SqlAlchemyFeedbackStore:
    """Tenant-scoped feedback persistence via SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        ticket_id: uuid.UUID,
        analysis_id: uuid.UUID,
        rating: str,
        corrected_category: str | None,
        corrected_priority: str | None,
        comment: str | None,
    ) -> Feedback:
        feedback = Feedback(
            organization_id=organization_id,
            ticket_id=ticket_id,
            analysis_id=analysis_id,
            rating=rating,
            corrected_category=corrected_category,
            corrected_priority=corrected_priority,
            comment=comment,
        )
        self._session.add(feedback)
        await self._session.flush()
        # Load the server-generated created_at so the response can render it before
        # the request-scoped session commits.
        await self._session.refresh(feedback)
        return feedback

    async def list_for_ticket(
        self, organization_id: uuid.UUID, ticket_id: uuid.UUID
    ) -> Sequence[Feedback]:
        stmt = (
            select(Feedback)
            .where(
                Feedback.organization_id == organization_id,
                Feedback.ticket_id == ticket_id,
            )
            .order_by(Feedback.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
