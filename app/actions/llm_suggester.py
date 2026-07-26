"""
LLM-backed action suggester (M5.3, opt-in via ``ACTION_SUGGESTER=llm``).

Reuses the existing provider-agnostic ``AnalysisProvider`` (its additive
``suggest_actions`` structured-output method) rather than introducing a parallel
LLM path — so it works with any backend and translates failures through the same
``Provider*`` hierarchy. It only *proposes*; approval + execution are unchanged.
"""

from app.actions.base import ProposedAction, is_destructive
from app.ai.base import AnalysisProvider
from app.db.models import Analysis, Ticket
from app.models import ActorType, SuggestedAction


def _to_params(action: SuggestedAction) -> dict[str, object]:
    """Map a suggested action's typed fields into the stored ``params`` dict."""
    params: dict[str, object] = {}
    if action.status is not None:
        params["status"] = action.status.value
    if action.assignee is not None:
        params["assignee"] = action.assignee
    if action.note is not None:
        params["note"] = action.note
    return params


class LlmActionSuggester:
    """Proposes actions by asking the AI provider for a structured ``ResolutionPlan``."""

    name = "llm"
    actor_type = ActorType.AI

    def __init__(self, provider: AnalysisProvider) -> None:
        self._provider = provider

    async def suggest(
        self, *, ticket: Ticket, analysis: Analysis | None, context: str | None
    ) -> list[ProposedAction]:
        plan = await self._provider.suggest_actions(
            ticket.raw_text,
            analysis_summary=analysis.summary if analysis is not None else None,
            context=context,
        )
        analysis_id = analysis.id if analysis is not None else None
        return [
            ProposedAction(
                action_type=action.action_type,
                params=_to_params(action),
                rationale=action.rationale,
                is_destructive=is_destructive(action.action_type),
                analysis_id=analysis_id,
            )
            for action in plan.actions
        ]
