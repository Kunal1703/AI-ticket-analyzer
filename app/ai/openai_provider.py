"""
OpenAI-SDK-based implementation of the :class:`~app.ai.base.AnalysisProvider`.

This provider uses the OpenAI Python SDK and therefore works with OpenAI **and
any OpenAI-compatible endpoint** (Groq, Together AI, OpenRouter, Ollama, or a
custom gateway) simply by varying ``base_url``, ``api_key``, and ``model`` via
the injected :class:`~app.ai.config.ProviderConfig`. It encapsulates client
lifecycle, structured-output requests, refusal handling, retry/backoff, and
translation of OpenAI errors into the provider-agnostic ``Provider*`` hierarchy.
"""

import logging
import time

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

from app.ai.base import (
    AnalysisProvider,
    AnalysisResult,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    TokenUsage,
)
from app.ai.config import ProviderConfig
from app.models import ResolutionPlan, TicketAnalysis
from app.prompts import ACTION_SYSTEM_PROMPT, build_action_user_prompt, get_prompt

logger = logging.getLogger(__name__)

# AsyncOpenAI requires a non-empty api_key string even for endpoints (e.g.
# Ollama) that ignore it.
_PLACEHOLDER_API_KEY = "not-needed"


class OpenAIProvider(AnalysisProvider):
    """Analyze tickets via the OpenAI SDK (OpenAI or any compatible endpoint)."""

    def __init__(self, config: ProviderConfig) -> None:
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

    @staticmethod
    def _extract_usage(completion: object) -> TokenUsage | None:
        """Best-effort extraction of token usage from a completion."""
        usage = getattr(completion, "usage", None)
        if usage is None:
            return None
        try:
            return TokenUsage(
                prompt_tokens=int(usage.prompt_tokens),
                completion_tokens=int(usage.completion_tokens),
                total_tokens=int(usage.total_tokens),
            )
        except (AttributeError, TypeError, ValueError):
            return None

    async def _request_analysis(
        self, ticket_text: str, context: str | None = None
    ) -> AnalysisResult:
        """Perform a single structured-output request (no retry logic)."""
        config = self._config
        client = self._get_client()
        prompt = get_prompt(config.prompt_version)

        logger.info(
            "Sending ticket to %s (model=%s, prompt=%s, length=%d chars, grounded=%s)",
            config.provider,
            config.model,
            prompt.version,
            len(ticket_text),
            bool(context),
        )
        start = time.perf_counter()

        completion = await client.beta.chat.completions.parse(
            model=config.model,
            messages=[
                {"role": "system", "content": prompt.system_prompt},
                {"role": "user", "content": prompt.build_user_message(ticket_text, context)},
            ],
            response_format=TicketAnalysis,
            temperature=config.temperature,
        )

        latency_ms = (time.perf_counter() - start) * 1000
        logger.info("%s response received in %.0f ms", config.provider, latency_ms)

        message = completion.choices[0].message

        # Structured output parsing — the SDK raises if parsing fails, but we
        # add a defensive check for refusals.
        if message.refusal:
            logger.error("%s refused the request: %s", config.provider, message.refusal)
            raise ValueError(f"{config.provider} refused the request: {message.refusal}")

        if message.parsed is None:
            logger.error("%s returned an unparseable response", config.provider)
            raise ValueError(f"{config.provider} returned an unparseable response")

        analysis: TicketAnalysis = message.parsed
        logger.info(
            "Analysis complete — category=%s, priority=%s",
            analysis.category.value,
            analysis.priority.value,
        )
        return AnalysisResult(
            analysis=analysis,
            usage=self._extract_usage(completion),
            prompt_version=prompt.version,
        )

    async def analyze(self, ticket_text: str, *, context: str | None = None) -> AnalysisResult:
        """Analyze a ticket, retrying transient errors with backoff.

        The maximum number of attempts comes from ``config.max_retries`` (total
        attempts, including the first). OpenAI-SDK exceptions are translated
        into the provider-agnostic ``Provider*`` errors so callers never depend
        on the OpenAI SDK. ``context`` (optional RAG grounding) is folded into the
        prompt by the selected :class:`~app.prompts.PromptVersion`.
        """
        retryer = AsyncRetrying(
            retry=retry_if_exception_type((APIConnectionError, APITimeoutError, RateLimitError)),
            stop=stop_after_attempt(self._config.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            reraise=True,
        )
        try:
            result: AnalysisResult = await retryer(self._request_analysis, ticket_text, context)
        except APITimeoutError as exc:
            raise ProviderTimeoutError(str(exc)) from exc
        except RateLimitError as exc:
            raise ProviderRateLimitError(str(exc)) from exc
        except (APIConnectionError, APIStatusError) as exc:
            raise ProviderConnectionError(str(exc)) from exc
        except ValueError as exc:
            # Raised by _request_analysis on refusal / unparseable output.
            raise ProviderResponseError(str(exc)) from exc
        return result

    async def _request_actions(
        self, ticket_text: str, analysis_summary: str | None, context: str | None
    ) -> ResolutionPlan:
        """Perform a single structured action-suggestion request (no retry logic)."""
        client = self._get_client()
        completion = await client.beta.chat.completions.parse(
            model=self._config.model,
            messages=[
                {"role": "system", "content": ACTION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_action_user_prompt(
                        ticket_text, analysis_summary=analysis_summary, context=context
                    ),
                },
            ],
            response_format=ResolutionPlan,
            temperature=self._config.temperature,
        )
        message = completion.choices[0].message
        if message.refusal:
            raise ValueError(f"{self._config.provider} refused the request: {message.refusal}")
        if message.parsed is None:
            raise ValueError(f"{self._config.provider} returned an unparseable response")
        plan: ResolutionPlan = message.parsed
        return plan

    async def suggest_actions(
        self,
        ticket_text: str,
        *,
        analysis_summary: str | None = None,
        context: str | None = None,
    ) -> ResolutionPlan:
        """Propose resolution actions via structured output (M5.3).

        Reuses the same client, retry policy, and ``Provider*`` error translation
        as :meth:`analyze` — only the schema (``ResolutionPlan``) and prompt differ.
        """
        retryer = AsyncRetrying(
            retry=retry_if_exception_type((APIConnectionError, APITimeoutError, RateLimitError)),
            stop=stop_after_attempt(self._config.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            reraise=True,
        )
        try:
            plan: ResolutionPlan = await retryer(
                self._request_actions, ticket_text, analysis_summary, context
            )
        except APITimeoutError as exc:
            raise ProviderTimeoutError(str(exc)) from exc
        except RateLimitError as exc:
            raise ProviderRateLimitError(str(exc)) from exc
        except (APIConnectionError, APIStatusError) as exc:
            raise ProviderConnectionError(str(exc)) from exc
        except ValueError as exc:
            raise ProviderResponseError(str(exc)) from exc
        return plan

    async def aclose(self) -> None:
        """Close the underlying AsyncOpenAI client, if one was created."""
        if self._client is not None:
            await self._client.close()
            self._client = None
