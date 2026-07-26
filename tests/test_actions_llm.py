"""
Tests for the LLM-backed action suggester (M5.3, step D): the additive
``AnalysisProvider.suggest_actions`` (default-raise + OpenAI structured path via a
mocked client), the ``LlmActionSuggester`` mapping, and suggester selection.
Offline — no live LLM.
"""

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from app.actions.llm_suggester import LlmActionSuggester
from app.actions.suggester import RuleBasedActionSuggester, build_action_suggester
from app.ai.base import AnalysisProvider, ProviderError, ProviderResponseError
from app.ai.config import ProviderConfig
from app.ai.openai_provider import OpenAIProvider
from app.config import Settings
from app.db.models import Analysis, Ticket
from app.models import (
    ActionType,
    ActorType,
    ResolutionPlan,
    SuggestedAction,
    TicketStatus,
)
from openai import APITimeoutError

ORG = uuid.uuid4()


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"_env_file": None}
    base.update(overrides)
    return Settings(**base)


def _ticket() -> Ticket:
    ticket = Ticket(organization_id=ORG, raw_text="please refund me", text_hash="h", source="api")
    ticket.id = uuid.uuid4()
    return ticket


def _analysis() -> Analysis:
    analysis = Analysis(
        ticket_id=uuid.uuid4(),
        summary="Customer wants a refund.",
        category="Refund",
        priority="High",
        next_actions=["x"],
    )
    analysis.id = uuid.uuid4()
    analysis.created_at = datetime.now(UTC)
    return analysis


# ---------------------------------------------------------------------------
# AnalysisProvider.suggest_actions default (backward compatible)
# ---------------------------------------------------------------------------


class _MinimalProvider(AnalysisProvider):
    """A provider that implements only the abstract surface (no suggest_actions)."""

    @property
    def name(self) -> str:
        return "minimal"

    @property
    def model(self) -> str:
        return "m"

    async def analyze(self, ticket_text: str, *, context: str | None = None) -> Any:
        raise NotImplementedError


class TestSuggestActionsDefault:
    @pytest.mark.anyio
    async def test_default_raises_provider_error(self) -> None:
        # Existing providers stay valid: the default suggest_actions raises,
        # so adding it did not break subclasses that don't support it.
        with pytest.raises(ProviderError):
            await _MinimalProvider().suggest_actions("hello")


# ---------------------------------------------------------------------------
# OpenAIProvider.suggest_actions (mocked SDK)
# ---------------------------------------------------------------------------


def _config(**overrides: Any) -> ProviderConfig:
    base: dict[str, Any] = {"provider": "openai", "model": "gpt-4o-test", "api_key": "sk-x"}
    base.update(overrides)
    return ProviderConfig(**base)


def _completion(parsed: Any = None, refusal: str | None = None) -> MagicMock:
    message = MagicMock()
    message.refusal = refusal
    message.parsed = parsed
    choice = MagicMock()
    choice.message = message
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def _provider_with_parse(parse_mock: AsyncMock, **overrides: Any) -> OpenAIProvider:
    provider = OpenAIProvider(_config(**overrides))
    client = MagicMock()
    client.beta.chat.completions.parse = parse_mock
    provider._client = client
    return provider


class TestOpenAISuggestActions:
    @pytest.mark.anyio
    async def test_returns_plan(self) -> None:
        plan = ResolutionPlan(
            actions=[SuggestedAction(action_type=ActionType.ADD_NOTE, rationale="note it")]
        )
        parse = AsyncMock(return_value=_completion(parsed=plan))
        provider = _provider_with_parse(parse)
        result = await provider.suggest_actions("t", analysis_summary="s", context="ctx")
        assert result.actions[0].action_type == ActionType.ADD_NOTE

    @pytest.mark.anyio
    async def test_refusal_is_response_error(self) -> None:
        parse = AsyncMock(return_value=_completion(refusal="no"))
        provider = _provider_with_parse(parse)
        with pytest.raises(ProviderResponseError):
            await provider.suggest_actions("t")

    @pytest.mark.anyio
    async def test_unparseable_is_response_error(self) -> None:
        parse = AsyncMock(return_value=_completion(parsed=None))
        provider = _provider_with_parse(parse)
        with pytest.raises(ProviderResponseError):
            await provider.suggest_actions("t")

    @pytest.mark.anyio
    async def test_timeout_translated(self) -> None:
        parse = AsyncMock(side_effect=APITimeoutError(request=httpx.Request("POST", "http://x")))
        provider = _provider_with_parse(parse, max_retries=1)
        from app.ai.base import ProviderTimeoutError

        with pytest.raises(ProviderTimeoutError):
            await provider.suggest_actions("t")


# ---------------------------------------------------------------------------
# LlmActionSuggester mapping
# ---------------------------------------------------------------------------


class TestLlmActionSuggester:
    @pytest.mark.anyio
    async def test_maps_plan_to_proposals(self) -> None:
        plan = ResolutionPlan(
            actions=[
                SuggestedAction(
                    action_type=ActionType.SET_STATUS,
                    rationale="begin",
                    status=TicketStatus.IN_PROGRESS,
                ),
                SuggestedAction(
                    action_type=ActionType.SEND_REPLY, rationale="reply", note="hi there"
                ),
                SuggestedAction(
                    action_type=ActionType.ASSIGN, rationale="route it", assignee="billing"
                ),
            ]
        )
        provider = MagicMock()
        provider.suggest_actions = AsyncMock(return_value=plan)
        suggester = LlmActionSuggester(provider)
        assert suggester.name == "llm" and suggester.actor_type == ActorType.AI

        analysis = _analysis()
        proposals = await suggester.suggest(ticket=_ticket(), analysis=analysis, context="ctx")
        assert proposals[0].action_type == ActionType.SET_STATUS
        assert proposals[0].params == {"status": "in_progress"}
        assert proposals[0].analysis_id == analysis.id
        # send_reply is destructive (canonical mapping) and carries the note.
        assert proposals[1].is_destructive is True
        assert proposals[1].params == {"note": "hi there"}
        assert proposals[2].params == {"assignee": "billing"}

    @pytest.mark.anyio
    async def test_passes_ticket_text_and_summary(self) -> None:
        provider = MagicMock()
        provider.suggest_actions = AsyncMock(return_value=ResolutionPlan(actions=[]))
        suggester = LlmActionSuggester(provider)
        await suggester.suggest(ticket=_ticket(), analysis=_analysis(), context="ctx")
        kwargs = provider.suggest_actions.await_args.kwargs
        assert kwargs["analysis_summary"] == "Customer wants a refund."
        assert kwargs["context"] == "ctx"


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


class TestBuildActionSuggester:
    def test_default_is_rule(self) -> None:
        suggester = build_action_suggester(_settings(), provider=MagicMock())
        assert isinstance(suggester, RuleBasedActionSuggester)

    def test_llm_selected(self) -> None:
        suggester = build_action_suggester(_settings(action_suggester="llm"), provider=MagicMock())
        assert isinstance(suggester, LlmActionSuggester)

    def test_unknown_falls_back_to_rule(self) -> None:
        suggester = build_action_suggester(_settings(action_suggester="nope"), provider=MagicMock())
        assert isinstance(suggester, RuleBasedActionSuggester)
