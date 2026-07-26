"""
Tests for M4.1: the Analytics API — the service (window math + assembly), the
routes, and the SQLAlchemy store (mocked session).

Everything runs offline with in-memory fakes; a skipif round-trip covers the real
aggregation SQL.
"""

import os
import uuid
from collections.abc import Generator
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.analytics.service import AnalyticsService, _bounds
from app.db.analytics_store import SqlAlchemyAnalyticsStore
from app.models import TimeseriesMetric
from app.tenancy.base import TenantContext
from httpx import AsyncClient

from tests.test_tickets import ORG

DB_URL = os.environ.get("DATABASE_URL")


class FakeAnalyticsStore:
    """In-memory ``AnalyticsStore`` that also records the window it was called with."""

    def __init__(self) -> None:
        self.tickets = 3
        self.analyses = 5
        self.by_category = {"Billing": 3, "Refund": 2}
        self.by_priority = {"High": 4, "Low": 1}
        self.days = [(date(2026, 7, 1), 2), (date(2026, 7, 2), 3)]
        self.last_window: tuple[datetime | None, datetime | None] | None = None

    async def count_tickets(
        self, organization_id: uuid.UUID, *, start: datetime | None, end: datetime | None
    ) -> int:
        self.last_window = (start, end)
        return self.tickets

    async def count_analyses(
        self, organization_id: uuid.UUID, *, start: datetime | None, end: datetime | None
    ) -> int:
        return self.analyses

    async def count_by_category(
        self, organization_id: uuid.UUID, *, start: datetime | None, end: datetime | None
    ) -> dict[str, int]:
        return self.by_category

    async def count_by_priority(
        self, organization_id: uuid.UUID, *, start: datetime | None, end: datetime | None
    ) -> dict[str, int]:
        return self.by_priority

    async def tickets_per_day(
        self, organization_id: uuid.UUID, *, start: datetime | None, end: datetime | None
    ) -> list[tuple[date, int]]:
        self.last_window = (start, end)
        return self.days

    async def analyses_per_day(
        self, organization_id: uuid.UUID, *, start: datetime | None, end: datetime | None
    ) -> list[tuple[date, int]]:
        return [(date(2026, 7, 1), 9)]


# ---------------------------------------------------------------------------
# Window math
# ---------------------------------------------------------------------------


class TestBounds:
    def test_none_window(self) -> None:
        assert _bounds(None, None) == (None, None)

    def test_end_is_inclusive_of_its_day(self) -> None:
        start_dt, end_dt = _bounds(date(2026, 7, 1), date(2026, 7, 3))
        assert start_dt == datetime(2026, 7, 1, tzinfo=UTC)
        # end is exclusive at the *start* of the following day → July 3 fully included.
        assert end_dt == datetime(2026, 7, 4, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class TestAnalyticsService:
    @pytest.mark.anyio
    async def test_summary_assembles(self) -> None:
        store = FakeAnalyticsStore()
        summary = await AnalyticsService(store).summary(
            ORG, start=date(2026, 7, 1), end=date(2026, 7, 3)
        )
        assert summary.total_tickets == 3
        assert summary.total_analyses == 5
        assert summary.by_category == {"Billing": 3, "Refund": 2}
        assert summary.start == "2026-07-01" and summary.end == "2026-07-03"
        # The store received the converted [start, end) datetime window.
        assert store.last_window == (
            datetime(2026, 7, 1, tzinfo=UTC),
            datetime(2026, 7, 4, tzinfo=UTC),
        )

    @pytest.mark.anyio
    async def test_timeseries_tickets(self) -> None:
        ts = await AnalyticsService(FakeAnalyticsStore()).timeseries(
            ORG, metric=TimeseriesMetric.TICKETS
        )
        assert ts.metric == "tickets"
        assert ts.points[0].date == "2026-07-01" and ts.points[0].count == 2

    @pytest.mark.anyio
    async def test_timeseries_analyses(self) -> None:
        ts = await AnalyticsService(FakeAnalyticsStore()).timeseries(
            ORG, metric=TimeseriesMetric.ANALYSES
        )
        assert ts.metric == "analyses"
        assert ts.points == [ts.points[0]] and ts.points[0].count == 9


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@pytest.fixture
def analytics_overrides() -> Generator[FakeAnalyticsStore, None, None]:
    from app.dependencies import get_analytics_service, get_tenant_context
    from app.main import app

    store = FakeAnalyticsStore()
    context = TenantContext(organization_id=ORG, principal_type="api_key", scopes=("analyze",))
    app.dependency_overrides[get_tenant_context] = lambda: context
    app.dependency_overrides[get_analytics_service] = lambda: AnalyticsService(store)
    yield store
    for dep in (get_tenant_context, get_analytics_service):
        app.dependency_overrides.pop(dep, None)


class TestAnalyticsRoutes:
    @pytest.mark.anyio
    async def test_summary(
        self, client: AsyncClient, analytics_overrides: FakeAnalyticsStore
    ) -> None:
        resp = await client.get("/v1/analytics/summary?start=2026-07-01&end=2026-07-03")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_tickets"] == 3
        assert body["by_priority"] == {"High": 4, "Low": 1}

    @pytest.mark.anyio
    async def test_timeseries_default_metric(
        self, client: AsyncClient, analytics_overrides: FakeAnalyticsStore
    ) -> None:
        resp = await client.get("/v1/analytics/timeseries")
        assert resp.status_code == 200
        assert resp.json()["metric"] == "tickets"
        assert len(resp.json()["points"]) == 2

    @pytest.mark.anyio
    async def test_invalid_metric_422(
        self, client: AsyncClient, analytics_overrides: FakeAnalyticsStore
    ) -> None:
        assert (await client.get("/v1/analytics/timeseries?metric=nope")).status_code == 422

    @pytest.mark.anyio
    async def test_invalid_date_422(
        self, client: AsyncClient, analytics_overrides: FakeAnalyticsStore
    ) -> None:
        assert (await client.get("/v1/analytics/summary?start=not-a-date")).status_code == 422


# ---------------------------------------------------------------------------
# SQLAlchemy store (mocked session)
# ---------------------------------------------------------------------------


class TestSqlAlchemyAnalyticsStore:
    @pytest.mark.anyio
    async def test_count_tickets_scalar(self) -> None:
        session = MagicMock()
        result = MagicMock()
        result.scalar_one.return_value = 7
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyAnalyticsStore(session)
        got = await store.count_tickets(
            ORG, start=datetime(2026, 7, 1, tzinfo=UTC), end=datetime(2026, 7, 4, tzinfo=UTC)
        )
        assert got == 7
        # Sibling delegator over the same helper.
        assert await store.count_analyses(ORG, start=None, end=None) == 7

    @pytest.mark.anyio
    async def test_count_by_category_dict(self) -> None:
        session = MagicMock()
        result = MagicMock()
        result.all.return_value = [("Billing", 3), ("Refund", 2)]
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyAnalyticsStore(session)
        assert await store.count_by_category(ORG, start=None, end=None) == {
            "Billing": 3,
            "Refund": 2,
        }
        assert await store.count_by_priority(ORG, start=None, end=None) == {
            "Billing": 3,
            "Refund": 2,
        }

    @pytest.mark.anyio
    async def test_tickets_per_day_rows(self) -> None:
        session = MagicMock()
        result = MagicMock()
        result.all.return_value = [(date(2026, 7, 1), 2), (date(2026, 7, 2), 3)]
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyAnalyticsStore(session)
        assert await store.analyses_per_day(ORG, start=None, end=None) == [
            (date(2026, 7, 1), 2),
            (date(2026, 7, 2), 3),
        ]
        assert await store.tickets_per_day(ORG, start=None, end=None) == [
            (date(2026, 7, 1), 2),
            (date(2026, 7, 2), 3),
        ]


class TestAnalyticsRoundTrip:
    @pytest.mark.anyio
    @pytest.mark.skipif(not DB_URL, reason="DATABASE_URL not set; skipping DB integration test")
    async def test_aggregates_against_db(self) -> None:
        from app.db.base import Base
        from app.db.models import Analysis, Organization, Ticket
        from app.db.session import create_db_engine, create_sessionmaker

        assert DB_URL is not None
        engine = create_db_engine(DB_URL)
        sessionmaker = create_sessionmaker(engine)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with sessionmaker() as session:
                org = Organization(name="Acme", slug="acme-analytics")
                session.add(org)
                await session.flush()
                for i in range(2):
                    ticket = Ticket(raw_text=f"t{i}", text_hash=f"h{i}", organization_id=org.id)
                    session.add(ticket)
                    await session.flush()
                    session.add(
                        Analysis(
                            ticket_id=ticket.id,
                            organization_id=org.id,
                            summary="s",
                            category="Billing",
                            priority="High",
                            next_actions=["x"],
                        )
                    )
                await session.commit()
                org_id = org.id

            async with sessionmaker() as session:
                store = SqlAlchemyAnalyticsStore(session)
                assert await store.count_tickets(org_id, start=None, end=None) == 2
                assert await store.count_by_category(org_id, start=None, end=None) == {"Billing": 2}
                days = await store.tickets_per_day(org_id, start=None, end=None)
                assert sum(c for _, c in days) == 2
        finally:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            await engine.dispose()
