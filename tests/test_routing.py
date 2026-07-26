"""
Tests for M3.4a: routing rules + SLA policies — the pure engine, the config CRUD
routes, and POST /v1/tickets/{id}/route (persisting assignee + sla_due_at).

Everything runs offline with in-memory fakes.
"""

import uuid
from collections.abc import Generator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.db.models import RoutingRule, SlaPolicy
from app.db.routing_store import SqlAlchemyRoutingRuleStore, SqlAlchemySlaPolicyStore
from app.routing.engine import RoutingEngine, SlaCalculator
from app.tenancy.base import TenantContext
from httpx import AsyncClient

from tests.test_tickets import ORG, FakeTicketStore, _ticket


def _rule(
    *,
    conditions: dict[str, str],
    actions: dict[str, Any],
    position: int = 0,
    active: bool = True,
) -> RoutingRule:
    rule = RoutingRule(
        organization_id=ORG, name="r", position=position, conditions=conditions, actions=actions
    )
    rule.id = uuid.uuid4()
    rule.active = active
    rule.created_at = datetime.now(UTC)
    return rule


def _policy(*, priority: str, minutes: int) -> SlaPolicy:
    policy = SlaPolicy(organization_id=ORG, priority=priority, resolution_minutes=minutes)
    policy.id = uuid.uuid4()
    policy.active = True
    policy.created_at = datetime.now(UTC)
    return policy


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class TestRoutingEngine:
    def test_first_matching_rule_wins(self) -> None:
        rules = [
            _rule(conditions={"category": "Refund"}, actions={"assignee": "refunds"}, position=0),
            _rule(
                conditions={"priority": "High"},
                actions={"assignee": "urgent", "tags": ["esc"]},
                position=1,
            ),
        ]
        decision = RoutingEngine.evaluate(category="Billing", priority="High", rules=rules)
        assert decision.assignee == "urgent"
        assert decision.tags == ("esc",)
        assert decision.matched_rule_id == rules[1].id

    def test_no_match_is_empty_decision(self) -> None:
        rules = [_rule(conditions={"category": "Refund"}, actions={"assignee": "x"})]
        decision = RoutingEngine.evaluate(category="Billing", priority="Low", rules=rules)
        assert (
            decision.assignee is None and decision.tags == () and decision.matched_rule_id is None
        )

    def test_empty_conditions_match_everything(self) -> None:
        rules = [_rule(conditions={}, actions={"assignee": "catch-all"})]
        assert (
            RoutingEngine.evaluate(category="Anything", priority="Low", rules=rules).assignee
            == "catch-all"
        )


class TestSlaCalculator:
    def test_due_at_from_matching_policy(self) -> None:
        base = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
        policies = [
            _policy(priority="Critical", minutes=60),
            _policy(priority="Low", minutes=10000),
        ]
        assert SlaCalculator.due_at(priority="Critical", policies=policies, base_time=base) == (
            base + timedelta(minutes=60)
        )

    def test_no_matching_policy_returns_none(self) -> None:
        assert (
            SlaCalculator.due_at(
                priority="High",
                policies=[_policy(priority="Low", minutes=1)],
                base_time=datetime.now(UTC),
            )
            is None
        )


# ---------------------------------------------------------------------------
# Fakes + config-CRUD / route fixtures
# ---------------------------------------------------------------------------


class FakeRuleStore:
    def __init__(self) -> None:
        self.rules: list[RoutingRule] = []

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        name: str,
        position: int,
        conditions: dict[str, str],
        actions: dict[str, Any],
    ) -> RoutingRule:
        rule = _rule(conditions=conditions, actions=actions, position=position)
        rule.organization_id = organization_id
        rule.name = name
        self.rules.append(rule)
        return rule

    async def list_by_org(self, organization_id: uuid.UUID) -> Sequence[RoutingRule]:
        return sorted(
            [r for r in self.rules if r.organization_id == organization_id],
            key=lambda r: r.position,
        )

    async def list_active(self, organization_id: uuid.UUID) -> Sequence[RoutingRule]:
        return [r for r in await self.list_by_org(organization_id) if r.active]

    async def delete(self, organization_id: uuid.UUID, rule_id: uuid.UUID) -> bool:
        before = len(self.rules)
        self.rules = [
            r for r in self.rules if not (r.id == rule_id and r.organization_id == organization_id)
        ]
        return len(self.rules) < before


class FakePolicyStore:
    def __init__(self) -> None:
        self.policies: list[SlaPolicy] = []

    async def create(
        self, *, organization_id: uuid.UUID, priority: str, resolution_minutes: int
    ) -> SlaPolicy:
        policy = _policy(priority=priority, minutes=resolution_minutes)
        policy.organization_id = organization_id
        self.policies.append(policy)
        return policy

    async def list_by_org(self, organization_id: uuid.UUID) -> Sequence[SlaPolicy]:
        return [p for p in self.policies if p.organization_id == organization_id]

    async def list_active(self, organization_id: uuid.UUID) -> Sequence[SlaPolicy]:
        return [p for p in await self.list_by_org(organization_id) if p.active]

    async def delete(self, organization_id: uuid.UUID, policy_id: uuid.UUID) -> bool:
        before = len(self.policies)
        self.policies = [
            p
            for p in self.policies
            if not (p.id == policy_id and p.organization_id == organization_id)
        ]
        return len(self.policies) < before


@pytest.fixture
def routing_overrides() -> Generator[dict[str, Any], None, None]:
    from app.dependencies import (
        get_routing_rule_store,
        get_sla_policy_store,
        get_tenant_context,
        get_ticket_store,
        require_org_membership,
    )
    from app.main import app
    from app.routing.routes import _require_owner_or_admin

    tickets = FakeTicketStore()
    rules = FakeRuleStore()
    policies = FakePolicyStore()
    context = TenantContext(organization_id=ORG, principal_type="api_key", scopes=("analyze",))
    membership = MagicMock()

    app.dependency_overrides[get_ticket_store] = lambda: tickets
    app.dependency_overrides[get_routing_rule_store] = lambda: rules
    app.dependency_overrides[get_sla_policy_store] = lambda: policies
    app.dependency_overrides[get_tenant_context] = lambda: context
    app.dependency_overrides[require_org_membership] = lambda: membership
    app.dependency_overrides[_require_owner_or_admin] = lambda: membership
    yield {"tickets": tickets, "rules": rules, "policies": policies}
    for dep in (
        get_ticket_store,
        get_routing_rule_store,
        get_sla_policy_store,
        get_tenant_context,
        require_org_membership,
        _require_owner_or_admin,
    ):
        app.dependency_overrides.pop(dep, None)


class TestRoutingConfigRoutes:
    @pytest.mark.anyio
    async def test_create_and_list_rule(
        self, client: AsyncClient, routing_overrides: dict[str, Any]
    ) -> None:
        resp = await client.post(
            f"/v1/orgs/{ORG}/routing-rules",
            json={
                "name": "billing",
                "position": 1,
                "conditions": {"category": "Billing"},
                "actions": {"assignee": "billing-team", "tags": ["vip"]},
            },
        )
        assert resp.status_code == 201
        assert resp.json()["conditions"] == {"category": "Billing"}
        listed = await client.get(f"/v1/orgs/{ORG}/routing-rules")
        assert len(listed.json()) == 1

    @pytest.mark.anyio
    async def test_delete_rule_then_404(
        self, client: AsyncClient, routing_overrides: dict[str, Any]
    ) -> None:
        rule = await routing_overrides["rules"].create(
            organization_id=ORG, name="r", position=0, conditions={}, actions={}
        )
        assert (await client.delete(f"/v1/orgs/{ORG}/routing-rules/{rule.id}")).status_code == 204
        assert (await client.delete(f"/v1/orgs/{ORG}/routing-rules/{rule.id}")).status_code == 404

    @pytest.mark.anyio
    async def test_create_and_delete_sla_policy(
        self, client: AsyncClient, routing_overrides: dict[str, Any]
    ) -> None:
        resp = await client.post(
            f"/v1/orgs/{ORG}/sla-policies",
            json={"priority": "Critical", "resolution_minutes": 60},
        )
        assert resp.status_code == 201
        policy_id = resp.json()["id"]
        assert (await client.get(f"/v1/orgs/{ORG}/sla-policies")).json()[0][
            "priority"
        ] == "Critical"
        assert (await client.delete(f"/v1/orgs/{ORG}/sla-policies/{policy_id}")).status_code == 204

    @pytest.mark.anyio
    async def test_bad_sla_minutes_422(
        self, client: AsyncClient, routing_overrides: dict[str, Any]
    ) -> None:
        resp = await client.post(
            f"/v1/orgs/{ORG}/sla-policies", json={"priority": "Low", "resolution_minutes": 0}
        )
        assert resp.status_code == 422


class TestRouteTicket:
    @pytest.mark.anyio
    async def test_route_persists_assignee_and_due(
        self, client: AsyncClient, routing_overrides: dict[str, Any]
    ) -> None:
        ticket = _ticket(analyses=1)  # latest analysis is Billing / High
        routing_overrides["tickets"].tickets = [ticket]
        await routing_overrides["rules"].create(
            organization_id=ORG,
            name="high",
            position=0,
            conditions={"priority": "High"},
            actions={"assignee": "urgent-team", "tags": ["esc"]},
        )
        await routing_overrides["policies"].create(
            organization_id=ORG, priority="High", resolution_minutes=120
        )

        resp = await client.post(f"/v1/tickets/{ticket.id}/route")
        assert resp.status_code == 200
        body = resp.json()
        assert body["assignee"] == "urgent-team"
        assert body["tags"] == ["esc"]
        assert body["sla_due_at"] is not None
        # Persisted on the ticket.
        assert ticket.assignee == "urgent-team"
        assert ticket.sla_due_at is not None

    @pytest.mark.anyio
    async def test_route_unknown_ticket_404(
        self, client: AsyncClient, routing_overrides: dict[str, Any]
    ) -> None:
        assert (await client.post(f"/v1/tickets/{uuid.uuid4()}/route")).status_code == 404

    @pytest.mark.anyio
    async def test_route_ticket_without_analysis_409(
        self, client: AsyncClient, routing_overrides: dict[str, Any]
    ) -> None:
        ticket = _ticket(analyses=0)
        routing_overrides["tickets"].tickets = [ticket]
        assert (await client.post(f"/v1/tickets/{ticket.id}/route")).status_code == 409


# ---------------------------------------------------------------------------
# SQLAlchemy stores (mocked session)
# ---------------------------------------------------------------------------


class TestSqlAlchemyRoutingStores:
    @pytest.mark.anyio
    async def test_rule_create_flushes(self) -> None:
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        store = SqlAlchemyRoutingRuleStore(session)
        rule = await store.create(
            organization_id=ORG, name="r", position=0, conditions={}, actions={}
        )
        assert rule.name == "r"
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    @pytest.mark.anyio
    async def test_rule_list_active_returns_scalars(self) -> None:
        rows = [_rule(conditions={}, actions={})]
        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyRoutingRuleStore(session)
        assert list(await store.list_active(ORG)) == rows

    @pytest.mark.anyio
    async def test_rule_list_by_org_returns_scalars(self) -> None:
        rows = [_rule(conditions={}, actions={})]
        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyRoutingRuleStore(session)
        assert list(await store.list_by_org(ORG)) == rows

    @pytest.mark.anyio
    async def test_rule_delete_rowcount(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(return_value=MagicMock(rowcount=1))
        store = SqlAlchemyRoutingRuleStore(session)
        assert await store.delete(ORG, uuid.uuid4()) is True

    @pytest.mark.anyio
    async def test_policy_create_and_delete(self) -> None:
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(rowcount=0))
        store = SqlAlchemySlaPolicyStore(session)
        policy = await store.create(organization_id=ORG, priority="Low", resolution_minutes=5)
        assert policy.priority == "Low"
        assert await store.delete(ORG, uuid.uuid4()) is False

    @pytest.mark.anyio
    async def test_policy_list_active_returns_scalars(self) -> None:
        rows = [_policy(priority="Low", minutes=5)]
        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemySlaPolicyStore(session)
        assert list(await store.list_active(ORG)) == rows

    @pytest.mark.anyio
    async def test_policy_list_by_org_returns_scalars(self) -> None:
        rows = [_policy(priority="Low", minutes=5)]
        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemySlaPolicyStore(session)
        assert list(await store.list_by_org(ORG)) == rows


class TestRoutingSchema:
    def test_tables_registered(self) -> None:
        from app.db.base import Base

        assert {"routing_rules", "sla_policies"} <= set(Base.metadata.tables)

    def test_ticket_has_routing_columns(self) -> None:
        from app.db.models import Ticket

        assert {"assignee", "sla_due_at"} <= set(Ticket.__table__.columns.keys())
