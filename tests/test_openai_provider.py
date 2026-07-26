"""
Tests for the OpenAI provider implementation (Milestone M0.5).

Verifies structured-output handling (success, refusal, unparseable), retry
behavior driven by ``openai_max_retries``, and — importantly — translation of
OpenAI-specific exceptions into the provider-agnostic ``Provider*`` errors so
business logic never depends on the OpenAI SDK.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from app.ai.base import (
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from app.ai.config import ProviderConfig
from app.ai.openai_provider import OpenAIProvider
from app.models import TicketAnalysis, TicketCategory, TicketPriority
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError


def _config(**overrides: Any) -> ProviderConfig:
    """Build a ProviderConfig for the OpenAI provider."""
    base: dict[str, Any] = {
        "provider": "openai",
        "model": "gpt-4o-test",
        "api_key": "sk-test-dummy",
    }
    base.update(overrides)
    return ProviderConfig(**base)


def _analysis() -> TicketAnalysis:
    return TicketAnalysis(
        summary="Customer cannot log in.",
        category=TicketCategory.ACCOUNT_ACCESS,
        priority=TicketPriority.HIGH,
        next_actions=["Reset password"],
    )


def _completion(
    refusal: str | None = None,
    parsed: TicketAnalysis | None = None,
    usage: object | None = None,
) -> MagicMock:
    """Build a mock OpenAI completion with one choice/message."""
    message = MagicMock()
    message.refusal = refusal
    message.parsed = parsed
    choice = MagicMock()
    choice.message = message
    completion = MagicMock()
    completion.choices = [choice]
    completion.usage = usage
    return completion


def _provider_with_parse(parse_mock: AsyncMock, **config_overrides: Any) -> OpenAIProvider:
    """Build an OpenAIProvider with its client's ``parse`` stubbed out."""
    provider = OpenAIProvider(_config(**config_overrides))
    client = MagicMock()
    client.beta.chat.completions.parse = parse_mock
    provider._client = client  # inject mock so no real network/client is created
    return provider


def _http_response(status: int) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )


# ---------------------------------------------------------------------------
# Structured-output handling
# ---------------------------------------------------------------------------


class TestStructuredOutput:
    @pytest.mark.anyio
    async def test_success_returns_parsed_analysis(self) -> None:
        analysis = _analysis()
        provider = _provider_with_parse(AsyncMock(return_value=_completion(parsed=analysis)))
        result = await provider.analyze("My account is locked.")
        assert result.analysis is analysis
        assert result.usage is None  # no usage on this completion
        assert result.prompt_version == "v1"  # M5.1: default prompt version recorded

    @pytest.mark.anyio
    async def test_usage_is_captured(self) -> None:
        analysis = _analysis()
        usage = MagicMock(prompt_tokens=11, completion_tokens=7, total_tokens=18)
        provider = _provider_with_parse(
            AsyncMock(return_value=_completion(parsed=analysis, usage=usage))
        )
        result = await provider.analyze("My account is locked.")
        assert result.usage is not None
        assert result.usage.prompt_tokens == 11
        assert result.usage.completion_tokens == 7
        assert result.usage.total_tokens == 18

    @pytest.mark.anyio
    async def test_malformed_usage_is_ignored(self) -> None:
        analysis = _analysis()
        usage = MagicMock(prompt_tokens="not-an-int", completion_tokens=1, total_tokens=2)
        provider = _provider_with_parse(
            AsyncMock(return_value=_completion(parsed=analysis, usage=usage))
        )
        result = await provider.analyze("My account is locked.")
        assert result.analysis is analysis
        assert result.usage is None  # best-effort: unparseable usage ignored

    @pytest.mark.anyio
    async def test_refusal_raises_response_error(self) -> None:
        provider = _provider_with_parse(
            AsyncMock(return_value=_completion(refusal="I cannot help with that."))
        )
        with pytest.raises(ProviderResponseError):
            await provider.analyze("...")

    @pytest.mark.anyio
    async def test_unparseable_raises_response_error(self) -> None:
        provider = _provider_with_parse(AsyncMock(return_value=_completion(parsed=None)))
        with pytest.raises(ProviderResponseError):
            await provider.analyze("...")


# ---------------------------------------------------------------------------
# Exception translation (OpenAI -> provider-agnostic)
# ---------------------------------------------------------------------------


class TestExceptionTranslation:
    @pytest.mark.anyio
    async def test_timeout_translated(self) -> None:
        provider = _provider_with_parse(
            AsyncMock(side_effect=APITimeoutError(request=None)),  # type: ignore[arg-type]
            max_retries=1,
        )
        with pytest.raises(ProviderTimeoutError):
            await provider.analyze("...")

    @pytest.mark.anyio
    async def test_rate_limit_translated(self) -> None:
        err = RateLimitError("rate limited", response=_http_response(429), body=None)
        provider = _provider_with_parse(AsyncMock(side_effect=err), max_retries=1)
        with pytest.raises(ProviderRateLimitError):
            await provider.analyze("...")

    @pytest.mark.anyio
    async def test_connection_error_translated(self) -> None:
        provider = _provider_with_parse(
            AsyncMock(side_effect=APIConnectionError(request=None)),  # type: ignore[arg-type]
            max_retries=1,
        )
        with pytest.raises(ProviderConnectionError):
            await provider.analyze("...")

    @pytest.mark.anyio
    async def test_api_status_error_translated(self) -> None:
        err = APIStatusError("server error", response=_http_response(500), body=None)
        provider = _provider_with_parse(AsyncMock(side_effect=err), max_retries=1)
        with pytest.raises(ProviderConnectionError):
            await provider.analyze("...")


# ---------------------------------------------------------------------------
# Retry count driven by settings.openai_max_retries
# ---------------------------------------------------------------------------


class TestRetryCount:
    @pytest.mark.anyio
    async def test_single_attempt_when_retries_is_one(self) -> None:
        parse = AsyncMock(side_effect=APIConnectionError(request=None))  # type: ignore[arg-type]
        provider = _provider_with_parse(parse, max_retries=1)
        with pytest.raises(ProviderConnectionError):
            await provider.analyze("...")
        assert parse.call_count == 1

    @pytest.mark.anyio
    async def test_attempts_match_configured_retries(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        # Avoid real backoff delays during the test.
        monkeypatch.setattr("asyncio.sleep", AsyncMock())
        parse = AsyncMock(side_effect=APIConnectionError(request=None))  # type: ignore[arg-type]
        provider = _provider_with_parse(parse, max_retries=3)
        with pytest.raises(ProviderConnectionError):
            await provider.analyze("...")
        assert parse.call_count == 3


class TestAclose:
    """aclose releases the underlying client."""

    @pytest.mark.anyio
    async def test_aclose_closes_client(self) -> None:
        provider = OpenAIProvider(_config())
        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        provider._client = mock_client
        await provider.aclose()
        mock_client.close.assert_awaited_once()
        assert provider._client is None

    @pytest.mark.anyio
    async def test_aclose_without_client_is_noop(self) -> None:
        provider = OpenAIProvider(_config())
        await provider.aclose()  # no client created — must not raise
        assert provider._client is None
