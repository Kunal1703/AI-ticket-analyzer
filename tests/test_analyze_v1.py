"""
Tests for M2.4: tenant-scoped /v1/analyze, API-key scope enforcement, RBAC on
API-key management, and the shared run_analysis orchestration.

All stores/provider are overridden with fakes/mocks — no live infra required.
"""

import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.ai import AnalysisResult
from app.auth.tokens import TokenService
from app.billing.plans import build_plans
from app.billing.service import BillingService
from app.db.models import Membership
from app.models import TicketAnalysis, TicketCategory, TicketPriority
from httpx import AsyncClient

from tests.test_auth import FakeUserStore
from tests.test_billing import FakeUsageStore
from tests.test_tenancy_service import FakeApiKeyStore, FakeOrgStore


def _analysis() -> TicketAnalysis:
    return TicketAnalysis(
        summary="Customer charged twice.",
        category=TicketCategory.BILLING,
        priority=TicketPriority.HIGH,
        next_actions=["Verify payment"],
    )


def _mock_provider() -> MagicMock:
    provider = MagicMock()
    provider.name = "test"
    provider.model = "test-model"
    provider.analyze = AsyncMock(return_value=AnalysisResult(analysis=_analysis()))
    return provider


_TID_ORG = uuid.uuid4()


class _FakeSession:
    """Minimal async-context session stand-in for persist/resolve unit tests."""

    def __init__(self, first_result: Any) -> None:
        self._first = first_result

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def execute(self, _stmt: Any) -> MagicMock:
        result = MagicMock()
        result.scalars.return_value.first.return_value = self._first
        return result

    def add(self, _obj: Any) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass


def _sessionmaker(first_result: Any) -> MagicMock:
    """A sessionmaker whose session resolves ``scalars().first()`` to ``first_result``."""
    return MagicMock(return_value=_FakeSession(first_result))


@pytest.fixture
def v1_overrides() -> Generator[dict[str, Any], None, None]:
    from app.dependencies import (
        get_analysis_provider,
        get_api_key_store,
        get_billing_service,
        get_optional_token_service,
        get_org_store,
        get_token_service,
        get_user_store,
    )
    from app.main import app

    stores = {"users": FakeUserStore(), "orgs": FakeOrgStore(), "keys": FakeApiKeyStore()}
    usage_store = FakeUsageStore()
    provider = _mock_provider()
    token_service = TokenService("test-secret-key")
    app.dependency_overrides[get_user_store] = lambda: stores["users"]
    app.dependency_overrides[get_org_store] = lambda: stores["orgs"]
    app.dependency_overrides[get_api_key_store] = lambda: stores["keys"]
    app.dependency_overrides[get_token_service] = lambda: token_service
    app.dependency_overrides[get_optional_token_service] = lambda: token_service
    app.dependency_overrides[get_analysis_provider] = lambda: provider
    # Quota enforcement needs a billing service; back it with an in-memory store
    # and the default (placeholder) plans so ordinary tests stay under the cap.
    app.dependency_overrides[get_billing_service] = lambda: BillingService(usage_store)
    yield {"stores": stores, "usage_store": usage_store, "provider": provider}
    for dep in (
        get_user_store,
        get_org_store,
        get_api_key_store,
        get_token_service,
        get_optional_token_service,
        get_analysis_provider,
        get_billing_service,
    ):
        app.dependency_overrides.pop(dep, None)


async def _signup(client: AsyncClient, email: str) -> str:
    resp = await client.post("/v1/auth/signup", json={"email": email, "password": "password123"})
    assert resp.status_code == 201
    return str(resp.json()["access_token"])


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestV1Analyze:
    @pytest.mark.anyio
    async def test_via_api_key(self, client: AsyncClient, v1_overrides: dict[str, Any]) -> None:
        token = await _signup(client, "owner@example.com")
        org = (await client.post("/v1/orgs", json={"name": "Acme"}, headers=_bearer(token))).json()
        key = (
            await client.post(
                f"/v1/orgs/{org['id']}/api-keys",
                json={"name": "ci", "scopes": ["analyze"]},
                headers=_bearer(token),
            )
        ).json()["api_key"]

        resp = await client.post(
            "/v1/analyze", json={"ticket": "I was charged twice."}, headers={"X-API-Key": key}
        )
        assert resp.status_code == 200
        assert resp.json()["category"] == "Billing"

    @pytest.mark.anyio
    async def test_via_user_jwt(self, client: AsyncClient, v1_overrides: dict[str, Any]) -> None:
        token = await _signup(client, "u@example.com")
        await client.post("/v1/orgs", json={"name": "Acme"}, headers=_bearer(token))
        resp = await client.post("/v1/analyze", json={"ticket": "help"}, headers=_bearer(token))
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_response_includes_ticket_id_field(
        self, client: AsyncClient, v1_overrides: dict[str, Any]
    ) -> None:
        # M3.6: /v1/analyze returns ticket_id (null here, since no DB is configured).
        token = await _signup(client, "tid@example.com")
        await client.post("/v1/orgs", json={"name": "Acme"}, headers=_bearer(token))
        resp = await client.post(
            "/v1/analyze", json={"ticket": "deep-link me"}, headers=_bearer(token)
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "ticket_id" in body
        assert body["ticket_id"] is None

    @pytest.mark.anyio
    async def test_api_key_without_scope_is_forbidden(
        self, client: AsyncClient, v1_overrides: dict[str, Any]
    ) -> None:
        token = await _signup(client, "owner2@example.com")
        org = (await client.post("/v1/orgs", json={"name": "Acme"}, headers=_bearer(token))).json()
        key = (
            await client.post(
                f"/v1/orgs/{org['id']}/api-keys",
                json={"name": "readonly", "scopes": ["read"]},  # no "analyze"
                headers=_bearer(token),
            )
        ).json()["api_key"]

        resp = await client.post("/v1/analyze", json={"ticket": "x"}, headers={"X-API-Key": key})
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_requires_auth(self, client: AsyncClient, v1_overrides: dict[str, Any]) -> None:
        assert (await client.post("/v1/analyze", json={"ticket": "x"})).status_code == 401

    @pytest.mark.anyio
    async def test_over_quota_returns_402(
        self, client: AsyncClient, v1_overrides: dict[str, Any]
    ) -> None:
        from app.dependencies import get_billing_service
        from app.main import app

        token = await _signup(client, "capped@example.com")
        org = (await client.post("/v1/orgs", json={"name": "Acme"}, headers=_bearer(token))).json()
        key = (
            await client.post(
                f"/v1/orgs/{org['id']}/api-keys",
                json={"name": "ci", "scopes": ["analyze"]},
                headers=_bearer(token),
            )
        ).json()["api_key"]

        # A zero-limit plan means the org is at quota immediately.
        capped = BillingService(FakeUsageStore(), build_plans({"free": 0}))
        app.dependency_overrides[get_billing_service] = lambda: capped

        resp = await client.post(
            "/v1/analyze", json={"ticket": "over cap"}, headers={"X-API-Key": key}
        )
        assert resp.status_code == 402
        assert resp.json()["error"]["code"] == "payment_required"

    @pytest.mark.anyio
    async def test_analysis_is_metered(
        self, client: AsyncClient, v1_overrides: dict[str, Any]
    ) -> None:
        # Metering runs inside run_analysis via the app sessionmaker (None in tests),
        # so it no-ops here; assert the request still succeeds and the mock provider
        # was actually invoked (a real, meterable analysis, not a cache hit).
        token = await _signup(client, "metered@example.com")
        org = (await client.post("/v1/orgs", json={"name": "Acme"}, headers=_bearer(token))).json()
        key = (
            await client.post(
                f"/v1/orgs/{org['id']}/api-keys",
                json={"name": "ci", "scopes": ["analyze"]},
                headers=_bearer(token),
            )
        ).json()["api_key"]

        resp = await client.post(
            "/v1/analyze", json={"ticket": "meter me"}, headers={"X-API-Key": key}
        )
        assert resp.status_code == 200
        assert v1_overrides["provider"].analyze.await_count == 1

    @pytest.mark.anyio
    async def test_legacy_analyze_still_unauthenticated(
        self, client: AsyncClient, override_provider: Any
    ) -> None:
        # Regression: legacy /analyze must keep working without auth.
        provider = _mock_provider()
        override_provider(provider)
        resp = await client.post("/analyze", json={"ticket": "legacy"})
        assert resp.status_code == 200
        assert resp.json()["category"] == "Billing"


class TestUsageEndpoint:
    @pytest.mark.anyio
    async def test_usage_reports_plan_and_limit(
        self, client: AsyncClient, v1_overrides: dict[str, Any]
    ) -> None:
        token = await _signup(client, "usage@example.com")
        org = (await client.post("/v1/orgs", json={"name": "Acme"}, headers=_bearer(token))).json()
        resp = await client.get(f"/v1/orgs/{org['id']}/usage", headers=_bearer(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["plan"] == "free"
        assert body["used"] == 0
        assert body["limit"] == 100  # placeholder free limit
        assert body["period_start"].endswith("+00:00")

    @pytest.mark.anyio
    async def test_usage_requires_membership(
        self, client: AsyncClient, v1_overrides: dict[str, Any]
    ) -> None:
        owner = await _signup(client, "usage-owner@example.com")
        org = (await client.post("/v1/orgs", json={"name": "Acme"}, headers=_bearer(owner))).json()
        outsider = await _signup(client, "outsider@example.com")
        resp = await client.get(f"/v1/orgs/{org['id']}/usage", headers=_bearer(outsider))
        assert resp.status_code == 403


class TestApiKeyRbac:
    @pytest.mark.anyio
    async def test_non_privileged_member_cannot_create_key(
        self, client: AsyncClient, v1_overrides: dict[str, Any]
    ) -> None:
        owner_token = await _signup(client, "owner3@example.com")
        org = (
            await client.post("/v1/orgs", json={"name": "Acme"}, headers=_bearer(owner_token))
        ).json()

        # A second user joins the org as a low-privilege "agent".
        member_token = await _signup(client, "agent@example.com")
        stores = v1_overrides["stores"]
        agent = stores["users"]._by_email["agent@example.com"]
        stores["orgs"].memberships.append(
            Membership(organization_id=uuid.UUID(org["id"]), user_id=agent.id, role="agent")
        )

        resp = await client.post(
            f"/v1/orgs/{org['id']}/api-keys", json={"name": "x"}, headers=_bearer(member_token)
        )
        assert resp.status_code == 403  # insufficient role


class TestRunAnalysis:
    @pytest.mark.anyio
    async def test_cache_is_namespaced_by_org(self) -> None:
        from app.cache.memory import TTLCache
        from app.services.analyze import run_analysis

        cache = TTLCache(ttl_seconds=300)
        provider = _mock_provider()
        org_a, org_b = uuid.uuid4(), uuid.uuid4()

        await run_analysis(
            ticket_text="same",
            provider=provider,
            cache=cache,
            sessionmaker=None,
            organization_id=org_a,
        )
        # Same text, different org → cache miss → provider called again.
        await run_analysis(
            ticket_text="same",
            provider=provider,
            cache=cache,
            sessionmaker=None,
            organization_id=org_b,
        )
        assert provider.analyze.await_count == 2
        # Same org again → cache hit → provider NOT called again.
        await run_analysis(
            ticket_text="same",
            provider=provider,
            cache=cache,
            sessionmaker=None,
            organization_id=org_a,
        )
        assert provider.analyze.await_count == 2

    @pytest.mark.anyio
    async def test_legacy_cache_hit(self) -> None:
        from app.cache.memory import TTLCache
        from app.services.analyze import run_analysis

        cache = TTLCache(ttl_seconds=300)
        provider = _mock_provider()
        await run_analysis(ticket_text="hi", provider=provider, cache=cache, sessionmaker=None)
        await run_analysis(ticket_text="hi", provider=provider, cache=cache, sessionmaker=None)
        assert provider.analyze.await_count == 1  # second call served from cache


class TestTicketIdSurfacing:
    """M3.6: persist/resolve return the ticket id so endpoints can deep-link."""

    @pytest.mark.anyio
    async def test_persist_returns_ticket_id(self) -> None:
        from app.db.models import Ticket
        from app.services.analysis_service import persist_analysis

        existing = Ticket(raw_text="x", text_hash="h")
        existing.id = uuid.uuid4()
        tid = await persist_analysis(
            _sessionmaker(existing),
            ticket_text="x",
            text_hash="h",
            analysis=_analysis(),
            organization_id=_TID_ORG,
        )
        assert tid == existing.id

    @pytest.mark.anyio
    async def test_persist_returns_none_without_db(self) -> None:
        from app.services.analysis_service import persist_analysis

        tid = await persist_analysis(None, ticket_text="x", text_hash="h", analysis=_analysis())
        assert tid is None

    @pytest.mark.anyio
    async def test_resolve_ticket_id(self) -> None:
        from app.services.analysis_service import resolve_ticket_id

        expected = uuid.uuid4()
        got = await resolve_ticket_id(
            _sessionmaker(expected), text_hash="h", organization_id=_TID_ORG
        )
        assert got == expected

    @pytest.mark.anyio
    async def test_resolve_none_without_db(self) -> None:
        from app.services.analysis_service import resolve_ticket_id

        got = await resolve_ticket_id(None, text_hash="h", organization_id=_TID_ORG)
        assert got is None

    @pytest.mark.anyio
    async def test_run_analysis_outcome_without_db(self) -> None:
        from app.cache.memory import TTLCache
        from app.services.analyze import run_analysis

        outcome = await run_analysis(
            ticket_text="x",
            provider=_mock_provider(),
            cache=TTLCache(ttl_seconds=300),
            sessionmaker=None,
            organization_id=_TID_ORG,
        )
        assert outcome.ticket_id is None
        assert outcome.analysis.category == TicketCategory.BILLING
