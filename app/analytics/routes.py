"""
Analytics HTTP routes (``/v1/analytics``).

Tenant-scoped read metrics (resolved via ``get_tenant_context`` — API key or JWT,
any org member). An optional ``start``/``end`` date window bounds every query;
``end`` is inclusive of its whole calendar day.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query

from app.analytics.service import AnalyticsService
from app.dependencies import get_analytics_service, get_tenant_context
from app.models import AnalyticsSummary, TimeseriesMetric, TimeseriesResponse
from app.tenancy.base import TenantContext

router = APIRouter(prefix="/v1/analytics", tags=["Analytics"])


@router.get(
    "/summary",
    response_model=AnalyticsSummary,
    summary="Aggregate ticket/analysis metrics",
)
async def analytics_summary(
    context: TenantContext = Depends(get_tenant_context),
    service: AnalyticsService = Depends(get_analytics_service),
    start: date | None = Query(None, description="Inclusive start date (UTC)."),
    end: date | None = Query(None, description="Inclusive end date (UTC)."),
) -> AnalyticsSummary:
    """Return totals and category/priority distributions for the organization."""
    return await service.summary(context.organization_id, start=start, end=end)


@router.get(
    "/timeseries",
    response_model=TimeseriesResponse,
    summary="Daily counts of tickets or analyses",
)
async def analytics_timeseries(
    context: TenantContext = Depends(get_tenant_context),
    service: AnalyticsService = Depends(get_analytics_service),
    metric: TimeseriesMetric = Query(TimeseriesMetric.TICKETS),
    start: date | None = Query(None, description="Inclusive start date (UTC)."),
    end: date | None = Query(None, description="Inclusive end date (UTC)."),
) -> TimeseriesResponse:
    """Return a daily time series of tickets or analyses for the organization."""
    return await service.timeseries(context.organization_id, metric=metric, start=start, end=end)
