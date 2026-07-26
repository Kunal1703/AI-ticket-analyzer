"""
Provider-neutral configuration for embedding backends (M5.2).

``EmbeddingConfig`` is the single value object passed to every embedding
provider — the embeddings analogue of :class:`app.ai.config.ProviderConfig`. It
decouples concrete providers from the application's global ``Settings``.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingConfig:
    """Resolved configuration for a single embedding provider.

    Attributes:
        provider: Registered provider name (e.g. ``"openai"``, ``"hash"``).
        model: Embedding model identifier to request.
        api_key: API key/token, or ``None`` for providers that need none.
        base_url: API base URL, or ``None`` to use the provider SDK default.
        timeout: Per-request timeout in seconds.
        max_retries: Maximum attempts on transient failures (incl. the first).
        dimensions: Output vector size — used only by the keyless ``hash``
            provider (real APIs determine the dimension from the model).
    """

    provider: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    timeout: int = 30
    max_retries: int = 3
    dimensions: int = 256
