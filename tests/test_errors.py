"""
Tests for the standardized error envelope and handlers (Milestone M0.4).

Every error response must preserve its HTTP status code and carry the
``{"error": {"code", "message", "request_id"}}`` envelope.
"""

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.ai import AnalysisProvider, ProviderTimeoutError
from app.main import app
from httpx import ASGITransport, AsyncClient

SetProvider = Callable[[AnalysisProvider], None]


def _provider(analyze_mock: AsyncMock) -> MagicMock:
    """Build a mock AnalysisProvider whose ``analyze`` is the given AsyncMock."""
    provider = MagicMock()
    provider.analyze = analyze_mock
    return provider


class TestErrorEnvelope:
    """Error responses share a consistent envelope across status codes."""

    @pytest.mark.anyio
    async def test_validation_error_envelope(self, client: AsyncClient) -> None:
        """A 422 validation error is rendered in the envelope with details."""
        resp = await client.post("/analyze", json={"ticket": ""})
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "validation_error"
        assert body["error"]["message"]
        assert body["error"]["request_id"]
        assert "details" in body["error"]
        # The body request id matches the response header.
        assert resp.headers["x-request-id"] == body["error"]["request_id"]

    @pytest.mark.anyio
    async def test_http_exception_envelope(
        self, client: AsyncClient, override_provider: SetProvider
    ) -> None:
        """A mapped HTTPException (504) keeps its status and uses the envelope."""
        override_provider(_provider(AsyncMock(side_effect=ProviderTimeoutError("timed out"))))
        resp = await client.post("/analyze", json={"ticket": "Help please."})
        assert resp.status_code == 504
        body = resp.json()
        assert body["error"]["code"] == "upstream_timeout"
        assert body["error"]["message"]
        assert body["error"]["request_id"]

    @pytest.mark.anyio
    async def test_unhandled_exception_envelope(self, override_provider: SetProvider) -> None:
        """An unexpected error returns a 500 envelope without leaking internals."""
        override_provider(_provider(AsyncMock(side_effect=RuntimeError("internal boom"))))
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/analyze", json={"ticket": "trigger 500"})
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "internal_error"
        assert body["error"]["message"] == "An internal error occurred."
        assert body["error"]["request_id"]
        # The internal exception message must not leak to the client.
        assert "boom" not in resp.text
