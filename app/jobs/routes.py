"""
Batch-analyze HTTP routes.

``POST /v1/analyze/batch`` submits N tickets for asynchronous analysis (metered +
quota-gated like ``/v1/analyze``) and returns a job id immediately (202).
``GET /v1/analyze/batch/{job_id}`` polls the job's status/counts. Individual
results are persisted as ordinary tickets/analyses (queryable via /v1/tickets).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.base import AnalysisProvider
from app.cache.base import Cache
from app.dependencies import (
    get_analysis_provider,
    get_batch_job_store,
    get_batch_service,
    get_cache,
    get_db_sessionmaker,
    get_tenant_context,
    get_webhook_dispatcher,
    require_quota,
)
from app.jobs.base import BatchJobStore
from app.jobs.service import BatchService
from app.jobs.submit import batch_job_response, submit_analyze_batch
from app.models import BatchJobResponse, BatchRequest
from app.tenancy.base import TenantContext
from app.webhooks.base import WebhookDispatcher

router = APIRouter(prefix="/v1", tags=["Batch"])


@router.post(
    "/analyze/batch",
    response_model=BatchJobResponse,
    status_code=202,
    summary="Submit a batch of tickets for asynchronous analysis",
    responses={
        401: {"description": "Not authenticated"},
        402: {"description": "Monthly analysis quota reached for the plan"},
        403: {"description": "Insufficient scope / not a member"},
        503: {"description": "Batch analysis requires a database"},
    },
)
async def submit_batch(
    payload: BatchRequest,
    context: TenantContext = Depends(require_quota),
    provider: AnalysisProvider = Depends(get_analysis_provider),
    cache: Cache = Depends(get_cache),
    sessionmaker: async_sessionmaker[AsyncSession] | None = Depends(get_db_sessionmaker),
    service: BatchService = Depends(get_batch_service),
    dispatcher: WebhookDispatcher = Depends(get_webhook_dispatcher),
) -> BatchJobResponse:
    """Queue a batch-analyze job and return it (status ``queued``)."""
    job = await submit_analyze_batch(
        service=service,
        dispatcher=dispatcher,
        provider=provider,
        cache=cache,
        sessionmaker=sessionmaker,
        organization_id=context.organization_id,
        texts=payload.tickets,
        source="api",
    )
    return batch_job_response(job)


@router.get(
    "/analyze/batch/{job_id}",
    response_model=BatchJobResponse,
    summary="Get a batch job's status",
    responses={404: {"description": "Batch job not found in this organization"}},
)
async def get_batch(
    job_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    job_store: BatchJobStore = Depends(get_batch_job_store),
) -> BatchJobResponse:
    """Return the batch job's current status and progress (404 if not in the org)."""
    job = await job_store.get(context.organization_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Batch job not found")
    return batch_job_response(job)
