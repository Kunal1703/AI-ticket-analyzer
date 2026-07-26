"""
Provider-agnostic interface for text embeddings (M5.2).

Mirrors the analysis-provider abstraction (:mod:`app.ai.base`): the RAG layer
depends only on :class:`EmbeddingProvider` and a provider-agnostic error
hierarchy, so a new embeddings backend can be added by implementing this
interface and registering it in :mod:`app.embeddings.factory` — without changing
any RAG/business logic.

Contract: implementations MUST translate backend-specific failures into the
``Embedding*`` exceptions below, and return one vector per input text (in order).
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence


class EmbeddingError(Exception):
    """Base class for embedding-provider failures."""


class EmbeddingTimeoutError(EmbeddingError):
    """The provider did not respond in time."""


class EmbeddingRateLimitError(EmbeddingError):
    """The provider rejected the request due to rate limiting."""


class EmbeddingConnectionError(EmbeddingError):
    """A network/transport-level failure talking to the provider."""


class EmbeddingResponseError(EmbeddingError):
    """The provider returned an unparseable/invalid embeddings response."""


class EmbeddingProvider(ABC):
    """Abstract base class for text-embedding providers.

    Implementations encapsulate all backend-specific concerns (SDK client,
    authentication, model selection, batching, retry/backoff, and error
    translation) behind this interface. Callers depend only on the interface,
    never on a concrete provider or its SDK.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Registered provider name (e.g. ``"openai"``, ``"hash"``)."""

    @property
    @abstractmethod
    def model(self) -> str:
        """Identifier of the embedding model used."""

    @abstractmethod
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts, returning one vector per text (in order).

        Args:
            texts: The texts to embed. An empty sequence returns ``[]`` without
                calling the backend.

        Returns:
            A list of embedding vectors, aligned with ``texts``.

        Raises:
            EmbeddingTimeoutError: The request timed out.
            EmbeddingRateLimitError: The provider rate limit was reached.
            EmbeddingConnectionError: A network/transport failure occurred.
            EmbeddingResponseError: The response was unparseable/invalid.
            EmbeddingError: Any other provider failure.
        """
        raise NotImplementedError

    async def embed_one(self, text: str) -> list[float]:
        """Embed a single text (convenience wrapper over :meth:`embed`)."""
        vectors = await self.embed([text])
        return vectors[0]

    async def aclose(self) -> None:
        """Release any resources held by the provider (default no-op)."""
        return None
