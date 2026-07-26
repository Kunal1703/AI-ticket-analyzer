"""
Tests for the AI provider abstraction: interface, factory, and registry.

These verify that providers are resolved through the abstraction so new
backends can be added without changing business logic.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.ai import AnalysisProvider, AnalysisResult, build_provider
from app.ai.factory import build_provider_config
from app.ai.openai_provider import OpenAIProvider
from app.config import Settings
from app.models import TicketAnalysis, TicketCategory, TicketPriority


def _settings(**overrides: object) -> Settings:
    """Build Settings without reading the local .env file."""
    base: dict[str, object] = {"llm_api_key": "sk-test-dummy"}
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type, call-arg]


class TestProviderFactory:
    """The factory resolves the configured provider via the registry."""

    def test_default_provider_is_openai(self) -> None:
        provider = build_provider(_settings())
        assert isinstance(provider, OpenAIProvider)
        assert isinstance(provider, AnalysisProvider)

    def test_provider_name_is_case_insensitive(self) -> None:
        provider = build_provider(_settings(ai_provider="OpenAI"))
        assert isinstance(provider, OpenAIProvider)

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported AI provider"):
            build_provider(_settings(ai_provider="does-not-exist"))

    def test_openai_compatible_provider_builds_and_exposes_metadata(self) -> None:
        provider = build_provider(_settings(ai_provider="groq", llm_model="llama-3.1-70b"))
        assert isinstance(provider, OpenAIProvider)
        assert provider.name == "groq"
        assert provider.model == "llama-3.1-70b"


class TestProviderConfigResolution:
    """build_provider_config applies per-provider defaults and validation."""

    def test_openai_env_alias_populates_llm_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Backward-compatibility: the OPENAI_API_KEY env var maps to llm_api_key.
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "from-openai-env")
        assert Settings(_env_file=None).llm_api_key == "from-openai-env"  # type: ignore[call-arg]

    def test_compatible_provider_default_base_url(self) -> None:
        config = build_provider_config(_settings(ai_provider="groq", llm_model="m"))
        assert config.base_url == "https://api.groq.com/openai/v1"
        assert config.model == "m"

    def test_explicit_base_url_overrides_default(self) -> None:
        config = build_provider_config(
            _settings(ai_provider="together", llm_model="m", llm_base_url="http://custom/v1")
        )
        assert config.base_url == "http://custom/v1"

    def test_ollama_needs_no_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        config = build_provider_config(
            Settings(_env_file=None, ai_provider="ollama")  # type: ignore[call-arg]
        )
        assert config.api_key is None
        assert config.base_url == "http://localhost:11434/v1"
        assert config.model == "llama3.1"

    def test_openai_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        with pytest.raises(ValueError, match="requires an API key"):
            build_provider_config(Settings(_env_file=None, ai_provider="openai"))  # type: ignore[call-arg]

    def test_openai_compatible_requires_base_url(self) -> None:
        with pytest.raises(ValueError, match="requires a base URL"):
            build_provider_config(_settings(ai_provider="openai-compatible", llm_model="m"))

    def test_provider_without_default_model_requires_model(self) -> None:
        with pytest.raises(ValueError, match="requires a model"):
            build_provider_config(_settings(ai_provider="groq"))


class TestLegacyFacade:
    """The app.openai_client shim remains a working, provider-agnostic entry point."""

    @pytest.mark.anyio
    async def test_analyze_ticket_delegates_to_provider(self) -> None:
        from app import openai_client

        analysis = TicketAnalysis(
            summary="Customer cannot log in.",
            category=TicketCategory.ACCOUNT_ACCESS,
            priority=TicketPriority.HIGH,
            next_actions=["Reset password"],
        )
        fake_provider = MagicMock()
        fake_provider.analyze = AsyncMock(return_value=AnalysisResult(analysis=analysis))
        with patch("app.openai_client.build_provider", return_value=fake_provider):
            result = await openai_client.analyze_ticket("My account is locked.")
        assert result is analysis
