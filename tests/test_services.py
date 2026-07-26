"""
Tests for the analysis persistence service (Milestone M1.2).

The service is best-effort: it must be a no-op without a database and must
swallow errors so the API response is never affected.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.models import TicketAnalysis, TicketCategory, TicketPriority
from app.services import analysis_service
from app.services.analysis_service import persist_analysis


def _analysis() -> TicketAnalysis:
    return TicketAnalysis(
        summary="Customer cannot log in.",
        category=TicketCategory.BILLING,
        priority=TicketPriority.HIGH,
        next_actions=["Reset password"],
    )


class _FakeSession:
    """Minimal async-context-manager session stand-in."""

    def __init__(self) -> None:
        self.committed = False

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.anyio
async def test_persist_is_noop_without_sessionmaker() -> None:
    """No database configured -> no-op, no error."""
    await persist_analysis(None, ticket_text="t", text_hash="h", analysis=_analysis())


@pytest.mark.anyio
async def test_persist_swallows_errors() -> None:
    """A failing session factory must not raise."""
    failing = MagicMock(side_effect=RuntimeError("db down"))
    await persist_analysis(failing, ticket_text="t", text_hash="h", analysis=_analysis())


@pytest.mark.anyio
async def test_persist_success_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    """On the happy path, the ticket+analysis are written and committed."""
    session = _FakeSession()
    sessionmaker = MagicMock(return_value=session)

    get_or_create = AsyncMock(return_value=MagicMock())
    add_analysis = AsyncMock()
    monkeypatch.setattr(analysis_service.repositories, "get_or_create_ticket", get_or_create)
    monkeypatch.setattr(analysis_service.repositories, "add_analysis", add_analysis)

    await persist_analysis(
        sessionmaker, ticket_text="t", text_hash="h", analysis=_analysis(), model="m"
    )

    get_or_create.assert_awaited_once()
    add_analysis.assert_awaited_once()
    assert session.committed is True
