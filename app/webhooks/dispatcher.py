"""
Webhook dispatchers.

``HttpWebhookDispatcher`` finds the org's active webhooks subscribed to an event,
records a delivery, and POSTs the signed payload with **bounded inline retries**
(short exponential backoff). It is best-effort: a delivery failure is recorded but
never propagates to the caller (a batch must still complete even if a webhook is
down). ``NoOpWebhookDispatcher`` is used when persistence is unavailable.
"""

import asyncio
import json
import logging
import uuid
from typing import Any, Protocol

from app.observability import metrics
from app.webhooks.base import WebhookDeliveryStore, WebhookStore
from app.webhooks.signing import WEBHOOK_SIGNATURE_HEADER, signature_header

logger = logging.getLogger(__name__)


class _HttpClient(Protocol):
    async def post(
        self, url: str, *, content: bytes, headers: dict[str, str], timeout: float
    ) -> Any: ...


class NoOpWebhookDispatcher:
    """Dispatcher used when webhooks can't be delivered (e.g. no database)."""

    async def dispatch(
        self, *, organization_id: uuid.UUID, event_type: str, payload: dict[str, Any]
    ) -> None:
        return None


class HttpWebhookDispatcher:
    """Deliver events to registered webhooks over HTTP with signing + retries."""

    def __init__(
        self,
        webhook_store: WebhookStore,
        delivery_store: WebhookDeliveryStore,
        http_client: _HttpClient,
        *,
        max_attempts: int = 3,
        timeout_seconds: float = 10.0,
        backoff_base_seconds: float = 0.5,
    ) -> None:
        self._webhooks = webhook_store
        self._deliveries = delivery_store
        self._client = http_client
        self._max_attempts = max(1, max_attempts)
        self._timeout = timeout_seconds
        self._backoff = backoff_base_seconds

    async def dispatch(
        self, *, organization_id: uuid.UUID, event_type: str, payload: dict[str, Any]
    ) -> None:
        try:
            hooks = await self._webhooks.list_active_for_event(organization_id, event_type)
        except Exception:
            logger.exception("Failed to load webhooks for %s/%s", organization_id, event_type)
            return
        for hook in hooks:
            try:
                await self._deliver(hook, organization_id, event_type, payload)
            except Exception:
                # Best-effort: one bad delivery must not stop the others.
                logger.exception("Webhook delivery crashed (webhook=%s)", hook.id)

    async def _deliver(
        self, hook: Any, organization_id: uuid.UUID, event_type: str, payload: dict[str, Any]
    ) -> None:
        delivery = await self._deliveries.create(
            webhook_id=hook.id,
            organization_id=organization_id,
            event_type=event_type,
            payload=payload,
        )
        body = json.dumps(payload, separators=(",", ":")).encode()

        status = "failed"
        response_status: int | None = None
        error: str | None = None
        attempts = 0
        for attempt in range(1, self._max_attempts + 1):
            attempts = attempt
            try:
                headers = {
                    "Content-Type": "application/json",
                    WEBHOOK_SIGNATURE_HEADER: signature_header(hook.secret, body),
                }
                resp = await self._client.post(
                    hook.url, content=body, headers=headers, timeout=self._timeout
                )
                response_status = resp.status_code
                if 200 <= resp.status_code < 300:
                    status = "delivered"
                    error = None
                    break
                error = f"HTTP {resp.status_code}"
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            if attempt < self._max_attempts:
                await asyncio.sleep(self._backoff * (2 ** (attempt - 1)))

        await self._deliveries.update(
            delivery.id,
            status=status,
            attempts=attempts,
            response_status=response_status,
            error=error,
        )
        metrics.record_webhook_delivery(status)
