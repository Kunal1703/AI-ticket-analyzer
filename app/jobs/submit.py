"""
Shared batch-submit orchestration.

Builds the per-item ``analyze_one`` (reusing ``run_analysis``) and the
``on_complete`` webhook dispatch for a batch, then submits it. Used by both the
``/v1/analyze/batch`` route and the CSV import channel, so the orchestration lives
in exactly one place (parameterized by ``source``).
"""

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.base import AnalysisProvider
from app.cache.base import Cache
from app.db.models import BatchJob
from app.jobs.service import BatchService
from app.models import BatchJobResponse
from app.services.analyze import run_analysis
from app.webhooks.base import EVENT_BATCH_COMPLETED, WebhookDispatcher


def batch_job_response(job: BatchJob) -> BatchJobResponse:
    """Render a batch job as its API response model."""
    return BatchJobResponse(
        id=str(job.id),
        status=job.status,
        total=job.total,
        completed=job.completed,
        failed=job.failed,
        created_at=job.created_at.isoformat(),
    )


async def submit_analyze_batch(
    *,
    service: BatchService,
    dispatcher: WebhookDispatcher,
    provider: AnalysisProvider,
    cache: Cache,
    sessionmaker: async_sessionmaker[AsyncSession] | None,
    organization_id: uuid.UUID,
    texts: Sequence[str],
    source: str = "api",
) -> BatchJob:
    """Create + schedule a batch-analyze job; dispatch ``batch.completed`` on finish."""
    total = len(texts)

    async def analyze_one(text: str) -> None:
        await run_analysis(
            ticket_text=text.strip(),
            provider=provider,
            cache=cache,
            sessionmaker=sessionmaker,
            organization_id=organization_id,
            source=source,
        )

    async def on_complete(job_id: uuid.UUID, status: str, completed: int, failed: int) -> None:
        await dispatcher.dispatch(
            organization_id=organization_id,
            event_type=EVENT_BATCH_COMPLETED,
            payload={
                "job_id": str(job_id),
                "status": status,
                "total": total,
                "completed": completed,
                "failed": failed,
            },
        )

    return await service.submit(
        organization_id=organization_id,
        texts=texts,
        analyze_one=analyze_one,
        on_complete=on_complete,
    )
