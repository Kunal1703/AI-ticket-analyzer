"""
Pure routing/SLA evaluation (no I/O).

``RoutingEngine`` picks the first active rule whose conditions all match an
analysis and returns its actions. ``SlaCalculator`` computes a resolution deadline
from the matching SLA policy. Both take already-loaded ORM rows and are trivially
unit-testable.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

from app.db.models import RoutingRule, SlaPolicy
from app.routing.base import RoutingDecision


def _rule_matches(conditions: dict[str, str], *, category: str, priority: str) -> bool:
    """Return True if every present condition key equals the analysis value."""
    if "category" in conditions and conditions["category"] != category:
        return False
    return not ("priority" in conditions and conditions["priority"] != priority)


class RoutingEngine:
    """Evaluate ordered routing rules against an analysis (first match wins)."""

    @staticmethod
    def evaluate(*, category: str, priority: str, rules: Sequence[RoutingRule]) -> RoutingDecision:
        for rule in rules:
            if _rule_matches(rule.conditions or {}, category=category, priority=priority):
                actions = rule.actions or {}
                assignee = actions.get("assignee")
                raw_tags = actions.get("tags")
                tags = tuple(str(t) for t in raw_tags) if isinstance(raw_tags, list) else ()
                return RoutingDecision(
                    assignee=assignee if isinstance(assignee, str) else None,
                    tags=tags,
                    matched_rule_id=rule.id,
                )
        return RoutingDecision()


class SlaCalculator:
    """Compute a resolution deadline from the SLA policy matching a priority."""

    @staticmethod
    def due_at(
        *, priority: str, policies: Sequence[SlaPolicy], base_time: datetime
    ) -> datetime | None:
        for policy in policies:
            if policy.priority == priority:
                return base_time + timedelta(minutes=policy.resolution_minutes)
        return None
