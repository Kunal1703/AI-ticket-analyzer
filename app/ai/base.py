"""
Provider-agnostic interface for ticket analysis.

Defines the abstract contract that every AI backend must implement, plus a
provider-agnostic exception hierarchy. The business/API layer depends only on
these abstractions, so future backends (e.g. Anthropic, Gemini, Ollama) can be
added by implementing this interface and registering them in ``app.ai.factory``
— **without changing any business logic or HTTP error mapping**.

Contract: implementations MUST translate backend-specific failures into the
``Provider*`` exceptions below so the application layer can map them to HTTP
status codes without knowing which concrete provider produced them.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.models import ResolutionPlan, TicketAnalysis


@dataclass(frozen=True)
class TokenUsage:
    """Token counts reported by a provider for one analysis."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class AnalysisResult:
    """A provider's analysis plus optional usage + prompt metadata.

    Separating these from the ``TicketAnalysis`` keeps the API response and the
    cached value unchanged while still surfacing token counts (metrics +
    persistence) and the prompt version (persistence + eval, M5.1).
    """

    analysis: TicketAnalysis
    usage: TokenUsage | None = None
    prompt_version: str | None = None


class ProviderError(Exception):
    """Base class for AI provider failures (maps to HTTP 502)."""


class ProviderTimeoutError(ProviderError):
    """The provider did not respond in time (maps to HTTP 504)."""


class ProviderRateLimitError(ProviderError):
    """The provider rejected the request due to rate limiting (maps to HTTP 429)."""


class ProviderConnectionError(ProviderError):
    """A network/transport-level failure talking to the provider (maps to HTTP 502)."""


class ProviderResponseError(ProviderError):
    """The provider returned a refused/unparseable/invalid response (maps to HTTP 502)."""


class AnalysisProvider(ABC):
    """Abstract base class for ticket-analysis providers.

    Implementations encapsulate all backend-specific concerns (SDK client,
    authentication, model selection, request/response shaping, retry/backoff,
    and error translation) behind this interface. Callers depend only on the
    interface, never on a concrete provider or its SDK.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Registered provider name (e.g. ``"openai"``, ``"ollama"``)."""

    @property
    @abstractmethod
    def model(self) -> str:
        """Identifier of the model used to produce analyses."""

    @abstractmethod
    async def analyze(self, ticket_text: str, *, context: str | None = None) -> AnalysisResult:
        """Analyze a support ticket and return the result with usage metadata.

        Args:
            ticket_text: Raw customer support ticket content.
            context: Optional retrieved knowledge-base context to ground the
                analysis (RAG, M5.2). Additive: ``None`` reproduces the prior
                behavior, and prompt versions that don't use context ignore it.

        Returns:
            An ``AnalysisResult`` (validated analysis + optional token usage).

        Raises:
            ProviderTimeoutError: The request timed out.
            ProviderRateLimitError: The provider rate limit was reached.
            ProviderConnectionError: A network/transport failure occurred.
            ProviderResponseError: The response was refused or unparseable.
            ProviderError: Any other provider failure.
        """
        raise NotImplementedError

    async def suggest_actions(
        self,
        ticket_text: str,
        *,
        analysis_summary: str | None = None,
        context: str | None = None,
    ) -> ResolutionPlan:
        """Propose resolution actions for a ticket (agentic actions, M5.3).

        **Additive + optional:** the default raises ``ProviderError`` so existing
        providers stay valid without change; a provider that supports structured
        action suggestion overrides this (translating SDK errors into
        ``Provider*``). Callers that don't need it are unaffected. The returned
        plan is only ever *proposed* — nothing here executes anything.
        """
        raise ProviderError("This provider does not support action suggestion")

    async def aclose(self) -> None:
        """Release any resources held by the provider.

        Called during application shutdown. The default is a no-op; providers
        that hold network clients should override this to close them.
        """
        return None
