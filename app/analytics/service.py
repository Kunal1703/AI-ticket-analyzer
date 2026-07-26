"""
Analytics service.

Owns the date-window conversion (calendar ``date`` → half-open ``[start, end)``
datetime bounds, with ``end`` inclusive of its whole day) and assembles the store's
aggregates into API responses. Thin coordinator over the ``AnalyticsStore`` port —
no HTTP concerns, trivially testable with a fake store.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta

from app.analytics.base import AnalyticsStore
from app.models import (
    AnalyticsSummary,
    TimeseriesMetric,
    TimeseriesPoint,
    TimeseriesResponse,
)


def _bounds(start: date | None, end: date | None) -> tuple[datetime | None, datetime | None]:
    """Convert calendar dates to a half-open UTC window; ``end`` day is inclusive."""
    start_dt = datetime.combine(start, time.min, tzinfo=UTC) if start is not None else None
    end_dt = (
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC) if end is not None else None
    )
    return start_dt, end_dt


class AnalyticsService:
    """Assemble tenant analytics from the store."""

    def __init__(self, store: AnalyticsStore) -> None:
        self._store = store

    async def summary(
        self, organization_id: uuid.UUID, *, start: date | None = None, end: date | None = None
    ) -> AnalyticsSummary:
        start_dt, end_dt = _bounds(start, end)
        return AnalyticsSummary(
            start=start.isoformat() if start is not None else None,
            end=end.isoformat() if end is not None else None,
            total_tickets=await self._store.count_tickets(
                organization_id, start=start_dt, end=end_dt
            ),
            total_analyses=await self._store.count_analyses(
                organization_id, start=start_dt, end=end_dt
            ),
            by_category=await self._store.count_by_category(
                organization_id, start=start_dt, end=end_dt
            ),
            by_priority=await self._store.count_by_priority(
                organization_id, start=start_dt, end=end_dt
            ),
        )

    async def timeseries(
        self,
        organization_id: uuid.UUID,
        *,
        metric: TimeseriesMetric,
        start: date | None = None,
        end: date | None = None,
    ) -> TimeseriesResponse:
        start_dt, end_dt = _bounds(start, end)
        if metric is TimeseriesMetric.ANALYSES:
            rows = await self._store.analyses_per_day(organization_id, start=start_dt, end=end_dt)
        else:
            rows = await self._store.tickets_per_day(organization_id, start=start_dt, end=end_dt)
        return TimeseriesResponse(
            metric=metric.value,
            start=start.isoformat() if start is not None else None,
            end=end.isoformat() if end is not None else None,
            points=[TimeseriesPoint(date=day.isoformat(), count=count) for day, count in rows],
        )
