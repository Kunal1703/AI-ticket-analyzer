"""SQLAlchemy implementations of the action + audit stores (request-scoped, M5.3)."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, ResolutionAction


class SqlAlchemyActionStore:
    """Resolution-action persistence via the request session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        ticket_id: uuid.UUID,
        analysis_id: uuid.UUID | None,
        action_type: str,
        params: dict[str, object],
        rationale: str,
        is_destructive: bool,
        suggested_by: str,
    ) -> ResolutionAction:
        action = ResolutionAction(
            organization_id=organization_id,
            ticket_id=ticket_id,
            analysis_id=analysis_id,
            action_type=action_type,
            params=params,
            rationale=rationale,
            is_destructive=is_destructive,
            suggested_by=suggested_by,
            status="proposed",
        )
        self._session.add(action)
        await self._session.flush()
        await self._session.refresh(action)  # load server defaults (created_at/updated_at)
        return action

    async def get_for_org(
        self, organization_id: uuid.UUID, action_id: uuid.UUID
    ) -> ResolutionAction | None:
        result = await self._session.execute(
            select(ResolutionAction).where(
                ResolutionAction.id == action_id,
                ResolutionAction.organization_id == organization_id,
            )
        )
        return result.scalars().first()

    async def list_for_ticket(
        self, organization_id: uuid.UUID, ticket_id: uuid.UUID
    ) -> Sequence[ResolutionAction]:
        result = await self._session.execute(
            select(ResolutionAction)
            .where(
                ResolutionAction.organization_id == organization_id,
                ResolutionAction.ticket_id == ticket_id,
            )
            .order_by(ResolutionAction.created_at)
        )
        return result.scalars().all()


class SqlAlchemyAuditStore:
    """Append-only audit-log persistence via the request session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        organization_id: uuid.UUID,
        actor_type: str,
        actor_id: str | None,
        action: str,
        resource_type: str,
        resource_id: uuid.UUID | None,
        detail: dict[str, object] | None,
    ) -> AuditLog:
        entry = AuditLog(
            organization_id=organization_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
        )
        self._session.add(entry)
        await self._session.flush()
        await self._session.refresh(entry)
        return entry

    async def list_for_org(
        self, organization_id: uuid.UUID, *, limit: int, offset: int
    ) -> Sequence[AuditLog]:
        result = await self._session.execute(
            select(AuditLog)
            .where(AuditLog.organization_id == organization_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()
