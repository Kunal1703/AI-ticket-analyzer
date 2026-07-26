"""
Ports and neutral value objects for agentic resolution actions (M5.3).

Everything the action subsystem depends on is a `Protocol` here, so routes and
the service are testable against in-memory fakes with no DB/LLM: the suggester
(proposes actions), the handlers (execute one action type), and the stores
(actions + append-only audit). Which action types are **destructive** (always
require approval, never auto-execute) is defined once, here, so the suggester and
the handlers can't disagree.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from app.db.models import Analysis, AuditLog, ResolutionAction, Ticket
from app.models import ActionType, ActorType
from app.webhooks.base import WebhookDispatcher

# Single source of truth: destructive/outward-facing actions. They always require
# human approval and are never auto-executed (see D34).
DESTRUCTIVE_ACTIONS: frozenset[ActionType] = frozenset({ActionType.SEND_REPLY, ActionType.ESCALATE})


def is_destructive(action_type: ActionType) -> bool:
    """Whether an action type is destructive/outward-facing (approval-gated)."""
    return action_type in DESTRUCTIVE_ACTIONS


@dataclass(frozen=True)
class ProposedAction:
    """A suggester's proposal (before it is persisted as a ``ResolutionAction``)."""

    action_type: ActionType
    params: dict[str, object]
    rationale: str
    is_destructive: bool
    analysis_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ActionResult:
    """The outcome of executing one action."""

    ok: bool
    detail: dict[str, object] = field(default_factory=dict)


@dataclass
class ActionContext:
    """Everything a handler needs to execute an action (no HTTP/DB coupling)."""

    ticket: Ticket
    organization_id: uuid.UUID
    dispatcher: WebhookDispatcher


class ActionSuggester(Protocol):
    """Proposes resolution actions for a ticket (rule-based or AI-backed)."""

    @property
    def name(self) -> str: ...

    @property
    def actor_type(self) -> ActorType: ...

    async def suggest(
        self,
        *,
        ticket: Ticket,
        analysis: Analysis | None,
        context: str | None,
    ) -> list[ProposedAction]: ...


class ActionHandler(Protocol):
    """Executes a single action type (an adapter over an internal/outward effect)."""

    @property
    def action_type(self) -> ActionType: ...

    @property
    def is_destructive(self) -> bool: ...

    async def execute(self, action: ResolutionAction, ctx: ActionContext) -> ActionResult: ...


class ActionStore(Protocol):
    """Persistence port for resolution actions (tenant-scoped, request-scoped)."""

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
    ) -> ResolutionAction: ...

    async def get_for_org(
        self, organization_id: uuid.UUID, action_id: uuid.UUID
    ) -> ResolutionAction | None: ...

    async def list_for_ticket(
        self, organization_id: uuid.UUID, ticket_id: uuid.UUID
    ) -> Sequence[ResolutionAction]: ...


class AuditStore(Protocol):
    """Append-only audit-log port (tenant-scoped, request-scoped)."""

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
    ) -> AuditLog: ...

    async def list_for_org(
        self, organization_id: uuid.UUID, *, limit: int, offset: int
    ) -> Sequence[AuditLog]: ...
