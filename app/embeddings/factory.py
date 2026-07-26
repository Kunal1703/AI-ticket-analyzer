"""
Embedding-provider registry and factory (M5.2).

``EMBEDDING_PROVIDER`` selects a backend from the registry below, and generic
``EMBEDDING_*`` settings configure it. Several providers share the OpenAI-SDK
:class:`~app.embeddings.openai_provider.OpenAIEmbeddingProvider` (only the
``base_url`` differs); the keyless ``hash`` provider is deterministic and needs
no infra, so RAG runs fully offline.

To add a provider that speaks a different API: implement
:class:`~app.embeddings.base.EmbeddingProvider`, translating its errors into the
``Embedding*`` hierarchy, and add one :class:`EmbeddingProviderSpec` entry.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from app.config import Settings
from app.embeddings.base import EmbeddingProvider
from app.embeddings.config import EmbeddingConfig
from app.embeddings.hash_provider import HashEmbeddingProvider
from app.embeddings.openai_provider import OpenAIEmbeddingProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingProviderSpec:
    """Registry entry describing how to build and default-configure a provider."""

    factory: Callable[[EmbeddingConfig], EmbeddingProvider]
    default_base_url: str | None = None
    default_model: str | None = None
    requires_api_key: bool = True
    requires_base_url: bool = False


# Registry of provider name -> spec. The OpenAI-SDK provider serves every
# OpenAI-compatible embeddings backend; "hash" is a keyless local fallback.
_EMBEDDING_PROVIDERS: dict[str, EmbeddingProviderSpec] = {
    "openai": EmbeddingProviderSpec(
        OpenAIEmbeddingProvider,
        default_model="text-embedding-3-small",
    ),
    "ollama": EmbeddingProviderSpec(
        OpenAIEmbeddingProvider,
        default_base_url="http://localhost:11434/v1",
        default_model="nomic-embed-text",
        requires_api_key=False,
    ),
    "openai-compatible": EmbeddingProviderSpec(
        OpenAIEmbeddingProvider,
        requires_api_key=False,
        requires_base_url=True,
    ),
    "hash": EmbeddingProviderSpec(
        HashEmbeddingProvider,
        default_model="hash",
        requires_api_key=False,
    ),
}


def available_embedding_providers() -> list[str]:
    """Return the sorted list of registered embedding-provider names."""
    return sorted(_EMBEDDING_PROVIDERS)


def build_embedding_config(settings: Settings) -> EmbeddingConfig:
    """Resolve an :class:`EmbeddingConfig` from application settings.

    The API key falls back to ``llm_api_key`` (embeddings usually share the LLM
    account); base URL/model use ``embedding_*`` settings or per-provider
    defaults. Validates per-provider requirements.

    Raises:
        ValueError: If the provider is unknown or a required value is missing.
    """
    name = settings.embedding_provider.lower()
    spec = _EMBEDDING_PROVIDERS.get(name)
    if spec is None:
        raise ValueError(
            f"Unsupported embedding provider {name!r}. Supported providers: "
            f"{', '.join(available_embedding_providers())}."
        )

    api_key = settings.embedding_api_key or settings.llm_api_key
    base_url = settings.embedding_base_url or spec.default_base_url
    model = settings.embedding_model or spec.default_model

    if not model:
        raise ValueError(f"Embedding provider {name!r} requires a model; set EMBEDDING_MODEL.")
    if spec.requires_api_key and not api_key:
        raise ValueError(f"Embedding provider {name!r} requires an API key; set EMBEDDING_API_KEY.")
    if spec.requires_base_url and not base_url:
        raise ValueError(
            f"Embedding provider {name!r} requires a base URL; set EMBEDDING_BASE_URL."
        )

    return EmbeddingConfig(
        provider=name,
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=settings.embedding_timeout,
        max_retries=settings.embedding_max_retries,
        dimensions=settings.embedding_dimensions,
    )


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Construct the configured embedding-provider instance.

    Raises:
        ValueError: If the provider is unknown or misconfigured.
    """
    config = build_embedding_config(settings)
    spec = _EMBEDDING_PROVIDERS[config.provider]
    logger.debug(
        "Using embedding provider: %s (model=%s, base_url=%s)",
        config.provider,
        config.model,
        config.base_url or "<sdk default>",
    )
    return spec.factory(config)
