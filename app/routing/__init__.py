"""
Routing & SLA (Milestone M3.4a).

Per-tenant helpdesk configuration: routing rules (assign a ticket / add tags based
on its analysis) and SLA policies (a resolution deadline per priority). Pure
evaluation lives in ``engine``; ``routes`` exposes config CRUD plus an explicit
``POST /v1/tickets/{id}/route`` that applies the config to a ticket's latest
analysis and persists the outcome (``assignee`` + ``sla_due_at``).

Custom per-tenant categories/taxonomy (which require dynamic structured-output
schema generation) are a later milestone (M3.4b).
"""

from app.routing.base import RoutingDecision, RoutingRuleStore, SlaPolicyStore
from app.routing.engine import RoutingEngine, SlaCalculator

__all__ = [
    "RoutingDecision",
    "RoutingEngine",
    "RoutingRuleStore",
    "SlaCalculator",
    "SlaPolicyStore",
]
