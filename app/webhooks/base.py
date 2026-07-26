"""Outbound-webhook ports: registration/delivery stores and the dispatcher."""

import uuid
from collections.abc import Sequence
from typing import Any, Protocol

from app.db.models import Webhook, WebhookDelivery

# Event emitted when an async batch job finishes.
EVENT_BATCH_COMPLETED = "batch.completed"


class WebhookStore(Protocol):
    """Persistence port for registered webhooks (sessionmaker-backed).

    Backed by a sessionmaker (own, self-committing sessions) so it works both in
    request handlers (registration) and in the background dispatch task.
    """

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        url: str,
        secret: str,
        event_types: list[str],
    ) -> Webhook: ...

    async def list_by_org(self, organization_id: uuid.UUID) -> Sequence[Webhook]: ...

    async def get(self, organization_id: uuid.UUID, webhook_id: uuid.UUID) -> Webhook | None: ...

    async def delete(self, organization_id: uuid.UUID, webhook_id: uuid.UUID) -> bool: ...

    async def list_active_for_event(
        self, organization_id: uuid.UUID, event_type: str
    ) -> Sequence[Webhook]: ...


class WebhookDeliveryStore(Protocol):
    """Persistence port for webhook delivery records (sessionmaker-backed)."""

    async def create(
        self,
        *,
        webhook_id: uuid.UUID,
        organization_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> WebhookDelivery: ...

    async def update(
        self,
        delivery_id: uuid.UUID,
        *,
        status: str,
        attempts: int,
        response_status: int | None,
        error: str | None,
    ) -> None: ...


class WebhookDispatcher(Protocol):
    """Delivers an event to all matching webhooks for an organization."""

    async def dispatch(
        self, *, organization_id: uuid.UUID, event_type: str, payload: dict[str, Any]
    ) -> None: ...
