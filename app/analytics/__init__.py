"""
Analytics API (Milestone M4.1).

Read-only, tenant-scoped aggregate metrics over the org's tickets/analyses
(``/v1/analytics/*``). Aggregation runs in SQL (`GROUP BY`, counts) behind an
``AnalyticsStore`` port; ``AnalyticsService`` owns the date-window logic and
assembles the responses. This reads the existing OLTP tables — an OLAP store /
materialized views are a later scale concern (see [14_remaining_roadmap.md]).
"""

from app.analytics.base import AnalyticsStore
from app.analytics.service import AnalyticsService

__all__ = ["AnalyticsService", "AnalyticsStore"]
