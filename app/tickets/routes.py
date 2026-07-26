"""
Ticket HTTP routes (``/v1/tickets``): read/history (M3.1) plus feedback capture
and re-analyze (M3.2).

Tenant-scoped: every query is bound to the caller's resolved organization
(``get_tenant_context`` — API key or JWT). Tickets are created on the analyze
path, never here; legacy org-less tickets are never exposed. Re-analyze appends a
new versioned analysis (metered + quota-gated, like ``/v1/analyze``); feedback is
an additive training signal on a specific analysis.
"""

import uuid
from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.base import AnalysisProvider
from app.cache.base import Cache
from app.db.models import Analysis, Feedback, Ticket
from app.dependencies import (
    get_analysis_provider,
    get_cache,
    get_context_retriever,
    get_db_sessionmaker,
    get_feedback_store,
    get_tenant_context,
    get_ticket_store,
    require_quota,
)
from app.models import (
    AnalysisRead,
    AnalyzeResponse,
    CreateFeedbackRequest,
    FeedbackResponse,
    PaginatedTickets,
    TicketCategory,
    TicketDetail,
    TicketPriority,
    TicketSort,
    TicketStatus,
    TicketSummary,
    UpdateTicketRequest,
)
from app.rag.retrieval import ContextRetriever
from app.services.analyze import run_analysis
from app.tenancy.base import TenantContext
from app.tickets.base import FeedbackStore, TicketStore

router = APIRouter(prefix="/v1", tags=["Tickets"])


def _latest(analyses: Sequence[Analysis]) -> Analysis | None:
    """Return the most recent analysis (append-only history), or None."""
    return max(analyses, key=lambda a: a.created_at) if analyses else None


def _analysis_read(analysis: Analysis) -> AnalysisRead:
    return AnalysisRead(
        id=str(analysis.id),
        summary=analysis.summary,
        category=analysis.category,
        priority=analysis.priority,
        next_actions=list(analysis.next_actions),
        model=analysis.model,
        prompt_version=analysis.prompt_version,
        created_at=analysis.created_at.isoformat(),
    )


def _summary(ticket: Ticket) -> TicketSummary:
    latest = _latest(ticket.analyses)
    return TicketSummary(
        id=str(ticket.id),
        source=ticket.source,
        status=ticket.status,
        created_at=ticket.created_at.isoformat(),
        analyses_count=len(ticket.analyses),
        latest_category=latest.category if latest is not None else None,
        latest_priority=latest.priority if latest is not None else None,
        latest_summary=latest.summary if latest is not None else None,
        assignee=ticket.assignee,
        sla_due_at=ticket.sla_due_at.isoformat() if ticket.sla_due_at is not None else None,
    )


def _detail(ticket: Ticket) -> TicketDetail:
    analyses = sorted(ticket.analyses, key=lambda a: a.created_at)
    return TicketDetail(
        id=str(ticket.id),
        source=ticket.source,
        status=ticket.status,
        raw_text=ticket.raw_text,
        created_at=ticket.created_at.isoformat(),
        assignee=ticket.assignee,
        sla_due_at=ticket.sla_due_at.isoformat() if ticket.sla_due_at is not None else None,
        analyses=[_analysis_read(a) for a in analyses],
    )


@router.get(
    "/tickets",
    response_model=PaginatedTickets,
    summary="List tickets",
    description=(
        "List the caller's organization's tickets (most recent first), with "
        "pagination and optional category/priority filters. Each item includes "
        "its latest analysis."
    ),
)
async def list_tickets(
    context: TenantContext = Depends(get_tenant_context),
    store: TicketStore = Depends(get_ticket_store),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    category: TicketCategory | None = Query(None),
    priority: TicketPriority | None = Query(None),
    status: TicketStatus | None = Query(None),
    assignee: str | None = Query(None, max_length=255),
    source: str | None = Query(None, max_length=32),
    search: str | None = Query(None, max_length=200),
    sort: TicketSort = Query(TicketSort.CREATED_DESC),
) -> PaginatedTickets:
    """Return a page of the organization's tickets."""
    org_id = context.organization_id
    tickets = await store.list_for_org(
        org_id,
        limit=limit,
        offset=offset,
        category=category,
        priority=priority,
        status=status,
        assignee=assignee,
        source=source,
        search=search,
        sort=sort,
    )
    total = await store.count_for_org(
        org_id,
        category=category,
        priority=priority,
        status=status,
        assignee=assignee,
        source=source,
        search=search,
    )
    return PaginatedTickets(
        items=[_summary(t) for t in tickets], total=total, limit=limit, offset=offset
    )


@router.get(
    "/tickets/{ticket_id}",
    response_model=TicketDetail,
    summary="Get a ticket with its analysis history",
    responses={404: {"description": "Ticket not found in this organization"}},
)
async def get_ticket(
    ticket_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    store: TicketStore = Depends(get_ticket_store),
) -> TicketDetail:
    """Return a single ticket and its versioned analyses (404 if not in the org)."""
    ticket = await store.get_for_org(context.organization_id, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return _detail(ticket)


@router.patch(
    "/tickets/{ticket_id}",
    response_model=TicketDetail,
    summary="Update a ticket's status and/or assignee",
    description=(
        "Partially update the ticket's workspace fields. Only fields present in "
        'the request are applied; `{"assignee": null}` clears the assignee. '
        "Status transitions are unrestricted. Any organization member may update."
    ),
    responses={
        404: {"description": "Ticket not found in this organization"},
        422: {"description": "No updatable fields provided / invalid status"},
    },
)
async def update_ticket(
    ticket_id: uuid.UUID,
    payload: UpdateTicketRequest,
    context: TenantContext = Depends(get_tenant_context),
    store: TicketStore = Depends(get_ticket_store),
) -> TicketDetail:
    """Update a ticket's ``status`` and/or ``assignee`` (M3.6)."""
    fields = payload.model_fields_set
    if not fields & {"status", "assignee"}:
        raise HTTPException(status_code=422, detail="No updatable fields provided")
    ticket = await store.get_for_org(context.organization_id, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Apply only the fields the caller actually sent (so null clears vs. omitted
    # leaves unchanged). The request-scoped session commits the mutation.
    if "status" in fields and payload.status is not None:
        ticket.status = payload.status.value
    if "assignee" in fields:
        ticket.assignee = payload.assignee
    return _detail(ticket)


# ---------------------------------------------------------------------------
# Re-analyze (M3.2)
# ---------------------------------------------------------------------------


@router.post(
    "/tickets/{ticket_id}/reanalyze",
    response_model=AnalyzeResponse,
    summary="Re-analyze a ticket",
    description=(
        "Re-run the AI on the ticket's stored text and append a new versioned "
        "analysis. Metered and quota-gated like /v1/analyze (API-key callers need "
        "the 'analyze' scope). Returns the analysis plus the ticket_id."
    ),
    responses={
        401: {"description": "Not authenticated"},
        402: {"description": "Monthly analysis quota reached for the plan"},
        403: {"description": "Insufficient scope / not a member"},
        404: {"description": "Ticket not found in this organization"},
    },
)
async def reanalyze_ticket(
    ticket_id: uuid.UUID,
    context: TenantContext = Depends(require_quota),
    store: TicketStore = Depends(get_ticket_store),
    provider: AnalysisProvider = Depends(get_analysis_provider),
    cache: Cache = Depends(get_cache),
    sessionmaker: async_sessionmaker[AsyncSession] | None = Depends(get_db_sessionmaker),
    retrieve_context: ContextRetriever | None = Depends(get_context_retriever),
) -> AnalyzeResponse:
    """Force a fresh analysis of an existing ticket and append it to the history."""
    ticket = await store.get_for_org(context.organization_id, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    outcome = await run_analysis(
        ticket_text=ticket.raw_text,
        provider=provider,
        cache=cache,
        sessionmaker=sessionmaker,
        organization_id=context.organization_id,
        bypass_cache=True,
        retrieve_context=retrieve_context,
    )
    return AnalyzeResponse(**outcome.analysis.model_dump(), ticket_id=str(ticket.id))


# ---------------------------------------------------------------------------
# Feedback (M3.2)
# ---------------------------------------------------------------------------


def _feedback_response(feedback: Feedback) -> FeedbackResponse:
    return FeedbackResponse(
        id=str(feedback.id),
        ticket_id=str(feedback.ticket_id),
        analysis_id=str(feedback.analysis_id),
        rating=feedback.rating,
        corrected_category=feedback.corrected_category,
        corrected_priority=feedback.corrected_priority,
        comment=feedback.comment,
        created_at=feedback.created_at.isoformat(),
    )


def _resolve_analysis(ticket: Ticket, analysis_id: str | None) -> Analysis:
    """Return the analysis the feedback targets (explicit id, else the latest).

    Raises 400 for a malformed id, 404 when the analysis isn't part of the ticket
    or the ticket has no analysis to rate.
    """
    if analysis_id is not None:
        try:
            target = uuid.UUID(analysis_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid analysis_id") from exc
        match = next((a for a in ticket.analyses if a.id == target), None)
        if match is None:
            raise HTTPException(status_code=404, detail="Analysis not found for this ticket")
        return match
    latest = _latest(ticket.analyses)
    if latest is None:
        raise HTTPException(status_code=404, detail="Ticket has no analysis to rate")
    return latest


@router.post(
    "/tickets/{ticket_id}/feedback",
    response_model=FeedbackResponse,
    status_code=201,
    summary="Submit feedback on a ticket's analysis",
    responses={404: {"description": "Ticket or analysis not found in this organization"}},
)
async def create_feedback(
    ticket_id: uuid.UUID,
    payload: CreateFeedbackRequest,
    context: TenantContext = Depends(get_tenant_context),
    store: TicketStore = Depends(get_ticket_store),
    feedback_store: FeedbackStore = Depends(get_feedback_store),
) -> FeedbackResponse:
    """Record feedback on an analysis (defaults to the ticket's latest analysis)."""
    ticket = await store.get_for_org(context.organization_id, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    analysis = _resolve_analysis(ticket, payload.analysis_id)
    feedback = await feedback_store.create(
        organization_id=context.organization_id,
        ticket_id=ticket.id,
        analysis_id=analysis.id,
        rating=payload.rating.value,
        corrected_category=(
            payload.corrected_category.value if payload.corrected_category is not None else None
        ),
        corrected_priority=(
            payload.corrected_priority.value if payload.corrected_priority is not None else None
        ),
        comment=payload.comment,
    )
    return _feedback_response(feedback)


@router.get(
    "/tickets/{ticket_id}/feedback",
    response_model=list[FeedbackResponse],
    summary="List a ticket's feedback",
    responses={404: {"description": "Ticket not found in this organization"}},
)
async def list_feedback(
    ticket_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    store: TicketStore = Depends(get_ticket_store),
    feedback_store: FeedbackStore = Depends(get_feedback_store),
) -> list[FeedbackResponse]:
    """Return all feedback recorded for a ticket (most recent first)."""
    ticket = await store.get_for_org(context.organization_id, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    items = await feedback_store.list_for_ticket(context.organization_id, ticket_id)
    return [_feedback_response(f) for f in items]
