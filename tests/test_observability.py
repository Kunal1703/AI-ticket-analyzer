"""
Tests for observability (Milestone M1.4): structured logging, request-id
correlation, the Prometheus metrics endpoint, and token-usage metrics.
"""

import json
import logging
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.ai import AnalysisProvider, AnalysisResult, TokenUsage
from app.core.logging import (
    JsonFormatter,
    RequestIdFilter,
    _build_handler,
    request_id_var,
    resolve_log_level,
)
from app.models import TicketAnalysis, TicketCategory, TicketPriority
from httpx import AsyncClient

SetProvider = Callable[[AnalysisProvider], None]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class TestLogging:
    def test_resolve_log_level(self) -> None:
        assert resolve_log_level(debug=True, log_level="INFO") == "DEBUG"
        assert resolve_log_level(debug=False, log_level="warning") == "WARNING"

    def test_request_id_filter_injects_contextvar(self) -> None:
        token = request_id_var.set("abc123")
        try:
            record = logging.LogRecord("n", logging.INFO, "p", 1, "msg", None, None)
            assert RequestIdFilter().filter(record) is True
            assert record.request_id == "abc123"  # type: ignore[attr-defined]
        finally:
            request_id_var.reset(token)

    def test_request_id_filter_defaults_to_dash(self) -> None:
        record = logging.LogRecord("n", logging.INFO, "p", 1, "msg", None, None)
        RequestIdFilter().filter(record)
        assert record.request_id == "-"  # type: ignore[attr-defined]

    def test_json_formatter_emits_structured_line(self) -> None:
        record = logging.LogRecord("svc", logging.INFO, "p", 1, "hello", None, None)
        record.request_id = "rid-1"
        data = json.loads(JsonFormatter().format(record))
        assert data["message"] == "hello"
        assert data["level"] == "INFO"
        assert data["logger"] == "svc"
        assert data["request_id"] == "rid-1"

    def test_build_handler_formatter_selection(self) -> None:
        assert isinstance(_build_handler("json").formatter, JsonFormatter)
        json_fmt = _build_handler("text").formatter
        assert json_fmt is not None
        assert not isinstance(json_fmt, JsonFormatter)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _provider_with_usage() -> MagicMock:
    analysis = TicketAnalysis(
        summary="Customer charged twice.",
        category=TicketCategory.BILLING,
        priority=TicketPriority.LOW,
        next_actions=["Verify payment"],
    )
    provider = MagicMock()
    provider.name = "metrics-test"
    provider.model = "metrics-model"
    provider.analyze = AsyncMock(
        return_value=AnalysisResult(
            analysis=analysis,
            usage=TokenUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        )
    )
    return provider


class TestMetrics:
    @pytest.mark.anyio
    async def test_metrics_endpoint_exposes_prometheus(self, client: AsyncClient) -> None:
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        assert "http_requests_total" in resp.text

    @pytest.mark.anyio
    async def test_analysis_and_token_metrics_recorded(
        self, client: AsyncClient, override_provider: SetProvider
    ) -> None:
        override_provider(_provider_with_usage())
        resp = await client.post("/analyze", json={"ticket": "metrics please"})
        assert resp.status_code == 200

        metrics_text = (await client.get("/metrics")).text
        assert "ticket_analyses_total" in metrics_text
        assert "llm_tokens_total" in metrics_text
        assert 'provider="metrics-test"' in metrics_text
