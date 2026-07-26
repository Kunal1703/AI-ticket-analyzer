"""Routing/SLA ports and the neutral routing decision."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.db.models import RoutingRule, SlaPolicy


@dataclass(frozen=True)
class RoutingDecision:
    """The outcome of evaluating routing rules against an analysis."""

    assignee: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    matched_rule_id: uuid.UUID | None = None


class RoutingRuleStore(Protocol):
    """Persistence port for per-tenant routing rules (request-scoped)."""

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        name: str,
        position: int,
        conditions: dict[str, str],
        actions: dict[str, Any],
    ) -> RoutingRule: ...

    async def list_by_org(self, organization_id: uuid.UUID) -> Sequence[RoutingRule]: ...

    async def list_active(self, organization_id: uuid.UUID) -> Sequence[RoutingRule]: ...

    async def delete(self, organization_id: uuid.UUID, rule_id: uuid.UUID) -> bool: ...


class SlaPolicyStore(Protocol):
    """Persistence port for per-tenant SLA policies (request-scoped)."""

    async def create(
        self, *, organization_id: uuid.UUID, priority: str, resolution_minutes: int
    ) -> SlaPolicy: ...

    async def list_by_org(self, organization_id: uuid.UUID) -> Sequence[SlaPolicy]: ...

    async def list_active(self, organization_id: uuid.UUID) -> Sequence[SlaPolicy]: ...

    async def delete(self, organization_id: uuid.UUID, policy_id: uuid.UUID) -> bool: ...
