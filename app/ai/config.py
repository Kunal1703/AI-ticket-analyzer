"""
Provider-neutral configuration for AI backends.

``ProviderConfig`` is the single value object passed to every provider. It
decouples concrete providers from the application's global ``Settings`` — a
provider depends only on the fields it needs (credentials, endpoint, model,
retry/timeout policy), never on app-wide configuration.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    """Resolved configuration for a single AI provider.

    Attributes:
        provider: Registered provider name (e.g. ``"openai"``, ``"ollama"``).
        model: Model identifier to request.
        api_key: API key/token, or ``None`` for providers that need none.
        base_url: API base URL, or ``None`` to use the provider SDK default.
        timeout: Per-request timeout in seconds.
        max_retries: Maximum attempts on transient failures (incl. the first).
        temperature: Sampling temperature.
        prompt_version: Prompt version to use (``None`` ⇒ default; see
            ``app.prompts``). Recorded on each analysis for eval/traceability.
    """

    provider: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    timeout: int = 30
    max_retries: int = 3
    temperature: float = 0.2
    prompt_version: str | None = None
