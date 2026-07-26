"""
Tests for M3.1: tenant-scoped ticket read/history API (/v1/tickets).

Routes are exercised with an in-memory ``FakeTicketStore`` and an overridden
tenant context (no DB/auth stack); the SQLAlchemy store is unit-tested with a
mocked session.
"""

import os
import uuid
from collections.abc import Generator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.db.models import Analysis, Ticket
from app.db.ticket_store import SqlAlchemyTicketStore
from app.models import TicketCategory, TicketPriority
from app.tenancy.base import TenantContext
from httpx import AsyncClient

ORG = uuid.uuid4()
DB_URL = os.environ.get("DATABASE_URL")


def _ticket(
    *,
    org: uuid.UUID = ORG,
    source: str = "api",
    analyses: int = 1,
    status: str = "open",
    assignee: str | None = None,
    raw_text: str = "I was charged twice.",
    created_at: datetime | None = None,
) -> Ticket:
    ticket = Ticket(raw_text=raw_text, text_hash="h", source=source)
    ticket.id = uuid.uuid4()
    ticket.organization_id = org
    ticket.status = status
    ticket.assignee = assignee
    ticket.created_at = created_at or datetime.now(UTC)
    rows: list[Analysis] = []
    for i in range(analyses):
        row = Analysis(
            summary=f"summary {i}",
            category=TicketCategory.BILLING.value,
            priority=TicketPriority.HIGH.value,
            next_actions=["Verify payment"],
            model="test-model",
        )
        row.id = uuid.uuid4()
        row.created_at = datetime.now(UTC) + timedelta(seconds=i)
        rows.append(row)
    ticket.analyses = rows
    return ticket


class FakeTicketStore:
    """In-memory ``TicketStore`` (M3.6: supports the workspace filters + sort)."""

    def __init__(self, tickets: list[Ticket] | None = None) -> None:
        self.tickets = tickets or []

    def _match(
        self,
        t: Ticket,
        org: uuid.UUID,
        category: TicketCategory | None,
        priority: TicketPriority | None,
        status: Any | None = None,
        assignee: str | None = None,
        source: str | None = None,
        search: str | None = None,
    ) -> bool:
        if t.organization_id != org:
            return False
        if category is not None and not any(a.category == category.value for a in t.analyses):
            return False
        if priority is not None and not any(a.priority == priority.value for a in t.analyses):
            return False
        if status is not None and t.status != status.value:
            return False
        if assignee is not None and t.assignee != assignee:
            return False
        if source is not None and t.source != source:
            return False
        return not search or search.lower() in t.raw_text.lower()

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        category: TicketCategory | None = None,
        priority: TicketPriority | None = None,
        status: Any | None = None,
        assignee: str | None = None,
        source: str | None = None,
        search: str | None = None,
        sort: Any | None = None,
    ) -> Sequence[Ticket]:
        matched = [
            t
            for t in self.tickets
            if self._match(t, organization_id, category, priority, status, assignee, source, search)
        ]
        ascending = sort is not None and getattr(sort, "value", None) == "created_at"
        matched.sort(key=lambda t: t.created_at, reverse=not ascending)
        return matched[offset : offset + limit]

    async def count_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        category: TicketCategory | None = None,
        priority: TicketPriority | None = None,
        status: Any | None = None,
        assignee: str | None = None,
        source: str | None = None,
        search: str | None = None,
    ) -> int:
        return len(
            [
                t
                for t in self.tickets
                if self._match(
                    t, organization_id, category, priority, status, assignee, source, search
                )
            ]
        )

    async def get_for_org(self, organization_id: uuid.UUID, ticket_id: uuid.UUID) -> Ticket | None:
        for t in self.tickets:
            if t.id == ticket_id and t.organization_id == organization_id:
                return t
        return None


@pytest.fixture
def ticket_overrides() -> Generator[FakeTicketStore, None, None]:
    from app.dependencies import get_ticket_store
    from app.main import app
    from app.tickets.routes import get_tenant_context

    store = FakeTicketStore()
    app.dependency_overrides[get_ticket_store] = lambda: store
    app.dependency_overrides[get_tenant_context] = lambda: TenantContext(
        organization_id=ORG, principal_type="api_key", scopes=("analyze",)
    )
    yield store
    app.dependency_overrides.pop(get_ticket_store, None)
    app.dependency_overrides.pop(get_tenant_context, None)


class TestListTickets:
    @pytest.mark.anyio
    async def test_lists_org_tickets_with_latest_analysis(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        # Explicit timestamps so the default (newest-first) order is deterministic.
        newer = _ticket(analyses=2, created_at=datetime(2026, 6, 1, tzinfo=UTC))
        older = _ticket(analyses=1, created_at=datetime(2026, 1, 1, tzinfo=UTC))
        ticket_overrides.tickets = [older, newer]
        resp = await client.get("/v1/tickets")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["limit"] == 20 and body["offset"] == 0
        first = body["items"][0]  # newest ticket, which has 2 analyses
        assert first["latest_category"] == "Billing"
        assert first["latest_priority"] == "High"
        assert first["latest_summary"] == "summary 1"  # newest analysis of the two
        assert first["analyses_count"] == 2

    @pytest.mark.anyio
    async def test_pagination(self, client: AsyncClient, ticket_overrides: FakeTicketStore) -> None:
        ticket_overrides.tickets = [_ticket(analyses=1) for _ in range(5)]
        resp = await client.get("/v1/tickets", params={"limit": 2, "offset": 2})
        body = resp.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2
        assert body["limit"] == 2 and body["offset"] == 2

    @pytest.mark.anyio
    async def test_filter_by_category(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        ticket_overrides.tickets = [_ticket(analyses=1)]
        # Matching category returns the ticket; a different one returns none.
        hit = await client.get("/v1/tickets", params={"category": "Billing"})
        assert hit.json()["total"] == 1
        miss = await client.get("/v1/tickets", params={"category": "Refund"})
        assert miss.json()["total"] == 0

    @pytest.mark.anyio
    async def test_invalid_limit_is_422(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        assert (await client.get("/v1/tickets", params={"limit": 0})).status_code == 422
        assert (await client.get("/v1/tickets", params={"limit": 101})).status_code == 422


class TestGetTicket:
    @pytest.mark.anyio
    async def test_returns_ticket_with_history(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        ticket = _ticket(analyses=3)
        ticket_overrides.tickets = [ticket]
        resp = await client.get(f"/v1/tickets/{ticket.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["raw_text"] == "I was charged twice."
        assert len(body["analyses"]) == 3
        # History is returned oldest-first.
        assert [a["summary"] for a in body["analyses"]] == ["summary 0", "summary 1", "summary 2"]

    @pytest.mark.anyio
    async def test_unknown_ticket_404(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        resp = await client.get(f"/v1/tickets/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_other_org_ticket_404(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        # A ticket belonging to a different org must not be readable (tenant isolation).
        other = _ticket(org=uuid.uuid4(), analyses=1)
        ticket_overrides.tickets = [other]
        resp = await client.get(f"/v1/tickets/{other.id}")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_detail_includes_status(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        ticket = _ticket(status="pending", analyses=1)
        ticket_overrides.tickets = [ticket]
        resp = await client.get(f"/v1/tickets/{ticket.id}")
        assert resp.json()["status"] == "pending"


class TestUpdateTicket:
    """M3.6: PATCH /v1/tickets/{id} — status + manual assignee."""

    @pytest.mark.anyio
    async def test_update_status(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        ticket = _ticket(status="open", analyses=1)
        ticket_overrides.tickets = [ticket]
        resp = await client.patch(f"/v1/tickets/{ticket.id}", json={"status": "in_progress"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"
        assert ticket.status == "in_progress"

    @pytest.mark.anyio
    async def test_set_assignee(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        ticket = _ticket(analyses=1)
        ticket_overrides.tickets = [ticket]
        resp = await client.patch(f"/v1/tickets/{ticket.id}", json={"assignee": "alice"})
        assert resp.status_code == 200
        assert resp.json()["assignee"] == "alice"

    @pytest.mark.anyio
    async def test_clear_assignee_with_explicit_null(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        ticket = _ticket(assignee="bob", analyses=1)
        ticket_overrides.tickets = [ticket]
        resp = await client.patch(f"/v1/tickets/{ticket.id}", json={"assignee": None})
        assert resp.status_code == 200
        assert resp.json()["assignee"] is None
        assert ticket.assignee is None

    @pytest.mark.anyio
    async def test_no_fields_is_422(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        ticket = _ticket(analyses=1)
        ticket_overrides.tickets = [ticket]
        resp = await client.patch(f"/v1/tickets/{ticket.id}", json={})
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_invalid_status_is_422(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        ticket = _ticket(analyses=1)
        ticket_overrides.tickets = [ticket]
        resp = await client.patch(f"/v1/tickets/{ticket.id}", json={"status": "bogus"})
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_unknown_ticket_404(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        resp = await client.patch(f"/v1/tickets/{uuid.uuid4()}", json={"status": "resolved"})
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_cross_org_404(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        other = _ticket(org=uuid.uuid4(), analyses=1)
        ticket_overrides.tickets = [other]
        resp = await client.patch(f"/v1/tickets/{other.id}", json={"status": "closed"})
        assert resp.status_code == 404


class TestListFilters:
    """M3.6: status/assignee/source/search filters + sort on GET /v1/tickets."""

    @pytest.mark.anyio
    async def test_filter_by_status(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        ticket_overrides.tickets = [_ticket(status="open"), _ticket(status="resolved")]
        resp = await client.get("/v1/tickets", params={"status": "resolved"})
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["status"] == "resolved"

    @pytest.mark.anyio
    async def test_filter_by_assignee(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        ticket_overrides.tickets = [_ticket(assignee="alice"), _ticket(assignee="bob")]
        resp = await client.get("/v1/tickets", params={"assignee": "alice"})
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["assignee"] == "alice"

    @pytest.mark.anyio
    async def test_filter_by_source(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        ticket_overrides.tickets = [_ticket(source="email"), _ticket(source="api")]
        resp = await client.get("/v1/tickets", params={"source": "email"})
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["source"] == "email"

    @pytest.mark.anyio
    async def test_search_matches_raw_text(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        ticket_overrides.tickets = [
            _ticket(raw_text="Refund my subscription"),
            _ticket(raw_text="Login is broken"),
        ]
        resp = await client.get("/v1/tickets", params={"search": "refund"})
        assert resp.json()["total"] == 1

    @pytest.mark.anyio
    async def test_invalid_status_filter_is_422(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        assert (await client.get("/v1/tickets", params={"status": "nope"})).status_code == 422

    @pytest.mark.anyio
    async def test_sort_created_ascending(
        self, client: AsyncClient, ticket_overrides: FakeTicketStore
    ) -> None:
        old = _ticket(created_at=datetime(2026, 1, 1, tzinfo=UTC))
        new = _ticket(created_at=datetime(2026, 6, 1, tzinfo=UTC))
        ticket_overrides.tickets = [old, new]
        asc = await client.get("/v1/tickets", params={"sort": "created_at"})
        assert [i["id"] for i in asc.json()["items"]] == [str(old.id), str(new.id)]
        desc = await client.get("/v1/tickets", params={"sort": "-created_at"})
        assert [i["id"] for i in desc.json()["items"]] == [str(new.id), str(old.id)]


class TestSqlAlchemyTicketStore:
    @pytest.mark.anyio
    async def test_list_executes_and_returns_scalars(self) -> None:
        tickets = [_ticket(analyses=1)]
        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = tickets
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyTicketStore(session)
        got = await store.list_for_org(ORG, limit=10, offset=0)
        assert list(got) == tickets
        session.execute.assert_awaited_once()

    @pytest.mark.anyio
    async def test_count_returns_scalar(self) -> None:
        session = MagicMock()
        result = MagicMock()
        result.scalar_one.return_value = 7
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyTicketStore(session)
        count = await store.count_for_org(
            ORG, category=TicketCategory.BILLING, priority=TicketPriority.HIGH
        )
        assert count == 7

    @pytest.mark.anyio
    async def test_get_returns_first(self) -> None:
        ticket = _ticket(analyses=1)
        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.first.return_value = ticket
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyTicketStore(session)
        assert await store.get_for_org(ORG, ticket.id) is ticket


class TestTicketRoundTrip:
    @pytest.mark.anyio
    @pytest.mark.skipif(not DB_URL, reason="DATABASE_URL not set; skipping DB integration test")
    async def test_list_and_get_against_db(self) -> None:
        from app.db.base import Base
        from app.db.repositories import add_analysis, get_or_create_ticket
        from app.db.session import create_db_engine, create_sessionmaker
        from app.models import TicketAnalysis

        assert DB_URL is not None  # guaranteed by skipif
        engine = create_db_engine(DB_URL)
        sessionmaker = create_sessionmaker(engine)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with sessionmaker() as session:
                from app.db.models import Organization

                org = Organization(name="Acme", slug="acme-tickets")
                session.add(org)
                await session.flush()
                ticket = await get_or_create_ticket(
                    session, raw_text="hi", text_hash="h1", organization_id=org.id
                )
                await add_analysis(
                    session,
                    ticket=ticket,
                    analysis=TicketAnalysis(
                        summary="s",
                        category=TicketCategory.BILLING,
                        priority=TicketPriority.HIGH,
                        next_actions=["x"],
                    ),
                )
                await session.commit()
                org_id, ticket_id = org.id, ticket.id

            async with sessionmaker() as session:
                store = SqlAlchemyTicketStore(session)
                listed = await store.list_for_org(org_id, limit=10, offset=0)
                assert [t.id for t in listed] == [ticket_id]
                loaded = await store.get_for_org(org_id, ticket_id)
                assert loaded is not None and len(loaded.analyses) == 1
                assert loaded.status == "open"  # server_default backfill/default
        finally:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            await engine.dispose()
