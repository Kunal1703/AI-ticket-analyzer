"""SQLAlchemy implementations of the routing/SLA stores (request-scoped)."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RoutingRule, SlaPolicy


class SqlAlchemyRoutingRuleStore:
    """Routing-rule persistence via the request session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        name: str,
        position: int,
        conditions: dict[str, str],
        actions: dict[str, Any],
    ) -> RoutingRule:
        rule = RoutingRule(
            organization_id=organization_id,
            name=name,
            position=position,
            conditions=conditions,
            actions=actions,
        )
        self._session.add(rule)
        await self._session.flush()
        return rule

    async def list_by_org(self, organization_id: uuid.UUID) -> Sequence[RoutingRule]:
        result = await self._session.execute(
            select(RoutingRule)
            .where(RoutingRule.organization_id == organization_id)
            .order_by(RoutingRule.position, RoutingRule.created_at)
        )
        return result.scalars().all()

    async def list_active(self, organization_id: uuid.UUID) -> Sequence[RoutingRule]:
        result = await self._session.execute(
            select(RoutingRule)
            .where(
                RoutingRule.organization_id == organization_id,
                RoutingRule.active.is_(True),
            )
            .order_by(RoutingRule.position, RoutingRule.created_at)
        )
        return result.scalars().all()

    async def delete(self, organization_id: uuid.UUID, rule_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            delete(RoutingRule).where(
                RoutingRule.id == rule_id,
                RoutingRule.organization_id == organization_id,
            )
        )
        return result.rowcount > 0


class SqlAlchemySlaPolicyStore:
    """SLA-policy persistence via the request session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, *, organization_id: uuid.UUID, priority: str, resolution_minutes: int
    ) -> SlaPolicy:
        policy = SlaPolicy(
            organization_id=organization_id,
            priority=priority,
            resolution_minutes=resolution_minutes,
        )
        self._session.add(policy)
        await self._session.flush()
        return policy

    async def list_by_org(self, organization_id: uuid.UUID) -> Sequence[SlaPolicy]:
        result = await self._session.execute(
            select(SlaPolicy)
            .where(SlaPolicy.organization_id == organization_id)
            .order_by(SlaPolicy.created_at)
        )
        return result.scalars().all()

    async def list_active(self, organization_id: uuid.UUID) -> Sequence[SlaPolicy]:
        result = await self._session.execute(
            select(SlaPolicy).where(
                SlaPolicy.organization_id == organization_id,
                SlaPolicy.active.is_(True),
            )
        )
        return result.scalars().all()

    async def delete(self, organization_id: uuid.UUID, policy_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            delete(SlaPolicy).where(
                SlaPolicy.id == policy_id,
                SlaPolicy.organization_id == organization_id,
            )
        )
        return result.rowcount > 0
