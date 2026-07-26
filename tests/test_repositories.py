"""
Tests for the ticket/analysis repository helpers (Milestone M1.2).

Query logic is unit-tested with a mocked ``AsyncSession``. A real round-trip
(including analysis versioning) is covered by an integration test that is
skipped unless ``DATABASE_URL`` is set.
"""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.db import repositories
from app.db.base import Base
from app.db.models import Analysis, Ticket
from app.db.session import create_db_engine, create_sessionmaker
from app.models import TicketAnalysis, TicketCategory, TicketPriority
from sqlalchemy import select

DB_URL = os.environ.get("DATABASE_URL")


def _analysis() -> TicketAnalysis:
    return TicketAnalysis(
        summary="Customer cannot log in.",
        category=TicketCategory.BILLING,
        priority=TicketPriority.HIGH,
        next_actions=["Reset password"],
    )


@pytest.mark.anyio
async def test_get_or_create_creates_when_missing() -> None:
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.flush = AsyncMock()

    ticket = await repositories.get_or_create_ticket(session, raw_text="x", text_hash="h")

    assert isinstance(ticket, Ticket)
    session.add.assert_called_once()
    session.flush.assert_awaited_once()


@pytest.mark.anyio
async def test_get_or_create_sets_organization_id() -> None:
    org_id = uuid.uuid4()
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.flush = AsyncMock()

    ticket = await repositories.get_or_create_ticket(
        session, raw_text="x", text_hash="h", organization_id=org_id
    )
    assert ticket.organization_id == org_id


@pytest.mark.anyio
async def test_add_analysis_inherits_ticket_org() -> None:
    org_id = uuid.uuid4()
    ticket = Ticket(raw_text="x", text_hash="h", organization_id=org_id)
    ticket.id = uuid.uuid4()
    session = MagicMock()
    session.add = MagicMock()
    row = await repositories.add_analysis(session, ticket=ticket, analysis=_analysis())
    assert row.organization_id == org_id


@pytest.mark.anyio
async def test_get_or_create_returns_existing() -> None:
    existing = Ticket(raw_text="x", text_hash="h")
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = existing
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()

    ticket = await repositories.get_or_create_ticket(session, raw_text="x", text_hash="h")

    assert ticket is existing
    session.add.assert_not_called()


@pytest.mark.anyio
async def test_add_analysis_builds_row() -> None:
    session = MagicMock()
    session.add = MagicMock()
    ticket = Ticket(raw_text="x", text_hash="h")
    ticket.id = uuid.uuid4()

    row = await repositories.add_analysis(
        session,
        ticket=ticket,
        analysis=_analysis(),
        model="m",
        prompt_version="v1",
        token_usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    )

    assert row.ticket_id == ticket.id
    assert row.category == "Billing"
    assert row.priority == "High"
    assert row.next_actions == ["Reset password"]
    assert row.model == "m"
    assert row.prompt_version == "v1"  # M5.1
    assert row.token_usage == {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}
    session.add.assert_called_once()


@pytest.mark.anyio
@pytest.mark.skipif(not DB_URL, reason="DATABASE_URL not set; skipping DB integration test")
async def test_versioning_reuses_ticket() -> None:
    """Two analyses of the same text reuse one ticket (versioned analyses)."""
    assert DB_URL is not None  # guaranteed by skipif
    engine = create_db_engine(DB_URL)
    sessionmaker = create_sessionmaker(engine)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with sessionmaker() as session:
            t1 = await repositories.get_or_create_ticket(session, raw_text="hi", text_hash="hh")
            await repositories.add_analysis(session, ticket=t1, analysis=_analysis())
            await session.commit()

        async with sessionmaker() as session:
            t2 = await repositories.get_or_create_ticket(session, raw_text="hi", text_hash="hh")
            await repositories.add_analysis(session, ticket=t2, analysis=_analysis())
            await session.commit()
            assert t1.id == t2.id

        async with sessionmaker() as session:
            rows = (
                (await session.execute(select(Analysis).where(Analysis.ticket_id == t1.id)))
                .scalars()
                .all()
            )
            assert len(rows) == 2
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()
