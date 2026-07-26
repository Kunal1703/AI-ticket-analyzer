"""
Job runner implementations + registry.

``BackgroundJobRunner`` runs jobs in-process via asyncio background tasks (no
external infrastructure). A Redis-backed worker (arq/Celery) is a future
registry entry selected by ``settings.job_queue``.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from app.config import Settings
from app.jobs.base import JobRunner

logger = logging.getLogger(__name__)


class BackgroundJobRunner:
    """Run jobs in-process as asyncio background tasks (best-effort).

    Suitable for single-instance / degraded-mode operation. For multi-instance
    durability, swap in a Redis-backed worker runner via the registry.
    """

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    async def run(self, job: Callable[[], Coroutine[Any, Any, None]]) -> None:
        # Fire-and-forget: schedule the coroutine and return immediately. A strong
        # reference is kept until completion so the task is not garbage-collected.
        task: asyncio.Task[None] = asyncio.create_task(job())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def aclose(self) -> None:
        if self._tasks:
            logger.info("Draining %d in-flight background job(s)", len(self._tasks))
            await asyncio.gather(*self._tasks, return_exceptions=True)


_RUNNERS: dict[str, Callable[[Settings], JobRunner]] = {
    "background": lambda _settings: BackgroundJobRunner(),
}


def available_job_runners() -> list[str]:
    """Return the sorted list of registered job-runner backends."""
    return sorted(_RUNNERS)


def build_job_runner(settings: Settings) -> JobRunner:
    """Construct the configured job runner.

    Raises:
        ValueError: If ``settings.job_queue`` names an unregistered backend.
    """
    name = settings.job_queue.lower()
    factory = _RUNNERS.get(name)
    if factory is None:
        raise ValueError(
            f"Unsupported job queue {name!r}. Supported: {', '.join(available_job_runners())}."
        )
    return factory(settings)
