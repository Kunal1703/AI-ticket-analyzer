"""
Action suggesters + registry (M5.3).

A suggester proposes resolution actions for a ticket. The **default is
deterministic and rule-based** — no LLM, no network — so the whole agentic
workflow runs offline and safely (mirroring the keyless embedding/cache
defaults). An optional LLM-backed suggester (`ACTION_SUGGESTER=llm`) is added in
``app.actions.llm_suggester`` and registered here.

Suggesting never executes anything: proposals are persisted as ``proposed`` and
require human approval.
"""

import logging

from app.actions.base import DESTRUCTIVE_ACTIONS, ActionSuggester, ProposedAction, is_destructive
from app.ai.base import AnalysisProvider
from app.config import Settings
from app.db.models import Analysis, Ticket
from app.models import ActionType, ActorType, TicketPriority, TicketStatus

logger = logging.getLogger(__name__)

_HIGH_PRIORITIES = frozenset({TicketPriority.HIGH.value, TicketPriority.CRITICAL.value})


def _proposed(
    action_type: ActionType,
    *,
    rationale: str,
    params: dict[str, object] | None = None,
    analysis: Analysis | None = None,
) -> ProposedAction:
    return ProposedAction(
        action_type=action_type,
        params=params or {},
        rationale=rationale,
        is_destructive=is_destructive(action_type),
        analysis_id=analysis.id if analysis is not None else None,
    )


class RuleBasedActionSuggester:
    """Deterministic suggester: maps a ticket's latest analysis to proposals.

    Pure and offline — the safe default. Destructive proposals (escalate/reply)
    are still only *proposals*; nothing runs without approval.
    """

    name = "rule"
    actor_type = ActorType.SYSTEM

    async def suggest(
        self, *, ticket: Ticket, analysis: Analysis | None, context: str | None
    ) -> list[ProposedAction]:
        if analysis is None:
            # No analysis yet — propose the minimal triage step.
            return [
                _proposed(
                    ActionType.SET_STATUS,
                    rationale="Ticket has no analysis; move it into triage.",
                    params={"status": TicketStatus.IN_PROGRESS.value},
                )
            ]

        proposals: list[ProposedAction] = [
            _proposed(
                ActionType.ADD_NOTE,
                rationale="Summarize the issue for the assignee.",
                params={"note": analysis.summary},
                analysis=analysis,
            ),
            _proposed(
                ActionType.SET_STATUS,
                rationale="Begin working the ticket.",
                params={"status": TicketStatus.IN_PROGRESS.value},
                analysis=analysis,
            ),
        ]
        if analysis.priority in _HIGH_PRIORITIES:
            proposals.append(
                _proposed(
                    ActionType.ESCALATE,
                    rationale=f"{analysis.priority} priority — escalate for urgent handling.",
                    analysis=analysis,
                )
            )
        if analysis.category in {"Refund", "Billing"}:
            proposals.append(
                _proposed(
                    ActionType.SEND_REPLY,
                    rationale="Draft a reply acknowledging the billing/refund request.",
                    params={
                        "note": (
                            "Thanks for reaching out — we're reviewing your "
                            "billing/refund request and will follow up shortly."
                        )
                    },
                    analysis=analysis,
                )
            )
        return proposals


def build_action_suggester(settings: Settings, *, provider: AnalysisProvider) -> ActionSuggester:
    """Select the configured suggester.

    Default ``"rule"`` (deterministic, offline). ``"llm"`` reuses the AI provider
    (``provider``) via a lazily-imported suggester. An unknown value fails safe to
    the rule-based suggester.
    """
    name = settings.action_suggester.lower()
    if name == "llm":
        from app.actions.llm_suggester import LlmActionSuggester

        llm: ActionSuggester = LlmActionSuggester(provider)
        return llm
    if name != "rule":
        logger.warning("Unknown ACTION_SUGGESTER %r; falling back to rule-based", name)
    return RuleBasedActionSuggester()


__all__ = [
    "DESTRUCTIVE_ACTIONS",
    "RuleBasedActionSuggester",
    "build_action_suggester",
]
