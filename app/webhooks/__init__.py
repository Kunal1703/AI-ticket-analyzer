"""
Outbound webhooks (Milestone M3.3b).

Tenants register endpoints (``webhooks``); the app delivers signed event payloads
to them (``webhook_deliveries`` records each attempt-set). Delivery is the
*outbound* mirror of the inbound Stripe webhook verification (M2.5b): here the app
is the signer (HMAC-SHA256 over ``{timestamp}.{body}``), and the tenant verifies.

- ``base`` — the ``WebhookStore``/``WebhookDeliveryStore``/``WebhookDispatcher`` ports.
- ``signing`` — secret generation + signature header.
- ``dispatcher`` — ``HttpWebhookDispatcher`` (bounded inline retries) + a no-op.
- ``routes`` — registration CRUD under ``/v1/orgs/{org_id}/webhooks``.
"""

from app.webhooks.base import WebhookDeliveryStore, WebhookDispatcher, WebhookStore
from app.webhooks.dispatcher import HttpWebhookDispatcher, NoOpWebhookDispatcher

__all__ = [
    "HttpWebhookDispatcher",
    "NoOpWebhookDispatcher",
    "WebhookDeliveryStore",
    "WebhookDispatcher",
    "WebhookStore",
]
