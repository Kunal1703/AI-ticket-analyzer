"""
Tests for M3.5: inbound channels (email-to-ticket + CSV import).

Everything runs offline: the provider is mocked, the batch uses an inline runner,
and CSV parsing is pure. Source threading is verified at the persistence layer.
"""

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.csv_parser import MAX_IMPORT_ROWS, parse_csv_tickets
from app.services import analysis_service
from app.services.analysis_service import persist_analysis
from httpx import AsyncClient

from tests.test_batch import FakeBatchJobStore, InlineJobRunner, _mock_provider
from tests.test_tickets import ORG


def _analysis() -> Any:
    from app.models import TicketAnalysis, TicketCategory, TicketPriority

    return TicketAnalysis(
        summary="s",
        category=TicketCategory.BILLING,
        priority=TicketPriority.HIGH,
        next_actions=["x"],
    )


# ---------------------------------------------------------------------------
# CSV parser
# ---------------------------------------------------------------------------


class TestCsvParser:
    def test_text_column(self) -> None:
        csv = b"text,other\nfirst issue,x\nsecond issue,y\n"
        assert parse_csv_tickets(csv) == ["first issue", "second issue"]

    def test_alternate_column_name(self) -> None:
        assert parse_csv_tickets(b"Body\nhello\n") == ["hello"]

    def test_single_column_is_used(self) -> None:
        assert parse_csv_tickets(b"anything\nrow one\nrow two\n") == ["row one", "row two"]

    def test_blank_rows_skipped(self) -> None:
        assert parse_csv_tickets(b"text\na\n   \nb\n") == ["a", "b"]

    def test_no_usable_column_raises(self) -> None:
        with pytest.raises(ValueError, match="no text column"):
            parse_csv_tickets(b"col_a,col_b\n1,2\n")

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty or missing"):
            parse_csv_tickets(b"")

    def test_no_rows_raises(self) -> None:
        with pytest.raises(ValueError, match="no ticket rows"):
            parse_csv_tickets(b"text\n")

    def test_too_many_rows_raises(self) -> None:
        rows = "text\n" + "\n".join(f"t{i}" for i in range(MAX_IMPORT_ROWS + 1)) + "\n"
        with pytest.raises(ValueError, match="too many rows"):
            parse_csv_tickets(rows.encode())

    def test_non_utf8_raises(self) -> None:
        with pytest.raises(ValueError, match="UTF-8"):
            parse_csv_tickets(b"text\n\xff\xfe bad\n")


# ---------------------------------------------------------------------------
# Source threading (persistence layer)
# ---------------------------------------------------------------------------


class _FakeSession:
    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def commit(self) -> None:
        return None


class TestSourceThreading:
    @pytest.mark.anyio
    async def test_persist_forwards_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        get_or_create = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr(analysis_service.repositories, "get_or_create_ticket", get_or_create)
        monkeypatch.setattr(analysis_service.repositories, "add_analysis", AsyncMock())
        sessionmaker = MagicMock(return_value=_FakeSession())

        await persist_analysis(
            sessionmaker,
            ticket_text="t",
            text_hash="h",
            analysis=_analysis(),
            source="email",
        )
        assert get_or_create.await_args is not None
        assert get_or_create.await_args.kwargs["source"] == "email"


# ---------------------------------------------------------------------------
# Channel routes
# ---------------------------------------------------------------------------


@pytest.fixture
def channel_overrides() -> Generator[dict[str, Any], None, None]:
    from app.cache.memory import TTLCache
    from app.dependencies import (
        get_analysis_provider,
        get_batch_service,
        get_cache,
        get_webhook_dispatcher,
        require_quota,
    )
    from app.jobs.service import BatchService
    from app.main import app
    from app.tenancy.base import TenantContext
    from app.webhooks.dispatcher import NoOpWebhookDispatcher

    provider = _mock_provider()
    store = FakeBatchJobStore()
    context = TenantContext(organization_id=ORG, principal_type="api_key", scopes=("analyze",))

    app.dependency_overrides[require_quota] = lambda: context
    app.dependency_overrides[get_analysis_provider] = lambda: provider
    app.dependency_overrides[get_cache] = lambda: TTLCache(ttl_seconds=300)
    app.dependency_overrides[get_batch_service] = lambda: BatchService(store, InlineJobRunner())
    app.dependency_overrides[get_webhook_dispatcher] = lambda: NoOpWebhookDispatcher()
    yield {"provider": provider, "store": store}
    for dep in (
        require_quota,
        get_analysis_provider,
        get_cache,
        get_batch_service,
        get_webhook_dispatcher,
    ):
        app.dependency_overrides.pop(dep, None)


class TestEmailChannel:
    @pytest.mark.anyio
    async def test_email_creates_analysis(
        self, client: AsyncClient, channel_overrides: dict[str, Any]
    ) -> None:
        resp = await client.post(
            "/v1/channels/email",
            json={"from_address": "a@b.com", "subject": "Charged twice", "body": "Please help"},
        )
        assert resp.status_code == 200
        assert resp.json()["category"] == "Billing"
        channel_overrides["provider"].analyze.assert_awaited_once()

    @pytest.mark.anyio
    async def test_email_requires_body(
        self, client: AsyncClient, channel_overrides: dict[str, Any]
    ) -> None:
        resp = await client.post(
            "/v1/channels/email", json={"from_address": "a@b.com", "subject": "x"}
        )
        assert resp.status_code == 422


class TestImportChannel:
    @pytest.mark.anyio
    async def test_import_submits_batch(
        self, client: AsyncClient, channel_overrides: dict[str, Any]
    ) -> None:
        csv = b"text\nfirst\nsecond\nthird\n"
        resp = await client.post(
            "/v1/channels/import", content=csv, headers={"Content-Type": "text/csv"}
        )
        assert resp.status_code == 202
        assert resp.json()["total"] == 3
        # Inline runner analyzed each row.
        assert channel_overrides["provider"].analyze.await_count == 3

    @pytest.mark.anyio
    async def test_import_bad_csv_400(
        self, client: AsyncClient, channel_overrides: dict[str, Any]
    ) -> None:
        resp = await client.post(
            "/v1/channels/import", content=b"a,b\n1,2\n", headers={"Content-Type": "text/csv"}
        )
        assert resp.status_code == 400
