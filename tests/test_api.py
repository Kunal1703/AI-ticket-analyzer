"""
Integration tests for the FastAPI application.

Uses httpx's AsyncClient and overrides the AI provider dependency to isolate
the API layer.
"""

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.ai import (
    AnalysisProvider,
    AnalysisResult,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from app.models import TicketAnalysis, TicketCategory, TicketPriority
from httpx import AsyncClient

# Type alias for the override_provider fixture.
SetProvider = Callable[[AnalysisProvider], None]

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_analysis() -> TicketAnalysis:
    """Return a mock TicketAnalysis for testing."""
    return TicketAnalysis(
        summary="Customer upgraded but still on free plan with double charge.",
        category=TicketCategory.BILLING,
        priority=TicketPriority.HIGH,
        next_actions=[
            "Verify payment records",
            "Check account subscription status",
            "Issue refund if duplicate charge confirmed",
        ],
    )


def _provider(analyze_mock: AsyncMock) -> MagicMock:
    """Build a mock AnalysisProvider whose ``analyze`` is the given AsyncMock."""
    provider = MagicMock()
    provider.name = "test"
    provider.model = "test-model"
    provider.analyze = analyze_mock
    return provider


def _ok(analysis: TicketAnalysis) -> AsyncMock:
    """An ``analyze`` mock that succeeds with the given analysis."""
    return AsyncMock(return_value=AnalysisResult(analysis=analysis))


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """Tests for GET /health."""

    @pytest.mark.anyio
    async def test_health_returns_200(self, client: AsyncClient) -> None:
        """Health check should return 200 with status and version."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "version" in data


# ---------------------------------------------------------------------------
# Analyze endpoint
# ---------------------------------------------------------------------------


class TestAnalyzeEndpoint:
    """Tests for POST /analyze."""

    @pytest.mark.anyio
    async def test_analyze_success(
        self,
        client: AsyncClient,
        override_provider: SetProvider,
        mock_analysis: TicketAnalysis,
    ) -> None:
        """Valid ticket should return a structured analysis (mocked provider)."""
        override_provider(_provider(_ok(mock_analysis)))
        resp = await client.post(
            "/analyze",
            json={"ticket": "I was charged twice after upgrading."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "Billing"
        assert data["priority"] == "High"
        assert len(data["next_actions"]) >= 1
        assert "summary" in data

    @pytest.mark.anyio
    async def test_analyze_empty_ticket(self, client: AsyncClient) -> None:
        """Empty ticket string should return 422 validation error."""
        resp = await client.post("/analyze", json={"ticket": ""})
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_analyze_missing_ticket(self, client: AsyncClient) -> None:
        """Request without 'ticket' field should return 422."""
        resp = await client.post("/analyze", json={})
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_analyze_invalid_body(self, client: AsyncClient) -> None:
        """Non-JSON body should return 422."""
        resp = await client.post(
            "/analyze",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_analyze_provider_timeout(
        self, client: AsyncClient, override_provider: SetProvider
    ) -> None:
        """A provider timeout should return 504."""
        override_provider(_provider(AsyncMock(side_effect=ProviderTimeoutError("timed out"))))
        resp = await client.post("/analyze", json={"ticket": "Help me please."})
        assert resp.status_code == 504

    @pytest.mark.anyio
    async def test_analyze_provider_connection_error(
        self, client: AsyncClient, override_provider: SetProvider
    ) -> None:
        """A provider connection failure should return 502."""
        override_provider(_provider(AsyncMock(side_effect=ProviderConnectionError("no route"))))
        resp = await client.post("/analyze", json={"ticket": "Help me please."})
        assert resp.status_code == 502

    @pytest.mark.anyio
    async def test_analyze_provider_rate_limit(
        self, client: AsyncClient, override_provider: SetProvider
    ) -> None:
        """A provider rate-limit error should return 429."""
        override_provider(_provider(AsyncMock(side_effect=ProviderRateLimitError("slow down"))))
        resp = await client.post("/analyze", json={"ticket": "Help me please."})
        assert resp.status_code == 429

    @pytest.mark.anyio
    async def test_analyze_provider_response_error(
        self, client: AsyncClient, override_provider: SetProvider
    ) -> None:
        """An invalid/refused AI response should return 502."""
        override_provider(_provider(AsyncMock(side_effect=ProviderResponseError("refused"))))
        resp = await client.post("/analyze", json={"ticket": "Help me please."})
        assert resp.status_code == 502

    @pytest.mark.anyio
    async def test_response_contains_timing_header(
        self,
        client: AsyncClient,
        override_provider: SetProvider,
        mock_analysis: TicketAnalysis,
    ) -> None:
        """Response should include X-Process-Time-Ms header."""
        override_provider(_provider(_ok(mock_analysis)))
        resp = await client.post("/analyze", json={"ticket": "I need help."})
        assert "x-process-time-ms" in resp.headers

    @pytest.mark.anyio
    async def test_caching(
        self,
        client: AsyncClient,
        override_provider: SetProvider,
        mock_analysis: TicketAnalysis,
    ) -> None:
        """Identical tickets should be served from cache on second call."""
        analyze_mock = _ok(mock_analysis)
        override_provider(_provider(analyze_mock))
        # First call — cache miss
        resp1 = await client.post("/analyze", json={"ticket": "Caching test ticket."})
        # Second call — should come from cache
        resp2 = await client.post("/analyze", json={"ticket": "Caching test ticket."})
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # The provider should only have been called once.
        assert analyze_mock.call_count == 1
