"""
Route + DI tests for the M5.3 action endpoints (step C): the suggest → approve →
execute human-in-the-loop flow, audit-log listing, tenant scoping, and the
approver authorization. Offline with in-memory fakes.
"""

import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

import pytest
from app.actions.service import ActionService
from app.actions.suggester import RuleBasedActionSuggester
from app.tenancy.base import TenantContext
from httpx import AsyncClient

from tests.test_actions import FakeActionStore, FakeAuditStore, FakeDispatcher
from tests.test_tickets import ORG, FakeTicketStore, _ticket

USER = uuid.uuid4()


@pytest.fixture
def action_overrides() -> Generator[dict[str, Any], None, None]:
    from app.actions.handlers import build_action_handlers
    from app.actions.routes import _require_owner_or_admin
    from app.dependencies import (
        get_action_service,
        get_audit_store,
        get_tenant_context,
        get_ticket_store,
        get_webhook_dispatcher,
        require_approver,
    )
    from app.main import app

    tickets = FakeTicketStore()
    actions = FakeActionStore()
    audit = FakeAuditStore()
    dispatcher = FakeDispatcher()
    service = ActionService(actions, audit, RuleBasedActionSuggester(), build_action_handlers())
    user_ctx = TenantContext(organization_id=ORG, principal_type="user", user_id=USER)

    app.dependency_overrides[get_ticket_store] = lambda: tickets
    app.dependency_overrides[get_action_service] = lambda: service
    app.dependency_overrides[get_audit_store] = lambda: audit
    app.dependency_overrides[get_tenant_context] = lambda: user_ctx
    app.dependency_overrides[require_approver] = lambda: user_ctx
    app.dependency_overrides[get_webhook_dispatcher] = lambda: dispatcher
    app.dependency_overrides[_require_owner_or_admin] = lambda: MagicMock()
    yield {"tickets": tickets, "actions": actions, "audit": audit, "dispatcher": dispatcher}
    for dep in (
        get_ticket_store,
        get_action_service,
        get_audit_store,
        get_tenant_context,
        require_approver,
        get_webhook_dispatcher,
        _require_owner_or_admin,
    ):
        app.dependency_overrides.pop(dep, None)


class TestActionRoutes:
    @pytest.mark.anyio
    async def test_suggest_lists_and_full_lifecycle(
        self, client: AsyncClient, action_overrides: dict[str, Any]
    ) -> None:
        ticket = _ticket(analyses=1)  # latest analysis Billing / High
        action_overrides["tickets"].tickets = [ticket]

        # Suggest → proposed actions.
        resp = await client.post(f"/v1/tickets/{ticket.id}/actions/suggest")
        assert resp.status_code == 201
        body = resp.json()
        assert body["ticket_id"] == str(ticket.id)
        assert len(body["actions"]) >= 2
        assert all(a["status"] == "proposed" for a in body["actions"])
        # A safe internal action to drive to execution.
        set_status = next(a for a in body["actions"] if a["action_type"] == "set_status")

        # List reflects the proposals.
        listed = await client.get(f"/v1/tickets/{ticket.id}/actions")
        assert listed.status_code == 200 and len(listed.json()) == len(body["actions"])

        # Execute before approval → 409 (the safety invariant, over HTTP).
        early = await client.post(f"/v1/tickets/{ticket.id}/actions/{set_status['id']}/execute")
        assert early.status_code == 409

        # Approve → approved.
        approved = await client.post(f"/v1/tickets/{ticket.id}/actions/{set_status['id']}/approve")
        assert approved.status_code == 200 and approved.json()["status"] == "approved"

        # Execute → executed + ticket mutated.
        executed = await client.post(f"/v1/tickets/{ticket.id}/actions/{set_status['id']}/execute")
        assert executed.status_code == 200 and executed.json()["status"] == "executed"
        assert ticket.status == "in_progress"

        # Audit trail recorded every transition.
        events = [e.action for e in action_overrides["audit"].entries]
        assert "action.proposed" in events
        assert "action.approved" in events
        assert "action.executed" in events

    @pytest.mark.anyio
    async def test_execute_destructive_dispatches_webhook(
        self, client: AsyncClient, action_overrides: dict[str, Any]
    ) -> None:
        ticket = _ticket(analyses=1)  # Billing/High → escalate proposed
        action_overrides["tickets"].tickets = [ticket]
        actions = (await client.post(f"/v1/tickets/{ticket.id}/actions/suggest")).json()["actions"]
        escalate = next(a for a in actions if a["action_type"] == "escalate")
        assert escalate["is_destructive"] is True
        await client.post(f"/v1/tickets/{ticket.id}/actions/{escalate['id']}/approve")
        resp = await client.post(f"/v1/tickets/{ticket.id}/actions/{escalate['id']}/execute")
        assert resp.status_code == 200
        assert action_overrides["dispatcher"].dispatched[0][0] == "ticket.escalated"

    @pytest.mark.anyio
    async def test_reject(self, client: AsyncClient, action_overrides: dict[str, Any]) -> None:
        ticket = _ticket(analyses=1)
        action_overrides["tickets"].tickets = [ticket]
        actions = (await client.post(f"/v1/tickets/{ticket.id}/actions/suggest")).json()["actions"]
        aid = actions[0]["id"]
        resp = await client.post(f"/v1/tickets/{ticket.id}/actions/{aid}/reject")
        assert resp.status_code == 200 and resp.json()["status"] == "rejected"

    @pytest.mark.anyio
    async def test_reject_after_approve_is_409(
        self, client: AsyncClient, action_overrides: dict[str, Any]
    ) -> None:
        ticket = _ticket(analyses=1)
        action_overrides["tickets"].tickets = [ticket]
        actions = (await client.post(f"/v1/tickets/{ticket.id}/actions/suggest")).json()["actions"]
        aid = actions[0]["id"]
        await client.post(f"/v1/tickets/{ticket.id}/actions/{aid}/approve")
        # An approved action can no longer be rejected (terminal-ish transition).
        resp = await client.post(f"/v1/tickets/{ticket.id}/actions/{aid}/reject")
        assert resp.status_code == 409

    @pytest.mark.anyio
    async def test_double_approve_is_409(
        self, client: AsyncClient, action_overrides: dict[str, Any]
    ) -> None:
        ticket = _ticket(analyses=1)
        action_overrides["tickets"].tickets = [ticket]
        actions = (await client.post(f"/v1/tickets/{ticket.id}/actions/suggest")).json()["actions"]
        aid = actions[0]["id"]
        await client.post(f"/v1/tickets/{ticket.id}/actions/{aid}/approve")
        resp = await client.post(f"/v1/tickets/{ticket.id}/actions/{aid}/approve")
        assert resp.status_code == 409

    @pytest.mark.anyio
    async def test_execute_missing_ticket_404(
        self, client: AsyncClient, action_overrides: dict[str, Any]
    ) -> None:
        # An approved action whose ticket is absent from the store → 404.
        from app.db.models import ResolutionAction

        ticket_id = uuid.uuid4()
        action = ResolutionAction(
            organization_id=ORG,
            ticket_id=ticket_id,
            action_type="add_note",
            params={},
            rationale="r",
            is_destructive=False,
            suggested_by="rule",
            status="approved",
        )
        action.id = uuid.uuid4()
        action_overrides["actions"].actions = [action]
        resp = await client.post(f"/v1/tickets/{ticket_id}/actions/{action.id}/execute")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_suggest_unknown_ticket_404(
        self, client: AsyncClient, action_overrides: dict[str, Any]
    ) -> None:
        resp = await client.post(f"/v1/tickets/{uuid.uuid4()}/actions/suggest")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_approve_unknown_action_404(
        self, client: AsyncClient, action_overrides: dict[str, Any]
    ) -> None:
        ticket = _ticket(analyses=1)
        action_overrides["tickets"].tickets = [ticket]
        resp = await client.post(f"/v1/tickets/{ticket.id}/actions/{uuid.uuid4()}/approve")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_list_actions_unknown_ticket_404(
        self, client: AsyncClient, action_overrides: dict[str, Any]
    ) -> None:
        assert (await client.get(f"/v1/tickets/{uuid.uuid4()}/actions")).status_code == 404

    @pytest.mark.anyio
    async def test_audit_logs_listing(
        self, client: AsyncClient, action_overrides: dict[str, Any]
    ) -> None:
        ticket = _ticket(analyses=1)
        action_overrides["tickets"].tickets = [ticket]
        await client.post(f"/v1/tickets/{ticket.id}/actions/suggest")
        resp = await client.get(f"/v1/orgs/{ORG}/audit-logs")
        assert resp.status_code == 200
        assert any(e["action"] == "action.proposed" for e in resp.json())


class TestRequireApprover:
    @pytest.mark.anyio
    async def test_api_key_principal_rejected(self) -> None:
        from app.dependencies import require_approver
        from fastapi import HTTPException

        ctx = TenantContext(organization_id=ORG, principal_type="api_key", scopes=("analyze",))
        with pytest.raises(HTTPException) as exc:
            await require_approver(context=ctx, org_store=MagicMock())
        assert exc.value.status_code == 403

    @pytest.mark.anyio
    async def test_non_privileged_member_rejected(self) -> None:
        from unittest.mock import AsyncMock

        from app.dependencies import require_approver
        from fastapi import HTTPException

        ctx = TenantContext(organization_id=ORG, principal_type="user", user_id=USER)
        org_store = MagicMock()
        org_store.get_membership = AsyncMock(return_value=MagicMock(role="agent"))
        with pytest.raises(HTTPException) as exc:
            await require_approver(context=ctx, org_store=org_store)
        assert exc.value.status_code == 403

    @pytest.mark.anyio
    async def test_owner_allowed(self) -> None:
        from unittest.mock import AsyncMock

        from app.dependencies import require_approver

        ctx = TenantContext(organization_id=ORG, principal_type="user", user_id=USER)
        org_store = MagicMock()
        org_store.get_membership = AsyncMock(return_value=MagicMock(role="owner"))
        assert await require_approver(context=ctx, org_store=org_store) is ctx
