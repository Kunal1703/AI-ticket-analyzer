"""
Deterministic, keyless local embeddings via feature hashing (M5.2).

The ``hash`` provider produces a normalized bag-of-tokens vector using a stable
hash (so results are reproducible across processes, unlike Python's salted
``hash()``). It requires **no API key and no network**, mirroring the in-memory
cache and in-process job runner: it lets RAG run end-to-end offline and makes the
default test suite deterministic without mocking an SDK.

It is **not semantically meaningful** (no learned semantics) — use a real
embedding model in production. It is genuinely useful for local development,
tests, and lexical-overlap retrieval.
"""

import hashlib
import math
import re
from collections.abc import Sequence

from app.embeddings.base import EmbeddingProvider
from app.embeddings.config import EmbeddingConfig

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _stable_bucket(token: str, dimensions: int) -> tuple[int, float]:
    """Map a token to a (bucket index, sign) pair via a stable hash."""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    bucket = value % dimensions
    sign = 1.0 if (value >> 63) & 1 else -1.0
    return bucket, sign


def hash_embed(text: str, dimensions: int) -> list[float]:
    """Return a deterministic, L2-normalized feature-hashing vector for ``text``."""
    vector = [0.0] * dimensions
    for token in _TOKEN_RE.findall(text.lower()):
        bucket, sign = _stable_bucket(token, dimensions)
        vector[bucket] += sign
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0.0:
        return vector
    return [component / norm for component in vector]


class HashEmbeddingProvider(EmbeddingProvider):
    """Deterministic keyless embeddings (feature hashing). Dev/testing only."""

    def __init__(self, config: EmbeddingConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return self._config.provider

    @property
    def model(self) -> str:
        return self._config.model

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [hash_embed(text, self._config.dimensions) for text in texts]
