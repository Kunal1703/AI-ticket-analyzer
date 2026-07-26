"""
Inbound-channel HTTP routes (``/v1/channels``).

Both endpoints are tenant-scoped and metered + quota-gated (like ``/v1/analyze``)
and reuse the shared analyze/batch pipeline; ingested tickets are tagged with
their ``source`` (``"email"`` / ``"csv"``).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.base import AnalysisProvider
from app.cache.base import Cache
from app.channels.csv_parser import parse_csv_tickets
from app.dependencies import (
    get_analysis_provider,
    get_batch_service,
    get_cache,
    get_db_sessionmaker,
    get_webhook_dispatcher,
    require_quota,
)
from app.jobs.service import BatchService
from app.jobs.submit import batch_job_response, submit_analyze_batch
from app.models import BatchJobResponse, EmailInboundRequest, TicketAnalysis
from app.services.analyze import run_analysis
from app.tenancy.base import TenantContext
from app.webhooks.base import WebhookDispatcher

router = APIRouter(prefix="/v1/channels", tags=["Channels"])


@router.post(
    "/email",
    response_model=TicketAnalysis,
    summary="Ingest an email as a ticket",
    responses={
        401: {"description": "Not authenticated"},
        402: {"description": "Monthly analysis quota reached for the plan"},
        403: {"description": "Insufficient scope / not a member"},
    },
)
async def inbound_email(
    payload: EmailInboundRequest,
    context: TenantContext = Depends(require_quota),
    provider: AnalysisProvider = Depends(get_analysis_provider),
    cache: Cache = Depends(get_cache),
    sessionmaker: async_sessionmaker[AsyncSession] | None = Depends(get_db_sessionmaker),
) -> TicketAnalysis:
    """Turn an email into a ticket (source ``"email"``) and analyze it."""
    text = (
        f"{payload.subject}\n\n{payload.body}".strip() if payload.subject else payload.body.strip()
    )
    outcome = await run_analysis(
        ticket_text=text,
        provider=provider,
        cache=cache,
        sessionmaker=sessionmaker,
        organization_id=context.organization_id,
        source="email",
    )
    return outcome.analysis


@router.post(
    "/import",
    response_model=BatchJobResponse,
    status_code=202,
    summary="Import tickets from a CSV",
    description=(
        "Submit a CSV (as the raw request body) of ticket texts. A column named "
        "text/ticket/body/message/description is used (or the single column). The "
        "rows are analyzed asynchronously as a batch (source 'csv')."
    ),
    responses={
        400: {"description": "Malformed, empty, or oversized CSV"},
        401: {"description": "Not authenticated"},
        402: {"description": "Monthly analysis quota reached for the plan"},
        403: {"description": "Insufficient scope / not a member"},
        503: {"description": "Batch analysis requires a database"},
    },
)
async def import_csv(
    request: Request,
    context: TenantContext = Depends(require_quota),
    provider: AnalysisProvider = Depends(get_analysis_provider),
    cache: Cache = Depends(get_cache),
    sessionmaker: async_sessionmaker[AsyncSession] | None = Depends(get_db_sessionmaker),
    service: BatchService = Depends(get_batch_service),
    dispatcher: WebhookDispatcher = Depends(get_webhook_dispatcher),
) -> BatchJobResponse:
    """Parse a CSV upload and submit its rows as an async batch."""
    content = await request.body()
    try:
        texts = parse_csv_tickets(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job = await submit_analyze_batch(
        service=service,
        dispatcher=dispatcher,
        provider=provider,
        cache=cache,
        sessionmaker=sessionmaker,
        organization_id=context.organization_id,
        texts=texts,
        source="csv",
    )
    return batch_job_response(job)
