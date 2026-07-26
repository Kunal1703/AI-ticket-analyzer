"""
SQLAlchemy implementation of the ``BatchJobStore`` port.

Unlike the request-scoped stores, this wraps a *sessionmaker* and opens a fresh,
self-committing session per operation, so a job created during a request is
durable and visible to the background task that processes it.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import BatchJob
from app.jobs.base import JobStatus


class SqlAlchemyBatchJobStore:
    """Batch-job persistence via short, self-committing sessions."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(self, *, organization_id: uuid.UUID, total: int) -> BatchJob:
        async with self._sessionmaker() as session:
            job = BatchJob(
                organization_id=organization_id,
                total=total,
                status=JobStatus.QUEUED.value,
            )
            session.add(job)
            await session.flush()
            await session.refresh(job)  # load server-generated created_at/updated_at
            await session.commit()
            return job

    async def get(self, organization_id: uuid.UUID, job_id: uuid.UUID) -> BatchJob | None:
        async with self._sessionmaker() as session:
            job = await session.get(BatchJob, job_id)
            if job is None or job.organization_id != organization_id:
                return None
            return job

    async def update(
        self,
        job_id: uuid.UUID,
        *,
        status: str | None = None,
        completed: int | None = None,
        failed: int | None = None,
    ) -> None:
        async with self._sessionmaker() as session:
            job = await session.get(BatchJob, job_id)
            if job is None:
                return
            if status is not None:
                job.status = status
            if completed is not None:
                job.completed = completed
            if failed is not None:
                job.failed = failed
            await session.commit()
