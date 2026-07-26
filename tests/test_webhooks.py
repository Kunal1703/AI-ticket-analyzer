"""
Tests for M3.3b: outbound webhooks — signing, the dispatcher (bounded inline
retries), registration routes, and the batch.completed delivery wiring.

Everything runs offline: the HTTP client is a fake, and the stores are in-memory
fakes. A skipif round-trip covers the real webhook store.
"""

import os
import uuid
from collections.abc import Generator, Sequence
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.db.models import Webhook, WebhookDelivery
from app.db.webhook_store import SqlAlchemyWebhookStore
from app.webhooks.base import EVENT_BATCH_COMPLETED
from app.webhooks.dispatcher import HttpWebhookDispatcher, NoOpWebhookDispatcher
from app.webhooks.signing import (
    WEBHOOK_SIGNATURE_HEADER,
    compute_signature,
    generate_webhook_secret,
    signature_header,
)
from httpx import AsyncClient

from tests.test_tickets import ORG

DB_URL = os.environ.get("DATABASE_URL")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeWebhookStore:
    def __init__(self) -> None:
        self.webhooks: list[Webhook] = []

    def _add(self, *, url: str, event_types: list[str], active: bool = True) -> Webhook:
        hook = Webhook(organization_id=ORG, url=url, secret="whsec_x", event_types=event_types)
        hook.id = uuid.uuid4()
        hook.active = active
        hook.created_at = datetime.now(UTC)
        self.webhooks.append(hook)
        return hook

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        url: str,
        secret: str,
        event_types: list[str],
    ) -> Webhook:
        hook = self._add(url=url, event_types=event_types)
        hook.organization_id = organization_id
        hook.secret = secret
        return hook

    async def list_by_org(self, organization_id: uuid.UUID) -> Sequence[Webhook]:
        return [w for w in self.webhooks if w.organization_id == organization_id]

    async def get(self, organization_id: uuid.UUID, webhook_id: uuid.UUID) -> Webhook | None:
        return next(
            (
                w
                for w in self.webhooks
                if w.id == webhook_id and w.organization_id == organization_id
            ),
            None,
        )

    async def delete(self, organization_id: uuid.UUID, webhook_id: uuid.UUID) -> bool:
        hook = await self.get(organization_id, webhook_id)
        if hook is None:
            return False
        self.webhooks.remove(hook)
        return True

    async def list_active_for_event(
        self, organization_id: uuid.UUID, event_type: str
    ) -> Sequence[Webhook]:
        return [
            w
            for w in self.webhooks
            if w.organization_id == organization_id
            and w.active
            and event_type in (w.event_types or [])
        ]


class FakeDeliveryStore:
    def __init__(self) -> None:
        self.deliveries: list[WebhookDelivery] = []

    async def create(
        self,
        *,
        webhook_id: uuid.UUID,
        organization_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> WebhookDelivery:
        delivery = WebhookDelivery(
            webhook_id=webhook_id,
            organization_id=organization_id,
            event_type=event_type,
            payload=payload,
            status="pending",
            attempts=0,
        )
        delivery.id = uuid.uuid4()
        self.deliveries.append(delivery)
        return delivery

    async def update(
        self,
        delivery_id: uuid.UUID,
        *,
        status: str,
        attempts: int,
        response_status: int | None,
        error: str | None,
    ) -> None:
        for d in self.deliveries:
            if d.id == delivery_id:
                d.status = status
                d.attempts = attempts
                d.response_status = response_status
                d.error = error


class FakeHttpClient:
    """Returns queued responses (int status) or raises queued exceptions."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    async def post(
        self, url: str, *, content: bytes, headers: dict[str, str], timeout: float
    ) -> Any:
        self.calls.append({"url": url, "content": content, "headers": headers})
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return MagicMock(status_code=outcome)


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------


class TestSigning:
    def test_secret_has_prefix(self) -> None:
        assert generate_webhook_secret().startswith("whsec_")

    def test_signature_is_deterministic_and_verifiable(self) -> None:
        body = b'{"a":1}'
        header = signature_header("sekret", body, timestamp=1000)
        assert header.startswith("t=1000,v1=")
        expected = compute_signature("sekret", body, 1000)
        assert header == f"t=1000,v1={expected}"
        # A different secret yields a different signature.
        assert compute_signature("other", body, 1000) != expected


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def _dispatcher(
    store: FakeWebhookStore, deliveries: FakeDeliveryStore, client: FakeHttpClient
) -> HttpWebhookDispatcher:
    return HttpWebhookDispatcher(
        store, deliveries, client, max_attempts=3, timeout_seconds=1.0, backoff_base_seconds=0.0
    )


class TestDispatcher:
    @pytest.mark.anyio
    async def test_delivers_signed_payload(self) -> None:
        store = FakeWebhookStore()
        hook = store._add(url="https://example.test/hook", event_types=[EVENT_BATCH_COMPLETED])
        hook.secret = "s3cret"
        deliveries = FakeDeliveryStore()
        client = FakeHttpClient([200])
        await _dispatcher(store, deliveries, client).dispatch(
            organization_id=ORG, event_type=EVENT_BATCH_COMPLETED, payload={"job_id": "1"}
        )
        assert len(client.calls) == 1
        # The payload is signed with the hook's secret.
        sig = client.calls[0]["headers"][WEBHOOK_SIGNATURE_HEADER]
        assert sig.startswith("t=")
        assert deliveries.deliveries[0].status == "delivered"
        assert deliveries.deliveries[0].attempts == 1

    @pytest.mark.anyio
    async def test_retries_then_succeeds(self) -> None:
        store = FakeWebhookStore()
        store._add(url="https://x.test", event_types=[EVENT_BATCH_COMPLETED])
        deliveries = FakeDeliveryStore()
        client = FakeHttpClient([500, RuntimeError("conn reset"), 204])
        await _dispatcher(store, deliveries, client).dispatch(
            organization_id=ORG, event_type=EVENT_BATCH_COMPLETED, payload={}
        )
        assert len(client.calls) == 3
        assert deliveries.deliveries[0].status == "delivered"
        assert deliveries.deliveries[0].attempts == 3

    @pytest.mark.anyio
    async def test_exhausts_retries_and_marks_failed(self) -> None:
        store = FakeWebhookStore()
        store._add(url="https://x.test", event_types=[EVENT_BATCH_COMPLETED])
        deliveries = FakeDeliveryStore()
        client = FakeHttpClient([500, 500, 500])
        await _dispatcher(store, deliveries, client).dispatch(
            organization_id=ORG, event_type=EVENT_BATCH_COMPLETED, payload={}
        )
        d = deliveries.deliveries[0]
        assert d.status == "failed" and d.attempts == 3 and d.response_status == 500

    @pytest.mark.anyio
    async def test_unsubscribed_event_is_skipped(self) -> None:
        store = FakeWebhookStore()
        store._add(url="https://x.test", event_types=["something.else"])
        deliveries = FakeDeliveryStore()
        client = FakeHttpClient([])
        await _dispatcher(store, deliveries, client).dispatch(
            organization_id=ORG, event_type=EVENT_BATCH_COMPLETED, payload={}
        )
        assert client.calls == [] and deliveries.deliveries == []

    @pytest.mark.anyio
    async def test_noop_dispatcher_does_nothing(self) -> None:
        await NoOpWebhookDispatcher().dispatch(
            organization_id=ORG, event_type=EVENT_BATCH_COMPLETED, payload={}
        )

    @pytest.mark.anyio
    async def test_webhook_lookup_error_is_swallowed(self) -> None:
        store = FakeWebhookStore()
        store.list_active_for_event = AsyncMock(side_effect=RuntimeError("db down"))  # type: ignore[method-assign]
        deliveries = FakeDeliveryStore()
        # Must not raise (a batch must complete even if webhook loading fails).
        await _dispatcher(store, deliveries, FakeHttpClient([])).dispatch(
            organization_id=ORG, event_type=EVENT_BATCH_COMPLETED, payload={}
        )
        assert deliveries.deliveries == []

    @pytest.mark.anyio
    async def test_single_delivery_crash_is_isolated(self) -> None:
        store = FakeWebhookStore()
        store._add(url="https://x.test", event_types=[EVENT_BATCH_COMPLETED])
        deliveries = FakeDeliveryStore()
        deliveries.create = AsyncMock(side_effect=RuntimeError("insert failed"))  # type: ignore[method-assign]
        # The per-webhook crash is caught; dispatch returns normally.
        await _dispatcher(store, deliveries, FakeHttpClient([])).dispatch(
            organization_id=ORG, event_type=EVENT_BATCH_COMPLETED, payload={}
        )


# ---------------------------------------------------------------------------
# Registration routes
# ---------------------------------------------------------------------------


@pytest.fixture
def webhook_routes() -> Generator[dict[str, Any], None, None]:
    from app.dependencies import get_webhook_store, require_org_membership
    from app.main import app
    from app.webhooks.routes import _require_owner_or_admin

    store = FakeWebhookStore()
    membership = MagicMock()
    app.dependency_overrides[get_webhook_store] = lambda: store
    app.dependency_overrides[require_org_membership] = lambda: membership
    app.dependency_overrides[_require_owner_or_admin] = lambda: membership
    yield {"store": store}
    for dep in (get_webhook_store, require_org_membership, _require_owner_or_admin):
        app.dependency_overrides.pop(dep, None)


class TestWebhookRoutes:
    @pytest.mark.anyio
    async def test_create_returns_secret_once(
        self, client: AsyncClient, webhook_routes: dict[str, Any]
    ) -> None:
        org = uuid.uuid4()
        resp = await client.post(
            f"/v1/orgs/{org}/webhooks",
            json={"url": "https://example.test/hook", "event_types": ["batch.completed"]},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["secret"].startswith("whsec_")
        assert body["url"] == "https://example.test/hook"

    @pytest.mark.anyio
    async def test_invalid_url_422(
        self, client: AsyncClient, webhook_routes: dict[str, Any]
    ) -> None:
        resp = await client.post(f"/v1/orgs/{uuid.uuid4()}/webhooks", json={"url": "not-a-url"})
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_list_omits_secret(
        self, client: AsyncClient, webhook_routes: dict[str, Any]
    ) -> None:
        webhook_routes["store"]._add(url="https://x.test", event_types=["batch.completed"])
        resp = await client.get(f"/v1/orgs/{ORG}/webhooks")
        assert resp.status_code == 200
        assert "secret" not in resp.json()[0]

    @pytest.mark.anyio
    async def test_delete_then_404(
        self, client: AsyncClient, webhook_routes: dict[str, Any]
    ) -> None:
        hook = webhook_routes["store"]._add(url="https://x.test", event_types=["batch.completed"])
        assert (await client.delete(f"/v1/orgs/{ORG}/webhooks/{hook.id}")).status_code == 204
        assert (await client.delete(f"/v1/orgs/{ORG}/webhooks/{hook.id}")).status_code == 404


# ---------------------------------------------------------------------------
# Batch completion → dispatch wiring
# ---------------------------------------------------------------------------


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def dispatch(
        self, *, organization_id: uuid.UUID, event_type: str, payload: dict[str, Any]
    ) -> None:
        self.calls.append(
            {"organization_id": organization_id, "event_type": event_type, "payload": payload}
        )


class TestBatchDispatchWiring:
    @pytest.mark.anyio
    async def test_batch_completion_dispatches_event(self, client: AsyncClient) -> None:
        from app.cache.memory import TTLCache
        from app.dependencies import (
            get_analysis_provider,
            get_batch_service,
            get_cache,
            get_tenant_context,
            get_webhook_dispatcher,
            require_quota,
        )
        from app.jobs.service import BatchService
        from app.main import app
        from app.tenancy.base import TenantContext

        from tests.test_batch import FakeBatchJobStore, InlineJobRunner, _mock_provider

        recorder = RecordingDispatcher()
        context = TenantContext(organization_id=ORG, principal_type="api_key", scopes=("analyze",))
        app.dependency_overrides[require_quota] = lambda: context
        app.dependency_overrides[get_tenant_context] = lambda: context
        app.dependency_overrides[get_analysis_provider] = lambda: _mock_provider()
        app.dependency_overrides[get_cache] = lambda: TTLCache(ttl_seconds=300)
        app.dependency_overrides[get_batch_service] = lambda: BatchService(
            FakeBatchJobStore(), InlineJobRunner()
        )
        app.dependency_overrides[get_webhook_dispatcher] = lambda: recorder
        try:
            resp = await client.post("/v1/analyze/batch", json={"tickets": ["a", "b"]})
            assert resp.status_code == 202
            # Inline runner ran the job synchronously → the completion hook fired.
            assert len(recorder.calls) == 1
            call = recorder.calls[0]
            assert call["event_type"] == EVENT_BATCH_COMPLETED
            assert call["payload"]["status"] == "completed"
            assert call["payload"]["total"] == 2
        finally:
            for dep in (
                require_quota,
                get_tenant_context,
                get_analysis_provider,
                get_cache,
                get_batch_service,
                get_webhook_dispatcher,
            ):
                app.dependency_overrides.pop(dep, None)


# ---------------------------------------------------------------------------
# SqlAlchemyWebhookStore round-trip
# ---------------------------------------------------------------------------


class _FakeSession:
    """Async-context session stand-in for the sessionmaker-backed stores."""

    def __init__(
        self, *, get_value: Any = None, execute_result: Any = None, rowcount: int = 0
    ) -> None:
        self._get_value = get_value
        self._execute_result = execute_result
        self._rowcount = rowcount
        self.committed = False
        self.added: list[Any] = []

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def get(self, model: Any, ident: Any) -> Any:
        return self._get_value

    async def execute(self, stmt: Any) -> Any:
        if self._execute_result is not None:
            return self._execute_result
        return MagicMock(rowcount=self._rowcount)


def _scalars_result(rows: list[Any]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


class TestSqlAlchemyWebhookStores:
    @pytest.mark.anyio
    async def test_create_commits(self) -> None:
        session = _FakeSession()
        store = SqlAlchemyWebhookStore(MagicMock(return_value=session))
        hook = await store.create(
            organization_id=ORG, url="https://x.test", secret="s", event_types=["e"]
        )
        assert hook.url == "https://x.test"
        assert session.committed is True

    @pytest.mark.anyio
    async def test_list_active_filters_by_subscription(self) -> None:
        subscribed = Webhook(
            organization_id=ORG, url="https://a", secret="s", event_types=[EVENT_BATCH_COMPLETED]
        )
        other = Webhook(organization_id=ORG, url="https://b", secret="s", event_types=["x"])
        session = _FakeSession(execute_result=_scalars_result([subscribed, other]))
        store = SqlAlchemyWebhookStore(MagicMock(return_value=session))
        active = await store.list_active_for_event(ORG, EVENT_BATCH_COMPLETED)
        assert list(active) == [subscribed]

    @pytest.mark.anyio
    async def test_list_by_org_returns_scalars(self) -> None:
        hooks = [Webhook(organization_id=ORG, url="https://a", secret="s", event_types=["e"])]
        session = _FakeSession(execute_result=_scalars_result(hooks))
        store = SqlAlchemyWebhookStore(MagicMock(return_value=session))
        assert list(await store.list_by_org(ORG)) == hooks

    @pytest.mark.anyio
    async def test_get_scopes_by_org(self) -> None:
        hook = Webhook(organization_id=ORG, url="https://a", secret="s", event_types=["e"])
        hook.id = uuid.uuid4()
        store = SqlAlchemyWebhookStore(MagicMock(return_value=_FakeSession(get_value=hook)))
        assert await store.get(ORG, hook.id) is hook
        store2 = SqlAlchemyWebhookStore(MagicMock(return_value=_FakeSession(get_value=hook)))
        assert await store2.get(uuid.uuid4(), hook.id) is None

    @pytest.mark.anyio
    async def test_delete_returns_rowcount_bool(self) -> None:
        hit = SqlAlchemyWebhookStore(MagicMock(return_value=_FakeSession(rowcount=1)))
        assert await hit.delete(ORG, uuid.uuid4()) is True
        miss = SqlAlchemyWebhookStore(MagicMock(return_value=_FakeSession(rowcount=0)))
        assert await miss.delete(ORG, uuid.uuid4()) is False

    @pytest.mark.anyio
    async def test_delivery_create_and_update(self) -> None:
        from app.db.webhook_delivery_store import SqlAlchemyWebhookDeliveryStore

        session = _FakeSession()
        store = SqlAlchemyWebhookDeliveryStore(MagicMock(return_value=session))
        delivery = await store.create(
            webhook_id=uuid.uuid4(), organization_id=ORG, event_type="e", payload={}
        )
        assert session.committed is True

        row = WebhookDelivery(
            webhook_id=uuid.uuid4(), organization_id=ORG, event_type="e", payload={}
        )
        upd = _FakeSession(get_value=row)
        store2 = SqlAlchemyWebhookDeliveryStore(MagicMock(return_value=upd))
        await store2.update(
            delivery.id, status="delivered", attempts=1, response_status=200, error=None
        )
        assert row.status == "delivered" and upd.committed is True

    @pytest.mark.anyio
    async def test_delivery_update_missing_is_noop(self) -> None:
        from app.db.webhook_delivery_store import SqlAlchemyWebhookDeliveryStore

        session = _FakeSession(get_value=None)
        store = SqlAlchemyWebhookDeliveryStore(MagicMock(return_value=session))
        await store.update(
            uuid.uuid4(), status="failed", attempts=1, response_status=None, error="x"
        )
        assert session.committed is False


class TestWebhookSchema:
    def test_tables_registered(self) -> None:
        from app.db.base import Base

        assert {"webhooks", "webhook_deliveries"} <= set(Base.metadata.tables)

    @pytest.mark.anyio
    @pytest.mark.skipif(not DB_URL, reason="DATABASE_URL not set; skipping DB integration test")
    async def test_store_round_trip(self) -> None:
        from app.db.base import Base
        from app.db.models import Organization
        from app.db.session import create_db_engine, create_sessionmaker

        assert DB_URL is not None
        engine = create_db_engine(DB_URL)
        sessionmaker = create_sessionmaker(engine)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with sessionmaker() as session:
                org = Organization(name="Acme", slug="acme-wh")
                session.add(org)
                await session.commit()
                org_id = org.id

            store = SqlAlchemyWebhookStore(sessionmaker)
            hook = await store.create(
                organization_id=org_id,
                url="https://x.test",
                secret="whsec_1",
                event_types=[EVENT_BATCH_COMPLETED],
            )
            active = await store.list_active_for_event(org_id, EVENT_BATCH_COMPLETED)
            assert [h.id for h in active] == [hook.id]
            assert await store.delete(org_id, hook.id) is True
            assert await store.get(org_id, hook.id) is None
        finally:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            await engine.dispose()
