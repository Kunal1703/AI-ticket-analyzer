"""Embedding provider abstraction for AI Ticket Analyzer (M5.2).

Public surface for resolving and using text-embedding providers without
depending on any concrete backend — the embeddings analogue of :mod:`app.ai`.
Used by the RAG layer (:mod:`app.rag`) to embed knowledge-base documents and
retrieval queries.
"""

from app.embeddings.base import (
    EmbeddingConnectionError,
    EmbeddingError,
    EmbeddingProvider,
    EmbeddingRateLimitError,
    EmbeddingResponseError,
    EmbeddingTimeoutError,
)
from app.embeddings.config import EmbeddingConfig
from app.embeddings.factory import build_embedding_provider

__all__ = [
    "EmbeddingConfig",
    "EmbeddingConnectionError",
    "EmbeddingError",
    "EmbeddingProvider",
    "EmbeddingRateLimitError",
    "EmbeddingResponseError",
    "EmbeddingTimeoutError",
    "build_embedding_provider",
]
