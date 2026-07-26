"""
Pure state machine for resolution actions (M5.3).

Unlike ticket status (M3.6), whose transitions are intentionally unrestricted,
resolution actions enforce a real state machine — the safety story requires that
an action can only be executed *after* it is approved, and terminal states are
final. No I/O; trivially unit-testable.
"""

from app.models import ActionStatus


class InvalidActionTransition(Exception):
    """Raised when a resolution action is moved between incompatible states."""


# proposed → approved | rejected ; approved → executed | failed ; rest terminal.
_ALLOWED: dict[ActionStatus, frozenset[ActionStatus]] = {
    ActionStatus.PROPOSED: frozenset({ActionStatus.APPROVED, ActionStatus.REJECTED}),
    ActionStatus.APPROVED: frozenset({ActionStatus.EXECUTED, ActionStatus.FAILED}),
    ActionStatus.REJECTED: frozenset(),
    ActionStatus.EXECUTED: frozenset(),
    ActionStatus.FAILED: frozenset(),
}

TERMINAL_STATES: frozenset[ActionStatus] = frozenset(
    {ActionStatus.REJECTED, ActionStatus.EXECUTED, ActionStatus.FAILED}
)


def can_transition(current: ActionStatus, target: ActionStatus) -> bool:
    """Whether ``current`` may move to ``target``."""
    return target in _ALLOWED[current]


def ensure_transition(current: ActionStatus, target: ActionStatus) -> None:
    """Raise :class:`InvalidActionTransition` unless the move is allowed."""
    if not can_transition(current, target):
        raise InvalidActionTransition(
            f"Cannot transition action from {current.value} to {target.value}"
        )
