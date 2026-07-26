"""
App-level persistence behavior (Milestone M1.2).

Verifies that persistence is invisible when disabled and that a persistence
failure never affects the API response.
"""

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.ai import AnalysisProvider, AnalysisResult
from app.models import TicketAnalysis, TicketCategory, TicketPriority
from httpx import AsyncClient

SetProvider = Callable[[AnalysisProvider], None]
SetSessionmaker = Callable[[object], None]


def _analysis() -> TicketAnalysis:
    return TicketAnalysis(
        summary="Customer charged twice.",
        category=TicketCategory.BILLING,
        priority=TicketPriority.HIGH,
        next_actions=["Verify payment"],
    )


def _provider(analysis: TicketAnalysis) -> MagicMock:
    provider = MagicMock()
    provider.name = "test"
    provider.model = "test-model"
    provider.analyze = AsyncMock(return_value=AnalysisResult(analysis=analysis))
    return provider


class TestPersistenceBehavior:
    @pytest.mark.anyio
    async def test_default_app_has_no_persistence(self) -> None:
        """Without DATABASE_URL the app exposes no session factory."""
        from app.main import app

        assert app.state.db_sessionmaker is None
        assert app.state.db_engine is None

    @pytest.mark.anyio
    async def test_persistence_failure_does_not_break_response(
        self,
        client: AsyncClient,
        override_provider: SetProvider,
        override_db_sessionmaker: SetSessionmaker,
    ) -> None:
        """A failing session factory must not affect the 200 response."""
        override_provider(_provider(_analysis()))
        failing_sessionmaker = MagicMock(side_effect=RuntimeError("db down"))
        override_db_sessionmaker(failing_sessionmaker)

        resp = await client.post("/analyze", json={"ticket": "I was charged twice."})

        assert resp.status_code == 200
        assert resp.json()["category"] == "Billing"
        # The failing factory was actually invoked (best-effort path executed).
        failing_sessionmaker.assert_called_once()
