"""
Agentic resolution-action HTTP routes (M5.3).

The human-in-the-loop workflow for a ticket:

- ``POST /v1/tickets/{id}/actions/suggest`` — propose actions (any member).
- ``GET  /v1/tickets/{id}/actions`` — list a ticket's actions (any member).
- ``POST /v1/tickets/{id}/actions/{aid}/approve|reject`` — owner/admin human.
- ``POST /v1/tickets/{id}/actions/{aid}/execute`` — owner/admin; runs the handler
  (only possible once **approved** — a proposed action returns 409).
- ``GET  /v1/orgs/{org_id}/audit-logs`` — the tenant's append-only audit trail.

Everything is tenant-scoped (cross-org → 404); nothing executes automatically.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.actions.base import ActionContext, AuditStore
from app.actions.service import ActionService
from app.actions.state import InvalidActionTransition
from app.db.models import Analysis, AuditLog, Membership, ResolutionAction
from app.dependencies import (
    get_action_service,
    get_audit_store,
    get_tenant_context,
    get_ticket_store,
    get_webhook_dispatcher,
    require_approver,
    require_role,
)
from app.models import (
    AuditLogResponse,
    ResolutionActionResponse,
    SuggestActionsResponse,
)
from app.tenancy.base import TenantContext
from app.tickets.base import TicketStore
from app.webhooks.base import WebhookDispatcher

router = APIRouter(prefix="/v1", tags=["Actions"])

# Module-level dependency singleton (avoids a call inside Depends()).
_require_owner_or_admin = require_role("owner", "admin")


def _action_response(action: ResolutionAction) -> ResolutionActionResponse:
    return ResolutionActionResponse(
        id=str(action.id),
        ticket_id=str(action.ticket_id),
        analysis_id=str(action.analysis_id) if action.analysis_id is not None else None,
        action_type=action.action_type,
        params=dict(action.params or {}),
        rationale=action.rationale,
        status=action.status,
        is_destructive=action.is_destructive,
        suggested_by=action.suggested_by,
        approved_by=str(action.approved_by) if action.approved_by is not None else None,
        result=dict(action.result) if action.result is not None else None,
        created_at=action.created_at.isoformat(),
    )


def _latest(analyses: list[Analysis]) -> Analysis | None:
    return max(analyses, key=lambda a: a.created_at) if analyses else None


async def _load_action(
    service: ActionService, org_id: uuid.UUID, ticket_id: uuid.UUID, action_id: uuid.UUID
) -> ResolutionAction:
    action = await service.get(org_id, action_id)
    if action is None or action.ticket_id != ticket_id:
        raise HTTPException(status_code=404, detail="Action not found")
    return action


@router.post(
    "/tickets/{ticket_id}/actions/suggest",
    response_model=SuggestActionsResponse,
    status_code=201,
    summary="Propose resolution actions for a ticket",
    responses={404: {"description": "Ticket not found in this organization"}},
)
async def suggest_actions(
    ticket_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    ticket_store: TicketStore = Depends(get_ticket_store),
    service: ActionService = Depends(get_action_service),
) -> SuggestActionsResponse:
    """Propose (never execute) resolution actions from the ticket's latest analysis."""
    org_id = context.organization_id
    ticket = await ticket_store.get_for_org(org_id, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    created = await service.suggest(
        organization_id=org_id, ticket=ticket, analysis=_latest(ticket.analyses), context=None
    )
    return SuggestActionsResponse(
        ticket_id=str(ticket_id), actions=[_action_response(a) for a in created]
    )


@router.get(
    "/tickets/{ticket_id}/actions",
    response_model=list[ResolutionActionResponse],
    summary="List a ticket's resolution actions",
    responses={404: {"description": "Ticket not found in this organization"}},
)
async def list_actions(
    ticket_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    ticket_store: TicketStore = Depends(get_ticket_store),
    service: ActionService = Depends(get_action_service),
) -> list[ResolutionActionResponse]:
    org_id = context.organization_id
    if await ticket_store.get_for_org(org_id, ticket_id) is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    actions = await service.list_for_ticket(org_id, ticket_id)
    return [_action_response(a) for a in actions]


@router.post(
    "/tickets/{ticket_id}/actions/{action_id}/approve",
    response_model=ResolutionActionResponse,
    summary="Approve a proposed action",
    responses={
        403: {"description": "Owner/admin user required"},
        404: {"description": "Action not found"},
        409: {"description": "Action is not in a state that can be approved"},
    },
)
async def approve_action(
    ticket_id: uuid.UUID,
    action_id: uuid.UUID,
    context: TenantContext = Depends(require_approver),
    service: ActionService = Depends(get_action_service),
) -> ResolutionActionResponse:
    assert context.user_id is not None  # guaranteed by require_approver
    action = await _load_action(service, context.organization_id, ticket_id, action_id)
    try:
        await service.approve(action, user_id=context.user_id)
    except InvalidActionTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _action_response(action)


@router.post(
    "/tickets/{ticket_id}/actions/{action_id}/reject",
    response_model=ResolutionActionResponse,
    summary="Reject a proposed action",
    responses={
        403: {"description": "Owner/admin user required"},
        404: {"description": "Action not found"},
        409: {"description": "Action is not in a state that can be rejected"},
    },
)
async def reject_action(
    ticket_id: uuid.UUID,
    action_id: uuid.UUID,
    context: TenantContext = Depends(require_approver),
    service: ActionService = Depends(get_action_service),
) -> ResolutionActionResponse:
    assert context.user_id is not None  # guaranteed by require_approver
    action = await _load_action(service, context.organization_id, ticket_id, action_id)
    try:
        await service.reject(action, user_id=context.user_id)
    except InvalidActionTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _action_response(action)


@router.post(
    "/tickets/{ticket_id}/actions/{action_id}/execute",
    response_model=ResolutionActionResponse,
    summary="Execute an approved action",
    responses={
        403: {"description": "Owner/admin user required"},
        404: {"description": "Action or ticket not found"},
        409: {"description": "Action must be approved before execution"},
    },
)
async def execute_action(
    ticket_id: uuid.UUID,
    action_id: uuid.UUID,
    context: TenantContext = Depends(require_approver),
    ticket_store: TicketStore = Depends(get_ticket_store),
    service: ActionService = Depends(get_action_service),
    dispatcher: WebhookDispatcher = Depends(get_webhook_dispatcher),
) -> ResolutionActionResponse:
    """Run an **approved** action's handler (409 if it is not yet approved)."""
    assert context.user_id is not None  # guaranteed by require_approver
    org_id = context.organization_id
    action = await _load_action(service, org_id, ticket_id, action_id)
    ticket = await ticket_store.get_for_org(org_id, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ctx = ActionContext(ticket=ticket, organization_id=org_id, dispatcher=dispatcher)
    try:
        await service.execute(action, ctx, user_id=context.user_id)
    except InvalidActionTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _action_response(action)


@router.get(
    "/orgs/{org_id}/audit-logs",
    response_model=list[AuditLogResponse],
    summary="List the organization's audit log",
)
async def list_audit_logs(
    org_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _membership: Membership = Depends(_require_owner_or_admin),
    audit_store: AuditStore = Depends(get_audit_store),
) -> list[AuditLogResponse]:
    entries = await audit_store.list_for_org(org_id, limit=limit, offset=offset)
    return [_audit_response(e) for e in entries]


def _audit_response(entry: AuditLog) -> AuditLogResponse:
    return AuditLogResponse(
        id=str(entry.id),
        actor_type=entry.actor_type,
        actor_id=entry.actor_id,
        action=entry.action,
        resource_type=entry.resource_type,
        resource_id=str(entry.resource_id) if entry.resource_id is not None else None,
        detail=dict(entry.detail) if entry.detail is not None else None,
        created_at=entry.created_at.isoformat(),
    )
