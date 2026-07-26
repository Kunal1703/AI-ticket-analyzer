"""
Action service (M5.3): suggest → approve/reject → execute, each audited.

Orchestrates the ports (suggester, stores, handlers) and enforces the safety
invariants in one place:

- Suggesting only ever creates ``proposed`` actions (nothing runs).
- The state machine (``app.actions.state``) gates transitions, so **execution is
  only possible after approval** — a proposed action cannot be executed.
- Every transition (proposed/approved/rejected/executed/failed) is written to the
  append-only audit log with the actor.

It mutates the loaded ORM rows (the request-scoped session commits), like the
ticket PATCH/route endpoints.
"""

import logging
import uuid
from collections.abc import Sequence

from app.actions.base import (
    ActionContext,
    ActionHandler,
    ActionStore,
    ActionSuggester,
    AuditStore,
)
from app.actions.state import ensure_transition
from app.db.models import Analysis, ResolutionAction, Ticket
from app.models import ActionStatus, ActionType, ActorType

logger = logging.getLogger(__name__)

_RESOURCE = "resolution_action"


class ActionService:
    """Coordinates proposing, approving, and executing resolution actions."""

    def __init__(
        self,
        action_store: ActionStore,
        audit_store: AuditStore,
        suggester: ActionSuggester,
        handlers: dict[ActionType, ActionHandler],
    ) -> None:
        self._actions = action_store
        self._audit = audit_store
        self._suggester = suggester
        self._handlers = handlers

    async def suggest(
        self,
        *,
        organization_id: uuid.UUID,
        ticket: Ticket,
        analysis: Analysis | None,
        context: str | None,
    ) -> list[ResolutionAction]:
        """Propose actions for a ticket and persist them as ``proposed`` (audited)."""
        proposals = await self._suggester.suggest(ticket=ticket, analysis=analysis, context=context)
        created: list[ResolutionAction] = []
        for proposal in proposals:
            action = await self._actions.create(
                organization_id=organization_id,
                ticket_id=ticket.id,
                analysis_id=proposal.analysis_id,
                action_type=proposal.action_type.value,
                params=proposal.params,
                rationale=proposal.rationale,
                is_destructive=proposal.is_destructive,
                suggested_by=self._suggester.name,
            )
            await self._record(
                action,
                "action.proposed",
                actor_type=self._suggester.actor_type,
                actor_id=self._suggester.name,
                detail={"action_type": action.action_type, "is_destructive": action.is_destructive},
            )
            created.append(action)
        return created

    async def approve(self, action: ResolutionAction, *, user_id: uuid.UUID) -> ResolutionAction:
        """Approve a proposed action (proposed → approved), audited."""
        self._transition(action, ActionStatus.APPROVED)
        action.approved_by = user_id
        await self._record(
            action, "action.approved", actor_type=ActorType.USER, actor_id=str(user_id), detail=None
        )
        return action

    async def reject(self, action: ResolutionAction, *, user_id: uuid.UUID) -> ResolutionAction:
        """Reject a proposed action (proposed → rejected), audited."""
        self._transition(action, ActionStatus.REJECTED)
        await self._record(
            action, "action.rejected", actor_type=ActorType.USER, actor_id=str(user_id), detail=None
        )
        return action

    async def execute(
        self, action: ResolutionAction, ctx: ActionContext, *, user_id: uuid.UUID
    ) -> ResolutionAction:
        """Execute an **approved** action via its handler (executed/failed), audited.

        Enforces the safety invariant: ``ensure_transition`` rejects executing an
        action that is not approved (a proposed action raises, mapped to 409).
        """
        # Guard: only an approved action may be executed.
        ensure_transition(ActionStatus(action.status), ActionStatus.EXECUTED)
        handler = self._handlers.get(ActionType(action.action_type))
        if handler is None:  # pragma: no cover - every action type has a handler
            return await self._fail(action, user_id, {"error": "no handler for action type"})
        try:
            result = await handler.execute(action, ctx)
        except Exception as exc:
            logger.exception("Action %s handler failed", action.id)
            return await self._fail(action, user_id, {"error": str(exc)})
        if not result.ok:
            return await self._fail(action, user_id, result.detail)
        action.status = ActionStatus.EXECUTED.value
        action.result = result.detail
        await self._record(
            action,
            "action.executed",
            actor_type=ActorType.USER,
            actor_id=str(user_id),
            detail=result.detail,
        )
        return action

    async def get(
        self, organization_id: uuid.UUID, action_id: uuid.UUID
    ) -> ResolutionAction | None:
        return await self._actions.get_for_org(organization_id, action_id)

    async def list_for_ticket(
        self, organization_id: uuid.UUID, ticket_id: uuid.UUID
    ) -> Sequence[ResolutionAction]:
        return await self._actions.list_for_ticket(organization_id, ticket_id)

    # -- internals ---------------------------------------------------------

    def _transition(self, action: ResolutionAction, target: ActionStatus) -> None:
        ensure_transition(ActionStatus(action.status), target)
        action.status = target.value

    async def _fail(
        self, action: ResolutionAction, user_id: uuid.UUID, detail: dict[str, object]
    ) -> ResolutionAction:
        action.status = ActionStatus.FAILED.value
        action.result = detail
        await self._record(
            action, "action.failed", actor_type=ActorType.USER, actor_id=str(user_id), detail=detail
        )
        return action

    async def _record(
        self,
        action: ResolutionAction,
        event: str,
        *,
        actor_type: ActorType,
        actor_id: str | None,
        detail: dict[str, object] | None,
    ) -> None:
        await self._audit.record(
            organization_id=action.organization_id,
            actor_type=actor_type.value,
            actor_id=actor_id,
            action=event,
            resource_type=_RESOURCE,
            resource_id=action.id,
            detail=detail,
        )
