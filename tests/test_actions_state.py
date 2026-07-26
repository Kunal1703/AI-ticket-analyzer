"""
Tests for the M5.3 action state machine + schema registration (step A). Offline.
"""

import pytest
from app.actions.state import (
    TERMINAL_STATES,
    InvalidActionTransition,
    can_transition,
    ensure_transition,
)
from app.models import ActionStatus


class TestActionStateMachine:
    def test_proposed_can_approve_or_reject(self) -> None:
        assert can_transition(ActionStatus.PROPOSED, ActionStatus.APPROVED)
        assert can_transition(ActionStatus.PROPOSED, ActionStatus.REJECTED)

    def test_proposed_cannot_execute_directly(self) -> None:
        # The safety invariant: execution requires prior approval.
        assert not can_transition(ActionStatus.PROPOSED, ActionStatus.EXECUTED)

    def test_approved_can_execute_or_fail(self) -> None:
        assert can_transition(ActionStatus.APPROVED, ActionStatus.EXECUTED)
        assert can_transition(ActionStatus.APPROVED, ActionStatus.FAILED)

    def test_approved_cannot_be_rejected(self) -> None:
        assert not can_transition(ActionStatus.APPROVED, ActionStatus.REJECTED)

    def test_terminal_states_have_no_transitions(self) -> None:
        for state in TERMINAL_STATES:
            assert not can_transition(state, ActionStatus.APPROVED)
            assert not can_transition(state, ActionStatus.EXECUTED)

    def test_terminal_set(self) -> None:
        assert (
            frozenset({ActionStatus.REJECTED, ActionStatus.EXECUTED, ActionStatus.FAILED})
            == TERMINAL_STATES
        )

    def test_ensure_transition_ok(self) -> None:
        ensure_transition(ActionStatus.PROPOSED, ActionStatus.APPROVED)  # no raise

    def test_ensure_transition_raises(self) -> None:
        with pytest.raises(InvalidActionTransition, match="Cannot transition"):
            ensure_transition(ActionStatus.PROPOSED, ActionStatus.EXECUTED)


class TestActionSchema:
    def test_tables_registered(self) -> None:
        from app.db.base import Base

        assert {"resolution_actions", "audit_logs"} <= set(Base.metadata.tables)

    def test_resolution_action_columns(self) -> None:
        from app.db.models import ResolutionAction

        assert {
            "organization_id",
            "ticket_id",
            "analysis_id",
            "action_type",
            "params",
            "status",
            "is_destructive",
            "approved_by",
            "result",
        } <= set(ResolutionAction.__table__.columns.keys())

    def test_suggested_action_defaults(self) -> None:
        from app.models import ActionType, SuggestedAction

        action = SuggestedAction(action_type=ActionType.ADD_NOTE, rationale="because")
        assert action.status is None and action.assignee is None and action.note is None
