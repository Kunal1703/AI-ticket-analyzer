"""
OpenAI-SDK-based implementation of :class:`~app.embeddings.base.EmbeddingProvider`.

Uses the OpenAI Python SDK and therefore works with OpenAI **and any
OpenAI-compatible embeddings endpoint** (e.g. Ollama, a custom gateway) by
varying ``base_url``/``api_key``/``model`` via the injected
:class:`~app.embeddings.config.EmbeddingConfig`. Mirrors
:class:`~app.ai.openai_provider.OpenAIProvider`: lazy client, tenacity retries,
and translation of OpenAI errors into the ``Embedding*`` hierarchy.
"""

import logging
from collections.abc import Sequence

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.embeddings.base import (
    EmbeddingConnectionError,
    EmbeddingProvider,
    EmbeddingRateLimitError,
    EmbeddingResponseError,
    EmbeddingTimeoutError,
)
from app.embeddings.config import EmbeddingConfig

logger = logging.getLogger(__name__)

# AsyncOpenAI requires a non-empty api_key string even for endpoints (e.g.
# Ollama) that ignore it.
_PLACEHOLDER_API_KEY = "not-needed"


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Embed text via the OpenAI SDK (OpenAI or any compatible endpoint)."""

    def __init__(self, config: EmbeddingConfig) -> None:
        self._config = config
        self._client: AsyncOpenAI | None = None

    @property
    def name(self) -> str:
        return self._config.provider

    @property
    def model(self) -> str:
        return self._config.model

    def _get_client(self) -> AsyncOpenAI:
        """Lazily create and cache the AsyncOpenAI client."""
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._config.api_key or _PLACEHOLDER_API_KEY,
                base_url=self._config.base_url,
                timeout=self._config.timeout,
                max_retries=0,  # Retries handled by tenacity for finer control.
            )
        return self._client

    async def _request_embeddings(self, texts: Sequence[str]) -> list[list[float]]:
        """Perform a single embeddings request (no retry logic)."""
        client = self._get_client()
        response = await client.embeddings.create(model=self._config.model, input=list(texts))
        data = getattr(response, "data", None)
        if not data or len(data) != len(texts):
            raise ValueError("embeddings response did not match the request")
        return [list(item.embedding) for item in data]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts, retrying transient errors with backoff.

        OpenAI-SDK exceptions are translated into the provider-agnostic
        ``Embedding*`` errors so callers never depend on the OpenAI SDK.
        """
        if not texts:
            return []
        retryer = AsyncRetrying(
            retry=retry_if_exception_type((APIConnectionError, APITimeoutError, RateLimitError)),
            stop=stop_after_attempt(self._config.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            reraise=True,
        )
        try:
            vectors: list[list[float]] = await retryer(self._request_embeddings, texts)
        except APITimeoutError as exc:
            raise EmbeddingTimeoutError(str(exc)) from exc
        except RateLimitError as exc:
            raise EmbeddingRateLimitError(str(exc)) from exc
        except (APIConnectionError, APIStatusError) as exc:
            raise EmbeddingConnectionError(str(exc)) from exc
        except ValueError as exc:
            raise EmbeddingResponseError(str(exc)) from exc
        return vectors

    async def aclose(self) -> None:
        """Close the underlying AsyncOpenAI client, if one was created."""
        if self._client is not None:
            await self._client.close()
            self._client = None
