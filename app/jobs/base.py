"""
Async-job primitives: the job status enum and persistence/runner ports.

``BatchJobStore`` intentionally wraps a *sessionmaker* (not a request session):
its operations open their own short sessions and commit, so a job created during
a request is visible to the background task that processes it afterwards. This is
a deliberate departure from the request-scoped stores.
"""

import uuid
from collections.abc import Callable, Coroutine
from enum import Enum
from typing import Any, Protocol

from app.db.models import BatchJob


class JobStatus(str, Enum):
    """Lifecycle of a batch job."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class BatchJobStore(Protocol):
    """Persistence port for batch jobs (backed by a sessionmaker; see module doc)."""

    async def create(self, *, organization_id: uuid.UUID, total: int) -> BatchJob: ...

    async def get(self, organization_id: uuid.UUID, job_id: uuid.UUID) -> BatchJob | None: ...

    async def update(
        self,
        job_id: uuid.UUID,
        *,
        status: str | None = None,
        completed: int | None = None,
        failed: int | None = None,
    ) -> None: ...


class JobRunner(Protocol):
    """Executes a background job. Implementations decide in-process vs. worker."""

    async def run(self, job: Callable[[], Coroutine[Any, Any, None]]) -> None:
        """Schedule ``job`` to run. Returns without waiting for completion."""
        ...

    async def aclose(self) -> None:
        """Release resources / drain in-flight jobs at shutdown."""
        ...
