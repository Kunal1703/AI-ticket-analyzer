"""
Tests for M2.5b: Stripe billing provider, idempotent signature-verified webhook
ingestion, plan sync, and the webhook event store.

The Stripe SDK is not installed in this environment, so ``StripeBillingProvider``
is exercised by injecting a fake ``stripe`` module into ``sys.modules``; the route
and service logic are tested with a ``FakeBillingProvider`` (no SDK involved).
"""

import sys
import types
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.billing.base import BillingProviderError
from app.billing.provider import (
    BillingEvent,
    BillingProvider,
    available_billing_providers,
    build_billing_provider,
)
from app.billing.service import WebhookService
from app.billing.stripe_provider import StripeBillingProvider
from app.config import Settings
from app.db.base import Base
from app.db.models import ProcessedWebhookEvent
from app.db.webhook_event_store import SqlAlchemyWebhookEventStore
from httpx import AsyncClient

from tests.test_tenancy_service import FakeOrgStore

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeWebhookEventStore:
    """In-memory ``WebhookEventStore``."""

    def __init__(self) -> None:
        self.seen: set[tuple[str, str]] = set()

    async def exists(self, *, provider: str, event_id: str) -> bool:
        return (provider, event_id) in self.seen

    async def record(
        self, *, provider: str, event_id: str, event_type: str
    ) -> ProcessedWebhookEvent:
        self.seen.add((provider, event_id))
        event = ProcessedWebhookEvent(provider=provider, event_id=event_id, event_type=event_type)
        event.id = uuid.uuid4()
        return event


class FakeBillingProvider(BillingProvider):
    """Returns a preset event, or raises a preset error."""

    def __init__(self, event: BillingEvent | None = None, error: Exception | None = None) -> None:
        self._event = event
        self._error = error

    @property
    def name(self) -> str:
        return "stripe"

    def parse_webhook(self, payload: bytes, signature_header: str) -> BillingEvent:
        if self._error is not None:
            raise self._error
        assert self._event is not None
        return self._event


# ---------------------------------------------------------------------------
# StripeBillingProvider (fake `stripe` module injected)
# ---------------------------------------------------------------------------


class _FakeSignatureError(Exception):
    pass


def _install_fake_stripe(
    monkeypatch: pytest.MonkeyPatch, *, result: Any = None, raises: Exception | None = None
) -> None:
    module = types.ModuleType("stripe")

    def construct_event(payload: bytes, sig: str, secret: str) -> Any:
        if raises is not None:
            raise raises
        return result

    module.error = types.SimpleNamespace(SignatureVerificationError=_FakeSignatureError)  # type: ignore[attr-defined]
    module.Webhook = types.SimpleNamespace(construct_event=construct_event)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "stripe", module)


def _provider() -> StripeBillingProvider:
    return StripeBillingProvider(webhook_secret="whsec_test", price_plan_map={"pro_key": "pro"})


class TestStripeProviderParsing:
    def test_subscription_updated_maps_plan_and_org(self, monkeypatch: pytest.MonkeyPatch) -> None:
        org_id = uuid.uuid4()
        event = {
            "id": "evt_1",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "metadata": {"organization_id": str(org_id)},
                    "customer": "cus_123",
                    "items": {"data": [{"price": {"lookup_key": "pro_key"}}]},
                }
            },
        }
        _install_fake_stripe(monkeypatch, result=event)
        parsed = _provider().parse_webhook(b"{}", "sig")
        assert parsed.event_id == "evt_1"
        assert parsed.type == "customer.subscription.updated"
        assert parsed.organization_id == org_id
        assert parsed.plan == "pro"
        assert parsed.customer_id == "cus_123"

    def test_subscription_deleted_downgrades_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        org_id = uuid.uuid4()
        event = {
            "id": "evt_2",
            "type": "customer.subscription.deleted",
            "data": {"object": {"metadata": {"organization_id": str(org_id)}, "customer": "c"}},
        }
        _install_fake_stripe(monkeypatch, result=event)
        parsed = _provider().parse_webhook(b"{}", "sig")
        assert parsed.plan == "free"  # default_plan

    def test_unknown_price_yields_no_plan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        event = {
            "id": "evt_3",
            "type": "customer.subscription.updated",
            "data": {"object": {"items": {"data": [{"price": {"id": "unmapped"}}]}}},
        }
        _install_fake_stripe(monkeypatch, result=event)
        parsed = _provider().parse_webhook(b"{}", "sig")
        assert parsed.plan is None
        assert parsed.organization_id is None  # no metadata

    def test_signature_error_is_translated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_stripe(monkeypatch, raises=_FakeSignatureError("bad sig"))
        with pytest.raises(BillingProviderError):
            _provider().parse_webhook(b"{}", "sig")

    def test_malformed_payload_is_translated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_stripe(monkeypatch, raises=ValueError("bad json"))
        with pytest.raises(BillingProviderError):
            _provider().parse_webhook(b"{}", "sig")

    def test_checkout_completed_uses_metadata_plan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        event = {
            "id": "evt_co",
            "type": "checkout.session.completed",
            "data": {"object": {"metadata": {"plan": "enterprise"}, "customer": "cus_x"}},
        }
        _install_fake_stripe(monkeypatch, result=event)
        parsed = _provider().parse_webhook(b"{}", "sig")
        assert parsed.plan == "enterprise"

    def test_non_uuid_org_metadata_is_dropped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        event = {
            "id": "evt_bad",
            "type": "customer.subscription.deleted",
            "data": {"object": {"metadata": {"organization_id": "not-a-uuid"}}},
        }
        _install_fake_stripe(monkeypatch, result=event)
        parsed = _provider().parse_webhook(b"{}", "sig")
        assert parsed.organization_id is None

    def test_provider_name(self) -> None:
        assert _provider().name == "stripe"

    def test_missing_sdk_is_translated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # No fake installed and the real package is absent → import fails.
        monkeypatch.setitem(sys.modules, "stripe", None)
        with pytest.raises(BillingProviderError):
            _provider().parse_webhook(b"{}", "sig")


class TestBillingProviderFactory:
    def test_registry_lists_stripe(self) -> None:
        assert available_billing_providers() == ["stripe"]

    def test_build_stripe_when_configured(self) -> None:
        settings = Settings(  # type: ignore[call-arg]
            _env_file=None,
            stripe_webhook_secret="whsec_test",
            stripe_price_plan_map={"k": "pro"},
        )
        provider = build_billing_provider(settings)
        assert isinstance(provider, StripeBillingProvider)
        assert provider.name == "stripe"

    def test_build_without_secret_raises(self) -> None:
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        with pytest.raises(BillingProviderError):
            build_billing_provider(settings)

    def test_build_unknown_provider_raises(self) -> None:
        settings = Settings(_env_file=None, billing_provider="paypal")  # type: ignore[call-arg]
        with pytest.raises(ValueError, match="Unsupported billing provider"):
            build_billing_provider(settings)


# ---------------------------------------------------------------------------
# WebhookService
# ---------------------------------------------------------------------------


async def _make_org(orgs: FakeOrgStore) -> Any:
    return await orgs.create(name="Acme", slug="acme", owner_id=uuid.uuid4())


class TestWebhookService:
    @pytest.mark.anyio
    async def test_plan_updated_and_customer_linked(self) -> None:
        orgs = FakeOrgStore()
        org = await _make_org(orgs)
        event = BillingEvent(
            provider="stripe",
            event_id="evt_1",
            type="customer.subscription.updated",
            organization_id=org.id,
            plan="pro",
            customer_id="cus_9",
        )
        service = WebhookService(FakeBillingProvider(event=event), FakeWebhookEventStore(), orgs)
        assert await service.handle(b"{}", "sig") == "plan_updated"
        assert org.plan == "pro"
        assert org.stripe_customer_id == "cus_9"

    @pytest.mark.anyio
    async def test_duplicate_event_is_ignored(self) -> None:
        orgs = FakeOrgStore()
        org = await _make_org(orgs)
        events = FakeWebhookEventStore()
        events.seen.add(("stripe", "evt_dup"))
        event = BillingEvent(
            provider="stripe",
            event_id="evt_dup",
            type="customer.subscription.updated",
            organization_id=org.id,
            plan="pro",
        )
        service = WebhookService(FakeBillingProvider(event=event), events, orgs)
        assert await service.handle(b"{}", "sig") == "duplicate"
        assert org.plan == "free"  # unchanged

    @pytest.mark.anyio
    async def test_event_without_org_or_plan_is_ignored(self) -> None:
        service = WebhookService(
            FakeBillingProvider(event=BillingEvent(provider="stripe", event_id="e", type="ping")),
            FakeWebhookEventStore(),
            FakeOrgStore(),
        )
        assert await service.handle(b"{}", "sig") == "ignored"

    @pytest.mark.anyio
    async def test_unknown_org_is_ignored(self) -> None:
        event = BillingEvent(
            provider="stripe",
            event_id="e",
            type="customer.subscription.updated",
            organization_id=uuid.uuid4(),
            plan="pro",
        )
        service = WebhookService(
            FakeBillingProvider(event=event), FakeWebhookEventStore(), FakeOrgStore()
        )
        assert await service.handle(b"{}", "sig") == "ignored"

    @pytest.mark.anyio
    async def test_provider_error_propagates(self) -> None:
        service = WebhookService(
            FakeBillingProvider(error=BillingProviderError("bad")),
            FakeWebhookEventStore(),
            FakeOrgStore(),
        )
        with pytest.raises(BillingProviderError):
            await service.handle(b"{}", "sig")


# ---------------------------------------------------------------------------
# Webhook route
# ---------------------------------------------------------------------------


@pytest.fixture
def webhook_service_override() -> Generator[dict[str, Any], None, None]:
    from app.dependencies import get_webhook_service
    from app.main import app

    orgs = FakeOrgStore()
    events = FakeWebhookEventStore()
    state: dict[str, Any] = {"provider": FakeBillingProvider(), "orgs": orgs, "events": events}

    def _factory() -> WebhookService:
        return WebhookService(state["provider"], events, orgs)

    app.dependency_overrides[get_webhook_service] = _factory
    yield state
    app.dependency_overrides.pop(get_webhook_service, None)


class TestWebhookRoute:
    @pytest.mark.anyio
    async def test_plan_updated_returns_200(
        self, client: AsyncClient, webhook_service_override: dict[str, Any]
    ) -> None:
        orgs: FakeOrgStore = webhook_service_override["orgs"]
        org = await _make_org(orgs)
        webhook_service_override["provider"] = FakeBillingProvider(
            event=BillingEvent(
                provider="stripe",
                event_id="evt_1",
                type="customer.subscription.updated",
                organization_id=org.id,
                plan="pro",
            )
        )
        resp = await client.post(
            "/v1/billing/webhook", content=b"{}", headers={"Stripe-Signature": "sig"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "plan_updated"
        assert org.plan == "pro"

    @pytest.mark.anyio
    async def test_invalid_signature_returns_400(
        self, client: AsyncClient, webhook_service_override: dict[str, Any]
    ) -> None:
        webhook_service_override["provider"] = FakeBillingProvider(
            error=BillingProviderError("bad sig")
        )
        resp = await client.post(
            "/v1/billing/webhook", content=b"{}", headers={"Stripe-Signature": "nope"}
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "bad_request"

    @pytest.mark.anyio
    async def test_duplicate_returns_200_ignored(
        self, client: AsyncClient, webhook_service_override: dict[str, Any]
    ) -> None:
        webhook_service_override["events"].seen.add(("stripe", "evt_dup"))
        webhook_service_override["provider"] = FakeBillingProvider(
            event=BillingEvent(provider="stripe", event_id="evt_dup", type="ping")
        )
        resp = await client.post(
            "/v1/billing/webhook", content=b"{}", headers={"Stripe-Signature": "sig"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "duplicate"

    @pytest.mark.anyio
    async def test_returns_503_when_billing_not_configured(self, client: AsyncClient) -> None:
        # No override: the default app has no stripe secret (billing_provider is None).
        from app.dependencies import get_org_store, get_webhook_event_store
        from app.main import app

        app.dependency_overrides[get_webhook_event_store] = lambda: FakeWebhookEventStore()
        app.dependency_overrides[get_org_store] = lambda: FakeOrgStore()
        try:
            resp = await client.post(
                "/v1/billing/webhook", content=b"{}", headers={"Stripe-Signature": "sig"}
            )
            assert resp.status_code == 503
        finally:
            app.dependency_overrides.pop(get_webhook_event_store, None)
            app.dependency_overrides.pop(get_org_store, None)


# ---------------------------------------------------------------------------
# SqlAlchemyWebhookEventStore (mocked session) + schema
# ---------------------------------------------------------------------------


class TestSqlAlchemyWebhookEventStore:
    @pytest.mark.anyio
    async def test_exists_true_when_row_found(self) -> None:
        session = MagicMock()
        result = MagicMock()
        result.first.return_value = (uuid.uuid4(),)
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyWebhookEventStore(session)
        assert await store.exists(provider="stripe", event_id="evt_1") is True

    @pytest.mark.anyio
    async def test_record_adds_and_flushes(self) -> None:
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        store = SqlAlchemyWebhookEventStore(session)
        row = await store.record(provider="stripe", event_id="evt_1", event_type="t")
        assert row.event_id == "evt_1"
        session.add.assert_called_once()
        session.flush.assert_awaited_once()


class TestBillingWebhookSchema:
    def test_table_registered(self) -> None:
        assert "processed_webhook_events" in Base.metadata.tables

    def test_org_has_stripe_customer_id(self) -> None:
        from app.db.models import Organization

        assert "stripe_customer_id" in Organization.__table__.columns
