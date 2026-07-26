"""Analytics persistence port (read-only aggregates, request-scoped)."""

import uuid
from datetime import date, datetime
from typing import Protocol


class AnalyticsStore(Protocol):
    """Aggregate queries over an organization's tickets/analyses.

    All queries are tenant-scoped by ``organization_id`` and bounded by an
    optional half-open ``[start, end)`` window on the row's ``created_at``.
    """

    async def count_tickets(
        self, organization_id: uuid.UUID, *, start: datetime | None, end: datetime | None
    ) -> int: ...

    async def count_analyses(
        self, organization_id: uuid.UUID, *, start: datetime | None, end: datetime | None
    ) -> int: ...

    async def count_by_category(
        self, organization_id: uuid.UUID, *, start: datetime | None, end: datetime | None
    ) -> dict[str, int]: ...

    async def count_by_priority(
        self, organization_id: uuid.UUID, *, start: datetime | None, end: datetime | None
    ) -> dict[str, int]: ...

    async def tickets_per_day(
        self, organization_id: uuid.UUID, *, start: datetime | None, end: datetime | None
    ) -> list[tuple[date, int]]: ...

    async def analyses_per_day(
        self, organization_id: uuid.UUID, *, start: datetime | None, end: datetime | None
    ) -> list[tuple[date, int]]: ...
