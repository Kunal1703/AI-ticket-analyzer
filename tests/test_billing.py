"""
Unit tests for billing/usage metering (Milestone M2.5a): the plan registry, the
quota-checking service, the SQLAlchemy usage store (mocked session), and the
best-effort metering function.

Also defines an in-memory ``FakeUsageStore`` reused by the /v1/analyze route
tests.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.billing.base import QuotaExceededError
from app.billing.metering import record_analysis_usage
from app.billing.plans import DEFAULT_PLAN, build_plans, get_plan
from app.billing.service import BillingService, current_period_start
from app.db import models
from app.db.base import Base
from app.db.models import UsageEvent
from app.db.session import create_db_engine, create_sessionmaker
from app.db.usage_store import SqlAlchemyUsageStore

DB_URL = os.environ.get("DATABASE_URL")

# ---------------------------------------------------------------------------
# In-memory fake (shared with route tests)
# ---------------------------------------------------------------------------


class FakeUsageStore:
    """In-memory ``UsageStore`` for service/route tests."""

    def __init__(self) -> None:
        self.events: list[UsageEvent] = []

    async def record(
        self,
        *,
        organization_id: uuid.UUID,
        event_type: str,
        quantity: int,
        model: str | None,
        total_tokens: int | None,
    ) -> UsageEvent:
        event = UsageEvent(
            organization_id=organization_id,
            event_type=event_type,
            quantity=quantity,
            model=model,
            total_tokens=total_tokens,
        )
        event.id = uuid.uuid4()
        event.created_at = datetime.now(UTC)
        self.events.append(event)
        return event

    async def count_since(
        self, organization_id: uuid.UUID, *, since: datetime, event_type: str
    ) -> int:
        return sum(
            e.quantity
            for e in self.events
            if e.organization_id == organization_id
            and e.event_type == event_type
            and e.created_at >= since
        )


# ---------------------------------------------------------------------------
# Plan registry
# ---------------------------------------------------------------------------


class TestPlans:
    def test_defaults_present(self) -> None:
        plans = build_plans()
        assert plans["free"].monthly_analysis_limit is not None
        assert plans["enterprise"].monthly_analysis_limit is None  # unlimited

    def test_overrides_merge_over_defaults(self) -> None:
        plans = build_plans({"free": 5, "startup": 42})
        assert plans["free"].monthly_analysis_limit == 5
        assert plans["startup"].monthly_analysis_limit == 42
        # Untouched defaults remain.
        assert plans["pro"].monthly_analysis_limit == build_plans()["pro"].monthly_analysis_limit

    def test_get_plan_unknown_falls_back_to_default(self) -> None:
        plans = build_plans()
        assert get_plan(plans, "does-not-exist").name == DEFAULT_PLAN
        assert get_plan(plans, None).name == DEFAULT_PLAN

    def test_get_plan_missing_default_fails_open_unlimited(self) -> None:
        plans = {"pro": build_plans()["pro"]}  # no "free"
        assert get_plan(plans, "nope").monthly_analysis_limit is None


class TestCurrentPeriodStart:
    def test_is_first_of_month_midnight_utc(self) -> None:
        start = current_period_start(datetime(2026, 7, 2, 13, 45, tzinfo=UTC))
        assert (start.year, start.month, start.day) == (2026, 7, 1)
        assert (start.hour, start.minute, start.second, start.microsecond) == (0, 0, 0, 0)


# ---------------------------------------------------------------------------
# BillingService.check_quota
# ---------------------------------------------------------------------------


class TestBillingServiceQuota:
    @pytest.mark.anyio
    async def test_under_limit_passes(self) -> None:
        org = uuid.uuid4()
        store = FakeUsageStore()
        await store.record(
            organization_id=org, event_type="analysis", quantity=1, model=None, total_tokens=None
        )
        service = BillingService(store, build_plans({"free": 5}))
        await service.check_quota(org, "free")  # 1 < 5 → ok

    @pytest.mark.anyio
    async def test_at_limit_raises(self) -> None:
        org = uuid.uuid4()
        store = FakeUsageStore()
        for _ in range(5):
            await store.record(
                organization_id=org,
                event_type="analysis",
                quantity=1,
                model=None,
                total_tokens=None,
            )
        service = BillingService(store, build_plans({"free": 5}))
        with pytest.raises(QuotaExceededError):
            await service.check_quota(org, "free")  # 5 >= 5 → denied

    @pytest.mark.anyio
    async def test_unlimited_plan_never_touches_store(self) -> None:
        service = BillingService(MagicMock(), build_plans({"enterprise": None}))
        await service.check_quota(uuid.uuid4(), "enterprise")  # no store call, no raise

    @pytest.mark.anyio
    async def test_usage_before_period_start_is_ignored(self) -> None:
        org = uuid.uuid4()
        store = FakeUsageStore()
        # An event stamped last month must not count toward this month's quota.
        old = await store.record(
            organization_id=org, event_type="analysis", quantity=1, model=None, total_tokens=None
        )
        old.created_at = current_period_start() - timedelta(days=1)
        service = BillingService(store, build_plans({"free": 1}))
        await service.check_quota(org, "free")  # in-period usage is 0 → ok

    @pytest.mark.anyio
    async def test_unknown_plan_uses_default_limit(self) -> None:
        org = uuid.uuid4()
        store = FakeUsageStore()
        for _ in range(build_plans()[DEFAULT_PLAN].monthly_analysis_limit or 0):
            await store.record(
                organization_id=org,
                event_type="analysis",
                quantity=1,
                model=None,
                total_tokens=None,
            )
        service = BillingService(store)
        with pytest.raises(QuotaExceededError):
            await service.check_quota(org, "mystery-plan")  # falls back to default → denied


# ---------------------------------------------------------------------------
# SqlAlchemyUsageStore (mocked session)
# ---------------------------------------------------------------------------


class TestSqlAlchemyUsageStore:
    @pytest.mark.anyio
    async def test_record_adds_and_flushes(self) -> None:
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        store = SqlAlchemyUsageStore(session)
        event = await store.record(
            organization_id=uuid.uuid4(),
            event_type="analysis",
            quantity=1,
            model="m",
            total_tokens=42,
        )
        assert event.total_tokens == 42
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    @pytest.mark.anyio
    async def test_count_since_returns_scalar(self) -> None:
        session = MagicMock()
        result = MagicMock()
        result.scalar_one.return_value = 7
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyUsageStore(session)
        count = await store.count_since(
            uuid.uuid4(), since=datetime.now(UTC), event_type="analysis"
        )
        assert count == 7


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestUsageEventSchema:
    def test_table_registered(self) -> None:
        assert "usage_events" in Base.metadata.tables

    def test_organization_id_is_not_nullable(self) -> None:
        assert UsageEvent.__table__.columns["organization_id"].nullable is False

    @pytest.mark.anyio
    @pytest.mark.skipif(not DB_URL, reason="DATABASE_URL not set; skipping DB integration test")
    async def test_usage_round_trip(self) -> None:
        assert DB_URL is not None  # guaranteed by skipif
        engine = create_db_engine(DB_URL)
        sessionmaker = create_sessionmaker(engine)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with sessionmaker() as session:
                org = models.Organization(name="Acme", slug="acme-usage")
                session.add(org)
                await session.flush()
                store = SqlAlchemyUsageStore(session)
                await store.record(
                    organization_id=org.id,
                    event_type="analysis",
                    quantity=1,
                    model="m",
                    total_tokens=5,
                )
                await session.commit()
                org_id = org.id

            async with sessionmaker() as session:
                count = await SqlAlchemyUsageStore(session).count_since(
                    org_id, since=current_period_start(), event_type="analysis"
                )
                assert count == 1
        finally:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            await engine.dispose()


# ---------------------------------------------------------------------------
# Best-effort metering
# ---------------------------------------------------------------------------


class _FakeSession:
    """Minimal async-context-manager session stand-in."""

    def __init__(self) -> None:
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

    async def commit(self) -> None:
        self.committed = True


class TestRecordAnalysisUsage:
    @pytest.mark.anyio
    async def test_noop_without_sessionmaker(self) -> None:
        await record_analysis_usage(None, organization_id=uuid.uuid4())

    @pytest.mark.anyio
    async def test_noop_without_org(self) -> None:
        sessionmaker = MagicMock()
        await record_analysis_usage(sessionmaker, organization_id=None)
        sessionmaker.assert_not_called()

    @pytest.mark.anyio
    async def test_records_and_commits(self) -> None:
        session = _FakeSession()
        sessionmaker = MagicMock(return_value=session)
        await record_analysis_usage(
            sessionmaker, organization_id=uuid.uuid4(), model="m", total_tokens=10
        )
        assert session.committed is True
        assert len(session.added) == 1

    @pytest.mark.anyio
    async def test_swallows_errors(self) -> None:
        failing = MagicMock(side_effect=RuntimeError("db down"))
        # Must not raise despite the failing factory.
        await record_analysis_usage(failing, organization_id=uuid.uuid4())
        failing.assert_called_once()
