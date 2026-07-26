"""
Async jobs: batch analyze + a pluggable job runner (Milestone M3.3a).

A ``JobRunner`` abstracts *how* a background job executes. The default
``BackgroundJobRunner`` runs jobs in-process (an asyncio background task) so the
service needs no external infrastructure — graceful degradation, like the
in-memory cache. A Redis-backed worker (arq/Celery) is the registry-ready
production backend (selected via ``settings.job_queue``), added by implementing
``JobRunner`` and registering it — with no change to routes/services.

``BatchService`` creates a ``BatchJob`` row, hands processing to the runner, and
updates the job's status/counts as items complete. Individual results are
persisted as ordinary tickets/analyses via the shared ``run_analysis``.
"""

from app.jobs.base import BatchJobStore, JobRunner, JobStatus
from app.jobs.runner import BackgroundJobRunner, build_job_runner
from app.jobs.service import BatchService

__all__ = [
    "BackgroundJobRunner",
    "BatchJobStore",
    "BatchService",
    "JobRunner",
    "JobStatus",
    "build_job_runner",
]
