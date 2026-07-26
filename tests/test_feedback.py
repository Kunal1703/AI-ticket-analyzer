"""
Tests for M3.2: feedback capture (POST/GET /v1/tickets/{id}/feedback) and
re-analyze (POST /v1/tickets/{id}/reanalyze).

Routes are exercised with in-memory fakes and an overridden tenant context; the
SQLAlchemy feedback store is unit-tested with a mocked session.
"""

import uuid
from collections.abc import Generator, Sequence
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.ai import AnalysisResult
from app.db.feedback_store import SqlAlchemyFeedbackStore
from app.db.models import Feedback
from app.models import TicketAnalysis, TicketCategory, TicketPriority
from app.tenancy.base import TenantContext
from httpx import AsyncClient

from tests.test_tickets import ORG, FakeTicketStore, _ticket


class FakeFeedbackStore:
    """In-memory ``FeedbackStore``."""

    def __init__(self) -> None:
        self.items: list[Feedback] = []

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
    ) -> Feedback:
        feedback = Feedback(
            organization_id=organization_id,
            ticket_id=ticket_id,
            analysis_id=analysis_id,
            rating=rating,
            corrected_category=corrected_category,
            corrected_priority=corrected_priority,
            comment=comment,
        )
        feedback.id = uuid.uuid4()
        feedback.created_at = datetime.now(UTC)
        self.items.append(feedback)
        return feedback

    async def list_for_ticket(
        self, organization_id: uuid.UUID, ticket_id: uuid.UUID
    ) -> Sequence[Feedback]:
        return [
            f
            for f in self.items
            if f.organization_id == organization_id and f.ticket_id == ticket_id
        ]


def _mock_provider() -> MagicMock:
    provider = MagicMock()
    provider.name = "test"
    provider.model = "test-model"
    provider.analyze = AsyncMock(
        return_value=AnalysisResult(
            analysis=TicketAnalysis(
                summary="fresh",
                category=TicketCategory.REFUND,
                priority=TicketPriority.LOW,
                next_actions=["Refund"],
            )
        )
    )
    return provider


@pytest.fixture
def feedback_overrides() -> Generator[dict[str, Any], None, None]:
    from app.dependencies import (
        get_analysis_provider,
        get_cache,
        get_feedback_store,
        get_ticket_store,
        require_quota,
    )
    from app.main import app
    from app.tickets.routes import get_tenant_context

    tickets = FakeTicketStore()
    feedback = FakeFeedbackStore()
    provider = _mock_provider()
    context = TenantContext(organization_id=ORG, principal_type="api_key", scopes=("analyze",))

    app.dependency_overrides[get_ticket_store] = lambda: tickets
    app.dependency_overrides[get_feedback_store] = lambda: feedback
    app.dependency_overrides[get_tenant_context] = lambda: context
    app.dependency_overrides[require_quota] = lambda: context
    app.dependency_overrides[get_analysis_provider] = lambda: provider
    from app.cache.memory import TTLCache

    app.dependency_overrides[get_cache] = lambda: TTLCache(ttl_seconds=300)
    yield {"tickets": tickets, "feedback": feedback, "provider": provider}
    for dep in (
        get_ticket_store,
        get_feedback_store,
        get_tenant_context,
        require_quota,
        get_analysis_provider,
        get_cache,
    ):
        app.dependency_overrides.pop(dep, None)


class TestFeedback:
    @pytest.mark.anyio
    async def test_create_defaults_to_latest_analysis(
        self, client: AsyncClient, feedback_overrides: dict[str, Any]
    ) -> None:
        ticket = _ticket(analyses=2)
        feedback_overrides["tickets"].tickets = [ticket]
        latest_id = str(max(ticket.analyses, key=lambda a: a.created_at).id)

        resp = await client.post(
            f"/v1/tickets/{ticket.id}/feedback",
            json={"rating": "negative", "corrected_category": "Refund", "comment": "wrong"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["rating"] == "negative"
        assert body["corrected_category"] == "Refund"
        assert body["analysis_id"] == latest_id
        assert len(feedback_overrides["feedback"].items) == 1

    @pytest.mark.anyio
    async def test_create_with_explicit_analysis_id(
        self, client: AsyncClient, feedback_overrides: dict[str, Any]
    ) -> None:
        ticket = _ticket(analyses=3)
        feedback_overrides["tickets"].tickets = [ticket]
        target = str(ticket.analyses[0].id)  # an older version
        resp = await client.post(
            f"/v1/tickets/{ticket.id}/feedback",
            json={"rating": "positive", "analysis_id": target},
        )
        assert resp.status_code == 201
        assert resp.json()["analysis_id"] == target

    @pytest.mark.anyio
    async def test_unknown_analysis_id_404(
        self, client: AsyncClient, feedback_overrides: dict[str, Any]
    ) -> None:
        ticket = _ticket(analyses=1)
        feedback_overrides["tickets"].tickets = [ticket]
        resp = await client.post(
            f"/v1/tickets/{ticket.id}/feedback",
            json={"rating": "positive", "analysis_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_malformed_analysis_id_400(
        self, client: AsyncClient, feedback_overrides: dict[str, Any]
    ) -> None:
        ticket = _ticket(analyses=1)
        feedback_overrides["tickets"].tickets = [ticket]
        resp = await client.post(
            f"/v1/tickets/{ticket.id}/feedback",
            json={"rating": "positive", "analysis_id": "not-a-uuid"},
        )
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_ticket_without_analysis_404(
        self, client: AsyncClient, feedback_overrides: dict[str, Any]
    ) -> None:
        ticket = _ticket(analyses=0)
        feedback_overrides["tickets"].tickets = [ticket]
        resp = await client.post(f"/v1/tickets/{ticket.id}/feedback", json={"rating": "positive"})
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_list_feedback_unknown_ticket_404(
        self, client: AsyncClient, feedback_overrides: dict[str, Any]
    ) -> None:
        resp = await client.get(f"/v1/tickets/{uuid.uuid4()}/feedback")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_invalid_rating_422(
        self, client: AsyncClient, feedback_overrides: dict[str, Any]
    ) -> None:
        ticket = _ticket(analyses=1)
        feedback_overrides["tickets"].tickets = [ticket]
        resp = await client.post(f"/v1/tickets/{ticket.id}/feedback", json={"rating": "meh"})
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_feedback_on_unknown_ticket_404(
        self, client: AsyncClient, feedback_overrides: dict[str, Any]
    ) -> None:
        resp = await client.post(
            f"/v1/tickets/{uuid.uuid4()}/feedback", json={"rating": "positive"}
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_list_feedback(
        self, client: AsyncClient, feedback_overrides: dict[str, Any]
    ) -> None:
        ticket = _ticket(analyses=1)
        feedback_overrides["tickets"].tickets = [ticket]
        await client.post(f"/v1/tickets/{ticket.id}/feedback", json={"rating": "positive"})
        resp = await client.get(f"/v1/tickets/{ticket.id}/feedback")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestReanalyze:
    @pytest.mark.anyio
    async def test_reanalyze_returns_fresh_analysis(
        self, client: AsyncClient, feedback_overrides: dict[str, Any]
    ) -> None:
        ticket = _ticket(analyses=1)
        feedback_overrides["tickets"].tickets = [ticket]
        resp = await client.post(f"/v1/tickets/{ticket.id}/reanalyze")
        assert resp.status_code == 200
        # The mock provider returns a fresh Refund/Low analysis, not the ticket's
        # existing Billing/High one, proving the cache was bypassed.
        assert resp.json()["category"] == "Refund"
        # M3.6: reanalyze returns the (already-known) ticket_id for deep-linking.
        assert resp.json()["ticket_id"] == str(ticket.id)
        feedback_overrides["provider"].analyze.assert_awaited_once()

    @pytest.mark.anyio
    async def test_reanalyze_unknown_ticket_404(
        self, client: AsyncClient, feedback_overrides: dict[str, Any]
    ) -> None:
        resp = await client.post(f"/v1/tickets/{uuid.uuid4()}/reanalyze")
        assert resp.status_code == 404


class TestSqlAlchemyFeedbackStore:
    @pytest.mark.anyio
    async def test_create_adds_flushes_refreshes(self) -> None:
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.refresh = AsyncMock()
        store = SqlAlchemyFeedbackStore(session)
        fb = await store.create(
            organization_id=ORG,
            ticket_id=uuid.uuid4(),
            analysis_id=uuid.uuid4(),
            rating="positive",
            corrected_category=None,
            corrected_priority=None,
            comment="nice",
        )
        assert fb.rating == "positive"
        session.add.assert_called_once()
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once()

    @pytest.mark.anyio
    async def test_list_for_ticket_returns_scalars(self) -> None:
        rows = [Feedback(rating="positive")]
        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyFeedbackStore(session)
        got = await store.list_for_ticket(ORG, uuid.uuid4())
        assert list(got) == rows


class TestFeedbackSchema:
    def test_table_registered(self) -> None:
        from app.db.base import Base

        assert "feedback" in Base.metadata.tables

    def test_organization_id_not_nullable(self) -> None:
        assert Feedback.__table__.columns["organization_id"].nullable is False
