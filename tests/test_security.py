"""
Tests for CORS, security headers, and request-id middleware (Milestone M0.4).
"""

import pytest
from httpx import AsyncClient


class TestSecurityHeaders:
    """Security headers should be present on every response."""

    @pytest.mark.anyio
    async def test_security_headers_present(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["referrer-policy"] == "no-referrer"


class TestRequestId:
    """Every response should carry an X-Request-ID."""

    @pytest.mark.anyio
    async def test_request_id_present(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        assert resp.headers.get("x-request-id")

    @pytest.mark.anyio
    async def test_request_id_echoed_when_provided(self, client: AsyncClient) -> None:
        resp = await client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
        assert resp.headers["x-request-id"] == "trace-abc-123"


class TestCORS:
    """CORS must be driven by configured origins (no wildcard-with-credentials)."""

    @pytest.mark.anyio
    async def test_preflight_allowed_origin(self, client: AsyncClient) -> None:
        resp = await client.options(
            "/analyze",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"

    @pytest.mark.anyio
    async def test_preflight_disallowed_origin(self, client: AsyncClient) -> None:
        resp = await client.options(
            "/analyze",
            headers={
                "Origin": "http://evil.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" not in resp.headers
