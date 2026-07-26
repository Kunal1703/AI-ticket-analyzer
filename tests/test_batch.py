"""
Tests for M3.3a: async batch analyze + job-status tracking.

Route/service logic runs with a fake ``BatchJobStore`` and an inline ``JobRunner``
so a submitted batch completes deterministically (no background timing); the
SQLAlchemy store is unit-tested with a fake sessionmaker. A skipif round-trip
covers the real store.
"""

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable, Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.ai import AnalysisResult
from app.db.batch_job_store import SqlAlchemyBatchJobStore
from app.db.models import BatchJob
from app.jobs.base import JobStatus
from app.jobs.runner import BackgroundJobRunner, available_job_runners, build_job_runner
from app.jobs.service import BatchService
from app.models import TicketAnalysis, TicketCategory, TicketPriority
from app.tenancy.base import TenantContext
from httpx import AsyncClient

from tests.test_tickets import ORG

DB_URL = os.environ.get("DATABASE_URL")


class FakeBatchJobStore:
    """In-memory ``BatchJobStore``."""

    def __init__(self) -> None:
        self.jobs: dict[uuid.UUID, BatchJob] = {}

    async def create(self, *, organization_id: uuid.UUID, total: int) -> BatchJob:
        job = BatchJob(organization_id=organization_id, total=total, status=JobStatus.QUEUED.value)
        job.id = uuid.uuid4()
        job.completed = 0
        job.failed = 0
        job.created_at = datetime.now(UTC)
        self.jobs[job.id] = job
        return job

    async def get(self, organization_id: uuid.UUID, job_id: uuid.UUID) -> BatchJob | None:
        job = self.jobs.get(job_id)
        return job if job is not None and job.organization_id == organization_id else None

    async def update(
        self,
        job_id: uuid.UUID,
        *,
        status: str | None = None,
        completed: int | None = None,
        failed: int | None = None,
    ) -> None:
        job = self.jobs.get(job_id)
        if job is None:
            return
        if status is not None:
            job.status = status
        if completed is not None:
            job.completed = completed
        if failed is not None:
            job.failed = failed


class InlineJobRunner:
    """Runs the job immediately (so tests can assert the final state)."""

    async def run(self, job: Callable[[], Awaitable[None]]) -> None:
        await job()

    async def aclose(self) -> None:
        return None


# ---------------------------------------------------------------------------
# BatchService
# ---------------------------------------------------------------------------


class TestBatchService:
    @pytest.mark.anyio
    async def test_all_items_succeed(self) -> None:
        store = FakeBatchJobStore()
        service = BatchService(store, InlineJobRunner())
        seen: list[str] = []

        async def analyze_one(text: str) -> None:
            seen.append(text)

        job = await service.submit(
            organization_id=ORG, texts=["a", "b", "c"], analyze_one=analyze_one
        )
        done = store.jobs[job.id]
        assert done.status == JobStatus.COMPLETED.value
        assert done.completed == 3 and done.failed == 0
        assert seen == ["a", "b", "c"]

    @pytest.mark.anyio
    async def test_partial_failure_records_counts(self) -> None:
        store = FakeBatchJobStore()
        service = BatchService(store, InlineJobRunner())

        async def analyze_one(text: str) -> None:
            if text == "boom":
                raise RuntimeError("provider down")

        job = await service.submit(
            organization_id=ORG, texts=["ok", "boom", "ok"], analyze_one=analyze_one
        )
        done = store.jobs[job.id]
        assert done.status == JobStatus.COMPLETED_WITH_ERRORS.value
        assert done.completed == 2 and done.failed == 1

    @pytest.mark.anyio
    async def test_job_crash_marks_failed(self) -> None:
        # A store that raises while the job is running forces the FAILED path.
        class _FlakyStore(FakeBatchJobStore):
            async def update(self, job_id: uuid.UUID, **kwargs: Any) -> None:
                if kwargs.get("status") == JobStatus.RUNNING.value:
                    raise RuntimeError("store unreachable")
                await super().update(job_id, **kwargs)

        store = _FlakyStore()
        service = BatchService(store, InlineJobRunner())

        async def analyze_one(text: str) -> None:
            return None

        job = await service.submit(organization_id=ORG, texts=["a"], analyze_one=analyze_one)
        assert store.jobs[job.id].status == JobStatus.FAILED.value


# ---------------------------------------------------------------------------
# Runner registry
# ---------------------------------------------------------------------------


class TestJobRunnerRegistry:
    def test_lists_background(self) -> None:
        assert "background" in available_job_runners()

    def test_build_default(self) -> None:
        from app.config import Settings

        runner = build_job_runner(Settings(_env_file=None))  # type: ignore[call-arg]
        assert isinstance(runner, BackgroundJobRunner)

    def test_unknown_backend_raises(self) -> None:
        from app.config import Settings

        with pytest.raises(ValueError, match="Unsupported job queue"):
            build_job_runner(Settings(_env_file=None, job_queue="celery"))  # type: ignore[call-arg]

    @pytest.mark.anyio
    async def test_background_runner_executes_and_drains(self) -> None:
        runner = BackgroundJobRunner()
        ran = asyncio.Event()

        async def job() -> None:
            ran.set()

        await runner.run(job)
        await runner.aclose()  # drains in-flight tasks
        assert ran.is_set()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _mock_provider() -> MagicMock:
    provider = MagicMock()
    provider.name = "test"
    provider.model = "test-model"
    provider.analyze = AsyncMock(
        return_value=AnalysisResult(
            analysis=TicketAnalysis(
                summary="s",
                category=TicketCategory.BILLING,
                priority=TicketPriority.HIGH,
                next_actions=["x"],
            )
        )
    )
    return provider


@pytest.fixture
def batch_overrides() -> Generator[dict[str, Any], None, None]:
    from app.cache.memory import TTLCache
    from app.dependencies import (
        get_analysis_provider,
        get_batch_job_store,
        get_batch_service,
        get_cache,
        get_tenant_context,
        require_quota,
    )
    from app.main import app

    store = FakeBatchJobStore()
    provider = _mock_provider()
    context = TenantContext(organization_id=ORG, principal_type="api_key", scopes=("analyze",))

    app.dependency_overrides[require_quota] = lambda: context
    app.dependency_overrides[get_tenant_context] = lambda: context
    app.dependency_overrides[get_analysis_provider] = lambda: provider
    app.dependency_overrides[get_cache] = lambda: TTLCache(ttl_seconds=300)
    app.dependency_overrides[get_batch_job_store] = lambda: store
    app.dependency_overrides[get_batch_service] = lambda: BatchService(store, InlineJobRunner())
    yield {"store": store, "provider": provider}
    for dep in (
        require_quota,
        get_tenant_context,
        get_analysis_provider,
        get_cache,
        get_batch_job_store,
        get_batch_service,
    ):
        app.dependency_overrides.pop(dep, None)


class TestBatchRoutes:
    @pytest.mark.anyio
    async def test_submit_then_poll(
        self, client: AsyncClient, batch_overrides: dict[str, Any]
    ) -> None:
        resp = await client.post("/v1/analyze/batch", json={"tickets": ["one", "two"]})
        assert resp.status_code == 202
        body = resp.json()
        assert body["total"] == 2
        job_id = body["id"]
        # Inline runner completed the work synchronously.
        assert batch_overrides["provider"].analyze.await_count == 2

        poll = await client.get(f"/v1/analyze/batch/{job_id}")
        assert poll.status_code == 200
        assert poll.json()["status"] == JobStatus.COMPLETED.value
        assert poll.json()["completed"] == 2

    @pytest.mark.anyio
    async def test_empty_batch_422(
        self, client: AsyncClient, batch_overrides: dict[str, Any]
    ) -> None:
        assert (await client.post("/v1/analyze/batch", json={"tickets": []})).status_code == 422

    @pytest.mark.anyio
    async def test_too_many_items_422(
        self, client: AsyncClient, batch_overrides: dict[str, Any]
    ) -> None:
        resp = await client.post("/v1/analyze/batch", json={"tickets": ["x"] * 51})
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_blank_item_422(
        self, client: AsyncClient, batch_overrides: dict[str, Any]
    ) -> None:
        resp = await client.post("/v1/analyze/batch", json={"tickets": ["ok", "   "]})
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_poll_unknown_job_404(
        self, client: AsyncClient, batch_overrides: dict[str, Any]
    ) -> None:
        assert (await client.get(f"/v1/analyze/batch/{uuid.uuid4()}")).status_code == 404


# ---------------------------------------------------------------------------
# SqlAlchemyBatchJobStore
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self, job: BatchJob | None = None) -> None:
        self._job = job
        self.committed = False
        self.added: list[object] = []

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def refresh(self, obj: object) -> None:
        return None

    async def get(self, model: object, ident: object) -> BatchJob | None:
        return self._job

    async def commit(self) -> None:
        self.committed = True


class TestSqlAlchemyBatchJobStore:
    @pytest.mark.anyio
    async def test_create_commits(self) -> None:
        session = _FakeSession()
        store = SqlAlchemyBatchJobStore(MagicMock(return_value=session))
        job = await store.create(organization_id=ORG, total=3)
        assert job.total == 3
        assert session.committed is True

    @pytest.mark.anyio
    async def test_get_scopes_by_org(self) -> None:
        job = BatchJob(organization_id=ORG, total=1, status="queued")
        job.id = uuid.uuid4()
        store = SqlAlchemyBatchJobStore(MagicMock(return_value=_FakeSession(job)))
        assert await store.get(ORG, job.id) is job
        assert await store.get(uuid.uuid4(), job.id) is None  # other org

    @pytest.mark.anyio
    async def test_update_sets_fields(self) -> None:
        job = BatchJob(organization_id=ORG, total=1, status="queued")
        job.completed = 0
        job.failed = 0
        session = _FakeSession(job)
        store = SqlAlchemyBatchJobStore(MagicMock(return_value=session))
        await store.update(job.id, status="completed", completed=1, failed=0)
        assert job.status == "completed" and job.completed == 1
        assert session.committed is True

    @pytest.mark.anyio
    async def test_update_missing_is_noop(self) -> None:
        session = _FakeSession(None)  # get() returns None → job not found
        store = SqlAlchemyBatchJobStore(MagicMock(return_value=session))
        await store.update(uuid.uuid4(), status="completed")
        assert session.committed is False

    @pytest.mark.anyio
    @pytest.mark.skipif(not DB_URL, reason="DATABASE_URL not set; skipping DB integration test")
    async def test_round_trip(self) -> None:
        from app.db.base import Base
        from app.db.models import Organization
        from app.db.session import create_db_engine, create_sessionmaker

        assert DB_URL is not None
        engine = create_db_engine(DB_URL)
        sessionmaker = create_sessionmaker(engine)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with sessionmaker() as session:
                org = Organization(name="Acme", slug="acme-batch")
                session.add(org)
                await session.commit()
                org_id = org.id

            store = SqlAlchemyBatchJobStore(sessionmaker)
            job = await store.create(organization_id=org_id, total=2)
            await store.update(job.id, status="completed", completed=2, failed=0)
            loaded = await store.get(org_id, job.id)
            assert loaded is not None and loaded.status == "completed" and loaded.completed == 2
        finally:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            await engine.dispose()


class TestBatchJobSchema:
    def test_table_registered(self) -> None:
        from app.db.base import Base

        assert "batch_jobs" in Base.metadata.tables
