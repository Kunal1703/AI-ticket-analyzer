"""
Agentic resolution actions (Milestone M5.3).

The AI (or a deterministic rule-based suggester) **proposes** resolution actions
for a ticket; a human **approves/rejects** them; approved actions are **executed**
through action handlers; and every transition is written to an append-only,
tenant-scoped **audit log**. Nothing executes automatically, destructive actions
always require approval, and the suggester is pluggable (offline rule-based
default, optional LLM-backed) behind a port — the same abstraction + graceful
degradation DNA as the rest of the codebase.

Pure state-machine transitions live in ``state``; the ports/service live in the
sibling modules.
"""

from app.actions.service import ActionService
from app.actions.state import (
    TERMINAL_STATES,
    InvalidActionTransition,
    can_transition,
    ensure_transition,
)

__all__ = [
    "TERMINAL_STATES",
    "ActionService",
    "InvalidActionTransition",
    "can_transition",
    "ensure_transition",
]
