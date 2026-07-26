"""
Batch-analyze orchestration.

``BatchService`` creates a job row, schedules processing on the ``JobRunner``, and
updates the job's status/counts as items are analyzed. The per-item work is a
caller-supplied coroutine (``analyze_one``) that wraps the shared ``run_analysis``
— so batch analysis reuses the exact cache/provider/persist/meter pipeline as the
single-ticket path, with no duplicated logic.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence

from app.db.models import BatchJob
from app.jobs.base import BatchJobStore, JobRunner, JobStatus
from app.observability import metrics

logger = logging.getLogger(__name__)


class BatchService:
    """Create and process asynchronous batch-analyze jobs."""

    def __init__(self, job_store: BatchJobStore, runner: JobRunner) -> None:
        self._jobs = job_store
        self._runner = runner

    async def submit(
        self,
        *,
        organization_id: uuid.UUID,
        texts: Sequence[str],
        analyze_one: Callable[[str], Awaitable[None]],
        on_complete: Callable[[uuid.UUID, str, int, int], Awaitable[None]] | None = None,
    ) -> BatchJob:
        """Create the job and schedule its processing; returns the queued job.

        ``on_complete(job_id, status, completed, failed)`` runs after the job
        reaches a final state (used to dispatch a ``batch.completed`` webhook).
        """
        job = await self._jobs.create(organization_id=organization_id, total=len(texts))
        items = list(texts)
        await self._runner.run(lambda: self._process(job.id, items, analyze_one, on_complete))
        return job

    async def _process(
        self,
        job_id: uuid.UUID,
        texts: Sequence[str],
        analyze_one: Callable[[str], Awaitable[None]],
        on_complete: Callable[[uuid.UUID, str, int, int], Awaitable[None]] | None = None,
    ) -> None:
        completed = 0
        failed = 0
        status = JobStatus.FAILED.value
        try:
            await self._jobs.update(job_id, status=JobStatus.RUNNING.value)
            for text in texts:
                try:
                    await analyze_one(text)
                    completed += 1
                except Exception:
                    logger.exception("Batch item failed (job=%s)", job_id)
                    failed += 1
            status = (
                JobStatus.COMPLETED.value if failed == 0 else JobStatus.COMPLETED_WITH_ERRORS.value
            )
            await self._jobs.update(job_id, status=status, completed=completed, failed=failed)
        except Exception:
            # The whole job failed (e.g. the store is unreachable); record it.
            logger.exception("Batch job crashed (job=%s)", job_id)
            status = JobStatus.FAILED.value
            try:
                await self._jobs.update(job_id, status=status, completed=completed, failed=failed)
            except Exception:
                logger.exception("Failed to mark batch job failed (job=%s)", job_id)
        metrics.record_batch_job(status)

        if on_complete is not None:
            try:
                await on_complete(job_id, status, completed, failed)
            except Exception:
                logger.exception("Batch on_complete hook failed (job=%s)", job_id)
