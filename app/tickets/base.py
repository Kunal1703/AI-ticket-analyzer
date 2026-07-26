"""
Ticket read port.

``TicketStore`` is the persistence port the ticket read API depends on (mirroring
``OrgStore``/``UsageStore``), so routes can be tested against an in-memory fake
with no database. All queries are tenant-scoped by ``organization_id``.
"""

import uuid
from collections.abc import Sequence
from typing import Protocol

from app.db.models import Feedback, Ticket
from app.models import TicketCategory, TicketPriority, TicketSort, TicketStatus


class TicketStore(Protocol):
    """Read-only persistence port for tenant-scoped tickets + their analyses."""

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        category: TicketCategory | None = None,
        priority: TicketPriority | None = None,
        status: TicketStatus | None = None,
        assignee: str | None = None,
        source: str | None = None,
        search: str | None = None,
        sort: TicketSort = TicketSort.CREATED_DESC,
    ) -> Sequence[Ticket]: ...

    async def count_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        category: TicketCategory | None = None,
        priority: TicketPriority | None = None,
        status: TicketStatus | None = None,
        assignee: str | None = None,
        source: str | None = None,
        search: str | None = None,
    ) -> int: ...

    async def get_for_org(
        self, organization_id: uuid.UUID, ticket_id: uuid.UUID
    ) -> Ticket | None: ...


class FeedbackStore(Protocol):
    """Persistence port for feedback on ticket analyses (tenant-scoped)."""

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        ticket_id: uuid.UUID,
        analysis_id: uuid.UUID,
        rating: str,
        corrected_category: str | None,
        corrected_priority: str | None,
        comment: str | None,
    ) -> Feedback: ...

    async def list_for_ticket(
        self, organization_id: uuid.UUID, ticket_id: uuid.UUID
    ) -> Sequence[Feedback]: ...
