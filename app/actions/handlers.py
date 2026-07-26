"""
Action handlers + registry (M5.3).

Each handler executes exactly one action type behind the ``ActionHandler`` port.
Internal handlers (`set_status`, `assign`, `add_note`) mutate the ticket via the
request session; outward-facing handlers (`send_reply`, `escalate`) are
**destructive** and dispatch a signed webhook (reusing M3.3b) for the tenant's
integration to carry out the real effect — the app never performs an irreversible
external operation itself. Handlers are only ever run *after* approval by the
action service; nothing here auto-executes.
"""

from app.actions.base import ActionContext, ActionHandler, ActionResult
from app.db.models import ResolutionAction
from app.models import ActionType, TicketStatus


class SetStatusHandler:
    """Set the ticket's status (internal, non-destructive)."""

    action_type = ActionType.SET_STATUS
    is_destructive = False

    async def execute(self, action: ResolutionAction, ctx: ActionContext) -> ActionResult:
        raw = action.params.get("status")
        try:
            status = TicketStatus(raw)
        except ValueError:
            return ActionResult(ok=False, detail={"error": f"invalid status: {raw!r}"})
        ctx.ticket.status = status.value
        return ActionResult(ok=True, detail={"status": status.value})


class AssignHandler:
    """Set the ticket's assignee (internal, non-destructive)."""

    action_type = ActionType.ASSIGN
    is_destructive = False

    async def execute(self, action: ResolutionAction, ctx: ActionContext) -> ActionResult:
        assignee = action.params.get("assignee")
        ctx.ticket.assignee = str(assignee) if assignee is not None else None
        return ActionResult(ok=True, detail={"assignee": ctx.ticket.assignee})


class AddNoteHandler:
    """Record an internal note (internal, non-destructive).

    There is no notes table; the note lives in the action's ``params`` and the
    audit trail, which is sufficient for the training/history signal.
    """

    action_type = ActionType.ADD_NOTE
    is_destructive = False

    async def execute(self, action: ResolutionAction, ctx: ActionContext) -> ActionResult:
        note = action.params.get("note", "")
        return ActionResult(ok=True, detail={"note": note})


class SendReplyHandler:
    """Send a customer reply (destructive/outward) — dispatched via webhook.

    Best-effort webhook delivery hands the actual send to the tenant's
    integration; approval is enforced upstream by the action service.
    """

    action_type = ActionType.SEND_REPLY
    is_destructive = True

    async def execute(self, action: ResolutionAction, ctx: ActionContext) -> ActionResult:
        payload = {
            "ticket_id": str(ctx.ticket.id),
            "action_id": str(action.id),
            "body": action.params.get("note", ""),
        }
        await ctx.dispatcher.dispatch(
            organization_id=ctx.organization_id, event_type="ticket.reply", payload=payload
        )
        return ActionResult(ok=True, detail={"dispatched": "ticket.reply"})


class EscalateHandler:
    """Escalate the ticket (destructive/outward): mark in-progress + notify."""

    action_type = ActionType.ESCALATE
    is_destructive = True

    async def execute(self, action: ResolutionAction, ctx: ActionContext) -> ActionResult:
        ctx.ticket.status = TicketStatus.IN_PROGRESS.value
        payload = {"ticket_id": str(ctx.ticket.id), "action_id": str(action.id)}
        await ctx.dispatcher.dispatch(
            organization_id=ctx.organization_id, event_type="ticket.escalated", payload=payload
        )
        return ActionResult(ok=True, detail={"dispatched": "ticket.escalated"})


def build_action_handlers() -> dict[ActionType, ActionHandler]:
    """Return the registry of action handlers, keyed by action type."""
    handlers: list[ActionHandler] = [
        SetStatusHandler(),
        AssignHandler(),
        AddNoteHandler(),
        SendReplyHandler(),
        EscalateHandler(),
    ]
    return {handler.action_type: handler for handler in handlers}
