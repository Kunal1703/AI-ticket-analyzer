"""
Routing & SLA HTTP routes.

Per-tenant config CRUD (``/v1/orgs/{org_id}/routing-rules`` and
``…/sla-policies``, owner/admin to modify, membership to list) plus an explicit
``POST /v1/tickets/{id}/route`` that evaluates the org's rules + SLA against the
ticket's latest analysis and **persists** ``assignee`` + ``sla_due_at`` on the
ticket.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response

from app.db.models import Analysis, Membership, RoutingRule, SlaPolicy
from app.dependencies import (
    get_routing_rule_store,
    get_sla_policy_store,
    get_tenant_context,
    get_ticket_store,
    require_org_membership,
    require_role,
)
from app.models import (
    CreateRoutingRuleRequest,
    CreateSlaPolicyRequest,
    RoutingResult,
    RoutingRuleResponse,
    SlaPolicyResponse,
)
from app.routing.base import RoutingRuleStore, SlaPolicyStore
from app.routing.engine import RoutingEngine, SlaCalculator
from app.tenancy.base import TenantContext
from app.tickets.base import TicketStore

router = APIRouter(prefix="/v1", tags=["Routing"])

# Module-level dependency singleton (avoids a call inside Depends()).
_require_owner_or_admin = require_role("owner", "admin")


def _rule_response(rule: RoutingRule) -> RoutingRuleResponse:
    return RoutingRuleResponse(
        id=str(rule.id),
        name=rule.name,
        position=rule.position,
        conditions=dict(rule.conditions or {}),
        actions=dict(rule.actions or {}),
        active=rule.active,
    )


def _policy_response(policy: SlaPolicy) -> SlaPolicyResponse:
    return SlaPolicyResponse(
        id=str(policy.id),
        priority=policy.priority,
        resolution_minutes=policy.resolution_minutes,
        active=policy.active,
    )


def _latest(analyses: list[Analysis]) -> Analysis | None:
    return max(analyses, key=lambda a: a.created_at) if analyses else None


# ---------------------------------------------------------------------------
# Routing rules
# ---------------------------------------------------------------------------


@router.post(
    "/orgs/{org_id}/routing-rules",
    response_model=RoutingRuleResponse,
    status_code=201,
    summary="Create a routing rule",
)
async def create_routing_rule(
    org_id: uuid.UUID,
    payload: CreateRoutingRuleRequest,
    _membership: Membership = Depends(_require_owner_or_admin),
    store: RoutingRuleStore = Depends(get_routing_rule_store),
) -> RoutingRuleResponse:
    rule = await store.create(
        organization_id=org_id,
        name=payload.name,
        position=payload.position,
        conditions=payload.conditions.model_dump(exclude_none=True),
        actions=payload.actions.model_dump(exclude_none=True),
    )
    return _rule_response(rule)


@router.get(
    "/orgs/{org_id}/routing-rules",
    response_model=list[RoutingRuleResponse],
    summary="List routing rules",
)
async def list_routing_rules(
    org_id: uuid.UUID,
    _membership: Membership = Depends(require_org_membership),
    store: RoutingRuleStore = Depends(get_routing_rule_store),
) -> list[RoutingRuleResponse]:
    return [_rule_response(r) for r in await store.list_by_org(org_id)]


@router.delete(
    "/orgs/{org_id}/routing-rules/{rule_id}",
    status_code=204,
    summary="Delete a routing rule",
)
async def delete_routing_rule(
    org_id: uuid.UUID,
    rule_id: uuid.UUID,
    _membership: Membership = Depends(_require_owner_or_admin),
    store: RoutingRuleStore = Depends(get_routing_rule_store),
) -> Response:
    if not await store.delete(org_id, rule_id):
        raise HTTPException(status_code=404, detail="Routing rule not found")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# SLA policies
# ---------------------------------------------------------------------------


@router.post(
    "/orgs/{org_id}/sla-policies",
    response_model=SlaPolicyResponse,
    status_code=201,
    summary="Create an SLA policy",
)
async def create_sla_policy(
    org_id: uuid.UUID,
    payload: CreateSlaPolicyRequest,
    _membership: Membership = Depends(_require_owner_or_admin),
    store: SlaPolicyStore = Depends(get_sla_policy_store),
) -> SlaPolicyResponse:
    policy = await store.create(
        organization_id=org_id,
        priority=payload.priority,
        resolution_minutes=payload.resolution_minutes,
    )
    return _policy_response(policy)


@router.get(
    "/orgs/{org_id}/sla-policies",
    response_model=list[SlaPolicyResponse],
    summary="List SLA policies",
)
async def list_sla_policies(
    org_id: uuid.UUID,
    _membership: Membership = Depends(require_org_membership),
    store: SlaPolicyStore = Depends(get_sla_policy_store),
) -> list[SlaPolicyResponse]:
    return [_policy_response(p) for p in await store.list_by_org(org_id)]


@router.delete(
    "/orgs/{org_id}/sla-policies/{policy_id}",
    status_code=204,
    summary="Delete an SLA policy",
)
async def delete_sla_policy(
    org_id: uuid.UUID,
    policy_id: uuid.UUID,
    _membership: Membership = Depends(_require_owner_or_admin),
    store: SlaPolicyStore = Depends(get_sla_policy_store),
) -> Response:
    if not await store.delete(org_id, policy_id):
        raise HTTPException(status_code=404, detail="SLA policy not found")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Apply routing to a ticket
# ---------------------------------------------------------------------------


@router.post(
    "/tickets/{ticket_id}/route",
    response_model=RoutingResult,
    summary="Route a ticket (apply rules + SLA)",
    responses={
        404: {"description": "Ticket not found in this organization"},
        409: {"description": "Ticket has no analysis to route on"},
    },
)
async def route_ticket(
    ticket_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    ticket_store: TicketStore = Depends(get_ticket_store),
    rule_store: RoutingRuleStore = Depends(get_routing_rule_store),
    policy_store: SlaPolicyStore = Depends(get_sla_policy_store),
) -> RoutingResult:
    """Evaluate rules + SLA against the latest analysis; persist on the ticket."""
    org_id = context.organization_id
    ticket = await ticket_store.get_for_org(org_id, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    latest = _latest(ticket.analyses)
    if latest is None:
        raise HTTPException(status_code=409, detail="Ticket has no analysis to route on")

    rules = await rule_store.list_active(org_id)
    policies = await policy_store.list_active(org_id)
    decision = RoutingEngine.evaluate(
        category=latest.category, priority=latest.priority, rules=rules
    )
    due = SlaCalculator.due_at(
        priority=latest.priority, policies=policies, base_time=ticket.created_at
    )

    # Persist the outcome on the ticket (the store's session commits at request end).
    ticket.assignee = decision.assignee
    ticket.sla_due_at = due

    return RoutingResult(
        assignee=decision.assignee,
        tags=list(decision.tags),
        matched_rule_id=str(decision.matched_rule_id) if decision.matched_rule_id else None,
        sla_due_at=due.isoformat() if due is not None else None,
    )
