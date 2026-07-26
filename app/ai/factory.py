"""
Provider registry and factory.

The application is provider-agnostic: ``AI_PROVIDER`` selects a backend from the
registry below, and generic ``LLM_*`` settings configure it. Several providers
share the OpenAI-SDK-based :class:`~app.ai.openai_provider.OpenAIProvider`
because they expose OpenAI-compatible APIs (only the ``base_url`` differs).

To add a provider that speaks a *different* API (e.g. Anthropic, Gemini):

1. Implement :class:`~app.ai.base.AnalysisProvider` in a new module, taking a
   :class:`~app.ai.config.ProviderConfig` and translating its backend-specific
   errors into the ``Provider*`` exception hierarchy.
2. Add one :class:`ProviderSpec` entry to ``_PROVIDERS`` below.

No business-logic, API-route, service, or persistence changes are required.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from app.ai.base import AnalysisProvider
from app.ai.config import ProviderConfig
from app.ai.openai_provider import OpenAIProvider
from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderSpec:
    """Registry entry describing how to build and default-configure a provider."""

    factory: Callable[[ProviderConfig], AnalysisProvider]
    default_base_url: str | None = None
    default_model: str | None = None
    requires_api_key: bool = True
    requires_base_url: bool = False


# Registry of provider name -> spec. The OpenAI-SDK provider serves every
# OpenAI-compatible backend; only base_url / key requirements differ.
_PROVIDERS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        OpenAIProvider,
        default_model="gpt-4o-2024-08-06",
    ),
    "groq": ProviderSpec(
        OpenAIProvider,
        default_base_url="https://api.groq.com/openai/v1",
    ),
    "together": ProviderSpec(
        OpenAIProvider,
        default_base_url="https://api.together.xyz/v1",
    ),
    "openrouter": ProviderSpec(
        OpenAIProvider,
        default_base_url="https://openrouter.ai/api/v1",
    ),
    "ollama": ProviderSpec(
        OpenAIProvider,
        default_base_url="http://localhost:11434/v1",
        default_model="llama3.1",
        requires_api_key=False,
    ),
    "openai-compatible": ProviderSpec(
        OpenAIProvider,
        requires_api_key=False,
        requires_base_url=True,
    ),
}


def available_providers() -> list[str]:
    """Return the sorted list of registered provider names."""
    return sorted(_PROVIDERS)


def build_provider_config(settings: Settings) -> ProviderConfig:
    """Resolve a :class:`ProviderConfig` from application settings.

    Applies per-provider defaults (base URL, model) and validates per-provider
    requirements (API key, base URL).

    Raises:
        ValueError: If the provider is unknown or a required value is missing.
    """
    name = settings.ai_provider.lower()
    spec = _PROVIDERS.get(name)
    if spec is None:
        raise ValueError(
            f"Unsupported AI provider {name!r}. Supported providers: "
            f"{', '.join(available_providers())}."
        )

    base_url = settings.llm_base_url or spec.default_base_url
    model = settings.llm_model or spec.default_model

    if not model:
        raise ValueError(f"Provider {name!r} requires a model; set LLM_MODEL.")
    if spec.requires_api_key and not settings.llm_api_key:
        raise ValueError(f"Provider {name!r} requires an API key; set LLM_API_KEY.")
    if spec.requires_base_url and not base_url:
        raise ValueError(f"Provider {name!r} requires a base URL; set LLM_BASE_URL.")

    return ProviderConfig(
        provider=name,
        model=model,
        api_key=settings.llm_api_key,
        base_url=base_url,
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
        temperature=settings.llm_temperature,
        prompt_version=settings.llm_prompt_version,
    )


def build_provider(settings: Settings) -> AnalysisProvider:
    """Construct the configured provider instance.

    Args:
        settings: Application settings (``ai_provider`` selects the backend).

    Returns:
        A new ``AnalysisProvider`` instance.

    Raises:
        ValueError: If the provider is unknown or misconfigured.
    """
    config = build_provider_config(settings)
    spec = _PROVIDERS[config.provider]
    logger.debug(
        "Using AI provider: %s (model=%s, base_url=%s)",
        config.provider,
        config.model,
        config.base_url or "<sdk default>",
    )
    return spec.factory(config)
