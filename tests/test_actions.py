"""
Tests for the M5.3 action subsystem (step B): rule-based suggester, handlers,
the action service (suggest/approve/reject/execute + audit + safety invariants),
and the SQLAlchemy stores. All offline with in-memory fakes.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.actions.base import ActionContext
from app.actions.handlers import build_action_handlers
from app.actions.service import ActionService
from app.actions.state import InvalidActionTransition
from app.actions.suggester import RuleBasedActionSuggester
from app.db.action_store import SqlAlchemyActionStore, SqlAlchemyAuditStore
from app.db.models import Analysis, AuditLog, ResolutionAction, Ticket
from app.models import ActionType

ORG = uuid.uuid4()
USER = uuid.uuid4()


def _ticket() -> Ticket:
    ticket = Ticket(organization_id=ORG, raw_text="help", text_hash="h", source="api")
    ticket.id = uuid.uuid4()
    ticket.status = "open"
    ticket.assignee = None
    ticket.created_at = datetime.now(UTC)
    return ticket


def _analysis(*, category: str = "Technical Issue", priority: str = "Medium") -> Analysis:
    analysis = Analysis(
        ticket_id=uuid.uuid4(),
        summary="Customer cannot log in.",
        category=category,
        priority=priority,
        next_actions=["x"],
    )
    analysis.id = uuid.uuid4()
    analysis.created_at = datetime.now(UTC)
    return analysis


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeActionStore:
    def __init__(self) -> None:
        self.actions: list[ResolutionAction] = []

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        ticket_id: uuid.UUID,
        analysis_id: uuid.UUID | None,
        action_type: str,
        params: dict[str, object],
        rationale: str,
        is_destructive: bool,
        suggested_by: str,
    ) -> ResolutionAction:
        action = ResolutionAction(
            organization_id=organization_id,
            ticket_id=ticket_id,
            analysis_id=analysis_id,
            action_type=action_type,
            params=params,
            rationale=rationale,
            is_destructive=is_destructive,
            suggested_by=suggested_by,
            status="proposed",
        )
        action.id = uuid.uuid4()
        action.approved_by = None
        action.result = None
        action.created_at = datetime.now(UTC)
        self.actions.append(action)
        return action

    async def get_for_org(
        self, organization_id: uuid.UUID, action_id: uuid.UUID
    ) -> ResolutionAction | None:
        return next(
            (a for a in self.actions if a.id == action_id and a.organization_id == organization_id),
            None,
        )

    async def list_for_ticket(
        self, organization_id: uuid.UUID, ticket_id: uuid.UUID
    ) -> Sequence[ResolutionAction]:
        return [
            a
            for a in self.actions
            if a.organization_id == organization_id and a.ticket_id == ticket_id
        ]


class FakeAuditStore:
    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    async def record(
        self,
        *,
        organization_id: uuid.UUID,
        actor_type: str,
        actor_id: str | None,
        action: str,
        resource_type: str,
        resource_id: uuid.UUID | None,
        detail: dict[str, object] | None,
    ) -> AuditLog:
        entry = AuditLog(
            organization_id=organization_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
        )
        entry.id = uuid.uuid4()
        entry.created_at = datetime.now(UTC)
        self.entries.append(entry)
        return entry

    async def list_for_org(
        self, organization_id: uuid.UUID, *, limit: int, offset: int
    ) -> Sequence[AuditLog]:
        rows = [e for e in self.entries if e.organization_id == organization_id]
        return rows[offset : offset + limit]

    def events(self) -> list[str]:
        return [e.action for e in self.entries]


class FakeDispatcher:
    def __init__(self) -> None:
        self.dispatched: list[tuple[str, dict[str, Any]]] = []

    async def dispatch(
        self, *, organization_id: uuid.UUID, event_type: str, payload: dict[str, Any]
    ) -> None:
        self.dispatched.append((event_type, payload))


def _service(
    suggester: Any = None, handlers: Any = None
) -> tuple[ActionService, FakeActionStore, FakeAuditStore]:
    actions = FakeActionStore()
    audit = FakeAuditStore()
    service = ActionService(
        actions,
        audit,
        suggester or RuleBasedActionSuggester(),
        handlers if handlers is not None else build_action_handlers(),
    )
    return service, actions, audit


def _ctx(ticket: Ticket) -> ActionContext:
    return ActionContext(ticket=ticket, organization_id=ORG, dispatcher=FakeDispatcher())


# ---------------------------------------------------------------------------
# Rule-based suggester
# ---------------------------------------------------------------------------


class TestRuleBasedSuggester:
    @pytest.mark.anyio
    async def test_no_analysis_proposes_triage(self) -> None:
        proposals = await RuleBasedActionSuggester().suggest(
            ticket=_ticket(), analysis=None, context=None
        )
        assert [p.action_type for p in proposals] == [ActionType.SET_STATUS]
        assert all(not p.is_destructive for p in proposals)

    @pytest.mark.anyio
    async def test_normal_ticket_proposes_note_and_status(self) -> None:
        proposals = await RuleBasedActionSuggester().suggest(
            ticket=_ticket(), analysis=_analysis(), context=None
        )
        types = {p.action_type for p in proposals}
        assert ActionType.ADD_NOTE in types and ActionType.SET_STATUS in types
        assert all(not p.is_destructive for p in proposals)  # none destructive

    @pytest.mark.anyio
    async def test_high_priority_proposes_escalate_destructive(self) -> None:
        proposals = await RuleBasedActionSuggester().suggest(
            ticket=_ticket(), analysis=_analysis(priority="Critical"), context=None
        )
        escalate = next(p for p in proposals if p.action_type == ActionType.ESCALATE)
        assert escalate.is_destructive is True

    @pytest.mark.anyio
    async def test_refund_proposes_reply_destructive(self) -> None:
        proposals = await RuleBasedActionSuggester().suggest(
            ticket=_ticket(), analysis=_analysis(category="Refund"), context=None
        )
        reply = next(p for p in proposals if p.action_type == ActionType.SEND_REPLY)
        assert reply.is_destructive is True and "note" in reply.params


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


class TestHandlers:
    def test_registry_covers_every_action_type(self) -> None:
        handlers = build_action_handlers()
        assert set(handlers) == set(ActionType)

    def test_destructive_flags(self) -> None:
        handlers = build_action_handlers()
        assert handlers[ActionType.SEND_REPLY].is_destructive is True
        assert handlers[ActionType.ESCALATE].is_destructive is True
        assert handlers[ActionType.SET_STATUS].is_destructive is False

    @pytest.mark.anyio
    async def test_set_status_valid(self) -> None:
        ticket = _ticket()
        action = ResolutionAction(action_type="set_status", params={"status": "resolved"})
        result = await build_action_handlers()[ActionType.SET_STATUS].execute(action, _ctx(ticket))
        assert result.ok and ticket.status == "resolved"

    @pytest.mark.anyio
    async def test_set_status_invalid(self) -> None:
        ticket = _ticket()
        action = ResolutionAction(action_type="set_status", params={"status": "nope"})
        result = await build_action_handlers()[ActionType.SET_STATUS].execute(action, _ctx(ticket))
        assert result.ok is False and ticket.status == "open"

    @pytest.mark.anyio
    async def test_assign_and_clear(self) -> None:
        ticket = _ticket()
        handler = build_action_handlers()[ActionType.ASSIGN]
        await handler.execute(ResolutionAction(params={"assignee": "agent-1"}), _ctx(ticket))
        assert ticket.assignee == "agent-1"
        await handler.execute(ResolutionAction(params={}), _ctx(ticket))
        assert ticket.assignee is None

    @pytest.mark.anyio
    async def test_add_note(self) -> None:
        result = await build_action_handlers()[ActionType.ADD_NOTE].execute(
            ResolutionAction(params={"note": "hi"}), _ctx(_ticket())
        )
        assert result.ok and result.detail["note"] == "hi"

    @pytest.mark.anyio
    async def test_send_reply_dispatches(self) -> None:
        ticket = _ticket()
        ctx = _ctx(ticket)
        action = ResolutionAction(params={"note": "reply body"})
        action.id = uuid.uuid4()
        result = await build_action_handlers()[ActionType.SEND_REPLY].execute(action, ctx)
        assert result.ok
        assert ctx.dispatcher.dispatched[0][0] == "ticket.reply"  # type: ignore[attr-defined]

    @pytest.mark.anyio
    async def test_escalate_sets_status_and_dispatches(self) -> None:
        ticket = _ticket()
        ctx = _ctx(ticket)
        action = ResolutionAction(params={})
        action.id = uuid.uuid4()
        result = await build_action_handlers()[ActionType.ESCALATE].execute(action, ctx)
        assert result.ok and ticket.status == "in_progress"
        assert ctx.dispatcher.dispatched[0][0] == "ticket.escalated"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Service (suggest / approve / reject / execute + audit + safety)
# ---------------------------------------------------------------------------


class TestActionService:
    @pytest.mark.anyio
    async def test_suggest_persists_proposed_and_audits(self) -> None:
        service, actions, audit = _service()
        created = await service.suggest(
            organization_id=ORG, ticket=_ticket(), analysis=_analysis(), context=None
        )
        assert len(created) >= 2
        assert all(a.status == "proposed" for a in created)
        assert audit.events() == ["action.proposed"] * len(created)

    @pytest.mark.anyio
    async def test_execute_before_approval_is_blocked(self) -> None:
        # The core safety invariant: a proposed action cannot be executed.
        service, actions, _ = _service()
        [action] = await service.suggest(
            organization_id=ORG, ticket=_ticket(), analysis=None, context=None
        )
        with pytest.raises(InvalidActionTransition):
            await service.execute(action, _ctx(_ticket()), user_id=USER)
        assert action.status == "proposed"  # unchanged

    @pytest.mark.anyio
    async def test_approve_then_execute_internal(self) -> None:
        service, actions, audit = _service()
        ticket = _ticket()
        [action] = await service.suggest(
            organization_id=ORG, ticket=ticket, analysis=None, context=None
        )  # set_status -> in_progress
        await service.approve(action, user_id=USER)
        assert action.status == "approved" and action.approved_by == USER
        await service.execute(action, _ctx(ticket), user_id=USER)
        assert action.status == "executed"
        assert ticket.status == "in_progress"
        assert audit.events() == ["action.proposed", "action.approved", "action.executed"]

    @pytest.mark.anyio
    async def test_approve_then_execute_destructive_dispatches(self) -> None:
        service, _, audit = _service()
        ticket = _ticket()
        created = await service.suggest(
            organization_id=ORG, ticket=ticket, analysis=_analysis(priority="High"), context=None
        )
        escalate = next(a for a in created if a.action_type == "escalate")
        await service.approve(escalate, user_id=USER)
        ctx = _ctx(ticket)
        await service.execute(escalate, ctx, user_id=USER)
        assert escalate.status == "executed"
        assert ctx.dispatcher.dispatched  # type: ignore[attr-defined]

    @pytest.mark.anyio
    async def test_reject(self) -> None:
        service, _, audit = _service()
        [action] = await service.suggest(
            organization_id=ORG, ticket=_ticket(), analysis=None, context=None
        )
        await service.reject(action, user_id=USER)
        assert action.status == "rejected"
        assert "action.rejected" in audit.events()

    @pytest.mark.anyio
    async def test_double_approve_blocked(self) -> None:
        service, _, _ = _service()
        [action] = await service.suggest(
            organization_id=ORG, ticket=_ticket(), analysis=None, context=None
        )
        await service.approve(action, user_id=USER)
        with pytest.raises(InvalidActionTransition):
            await service.approve(action, user_id=USER)

    @pytest.mark.anyio
    async def test_handler_result_not_ok_marks_failed(self) -> None:
        service, _, audit = _service()
        ticket = _ticket()
        # add_note with an explicit invalid set_status action to force ok=False
        action = ResolutionAction(
            organization_id=ORG,
            ticket_id=ticket.id,
            action_type="set_status",
            params={"status": "bogus"},
            rationale="r",
            is_destructive=False,
            suggested_by="rule",
            status="approved",
        )
        action.id = uuid.uuid4()
        await service.execute(action, _ctx(ticket), user_id=USER)
        assert action.status == "failed"
        assert action.result is not None and "error" in action.result
        assert "action.failed" in audit.events()

    @pytest.mark.anyio
    async def test_handler_exception_marks_failed(self) -> None:
        raising = MagicMock()
        raising.execute = AsyncMock(side_effect=RuntimeError("boom"))
        handlers = {ActionType.ADD_NOTE: raising}
        service, _, audit = _service(handlers=handlers)
        action = ResolutionAction(
            organization_id=ORG,
            ticket_id=uuid.uuid4(),
            action_type="add_note",
            params={},
            rationale="r",
            is_destructive=False,
            suggested_by="rule",
            status="approved",
        )
        action.id = uuid.uuid4()
        await service.execute(action, _ctx(_ticket()), user_id=USER)
        assert action.status == "failed"
        assert "action.failed" in audit.events()

    @pytest.mark.anyio
    async def test_list_for_ticket(self) -> None:
        service, _, _ = _service()
        ticket = _ticket()
        await service.suggest(organization_id=ORG, ticket=ticket, analysis=None, context=None)
        listed = await service.list_for_ticket(ORG, ticket.id)
        assert len(listed) == 1


# ---------------------------------------------------------------------------
# SQLAlchemy stores (mocked session)
# ---------------------------------------------------------------------------


class TestSqlAlchemyActionStores:
    @pytest.mark.anyio
    async def test_action_create_flush_refresh(self) -> None:
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.refresh = AsyncMock()
        store = SqlAlchemyActionStore(session)
        action = await store.create(
            organization_id=ORG,
            ticket_id=uuid.uuid4(),
            analysis_id=None,
            action_type="add_note",
            params={"note": "x"},
            rationale="r",
            is_destructive=False,
            suggested_by="rule",
        )
        assert action.action_type == "add_note"
        session.add.assert_called_once()
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once()

    @pytest.mark.anyio
    async def test_action_get_and_list(self) -> None:
        rows = [
            ResolutionAction(organization_id=ORG, ticket_id=uuid.uuid4(), action_type="add_note")
        ]
        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.first.return_value = rows[0]
        result.scalars.return_value.all.return_value = rows
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyActionStore(session)
        assert await store.get_for_org(ORG, uuid.uuid4()) is rows[0]
        assert list(await store.list_for_ticket(ORG, uuid.uuid4())) == rows

    @pytest.mark.anyio
    async def test_audit_record_and_list(self) -> None:
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.refresh = AsyncMock()
        store = SqlAlchemyAuditStore(session)
        entry = await store.record(
            organization_id=ORG,
            actor_type="user",
            actor_id="u",
            action="action.approved",
            resource_type="resolution_action",
            resource_id=uuid.uuid4(),
            detail=None,
        )
        assert entry.action == "action.approved"
        session.flush.assert_awaited_once()

        rows = [AuditLog(organization_id=ORG, actor_type="user", action="x", resource_type="y")]
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        session.execute = AsyncMock(return_value=result)
        assert list(await store.list_for_org(ORG, limit=10, offset=0)) == rows
