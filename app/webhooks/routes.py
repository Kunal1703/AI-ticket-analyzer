"""
Webhook registration routes (``/v1/orgs/{org_id}/webhooks``).

Managing webhooks mirrors API-key management: create/delete require owner/admin,
listing requires membership. The signing secret is returned **once** at creation
(and stored so the app can sign deliveries).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response

from app.db.models import Membership, Webhook
from app.dependencies import get_webhook_store, require_org_membership, require_role
from app.models import (
    CreateWebhookRequest,
    WebhookCreatedResponse,
    WebhookResponse,
)
from app.webhooks.base import WebhookStore
from app.webhooks.signing import generate_webhook_secret

router = APIRouter(prefix="/v1", tags=["Webhooks"])

# Module-level dependency singleton (avoids a call inside Depends()).
_require_owner_or_admin = require_role("owner", "admin")


def _webhook_response(webhook: Webhook) -> WebhookResponse:
    return WebhookResponse(
        id=str(webhook.id),
        url=webhook.url,
        event_types=list(webhook.event_types or []),
        active=webhook.active,
    )


@router.post(
    "/orgs/{org_id}/webhooks",
    response_model=WebhookCreatedResponse,
    status_code=201,
    summary="Register a webhook",
)
async def create_webhook(
    org_id: uuid.UUID,
    payload: CreateWebhookRequest,
    _membership: Membership = Depends(_require_owner_or_admin),
    store: WebhookStore = Depends(get_webhook_store),
) -> WebhookCreatedResponse:
    """Register an outbound webhook; the signing secret is returned once."""
    secret = generate_webhook_secret()
    webhook = await store.create(
        organization_id=org_id,
        url=str(payload.url),
        secret=secret,
        event_types=payload.event_types,
    )
    base = _webhook_response(webhook)
    return WebhookCreatedResponse(**base.model_dump(), secret=secret)


@router.get(
    "/orgs/{org_id}/webhooks",
    response_model=list[WebhookResponse],
    summary="List webhooks",
)
async def list_webhooks(
    org_id: uuid.UUID,
    _membership: Membership = Depends(require_org_membership),
    store: WebhookStore = Depends(get_webhook_store),
) -> list[WebhookResponse]:
    """List the organization's webhooks (never includes secrets)."""
    return [_webhook_response(w) for w in await store.list_by_org(org_id)]


@router.delete(
    "/orgs/{org_id}/webhooks/{webhook_id}",
    status_code=204,
    summary="Delete a webhook",
)
async def delete_webhook(
    org_id: uuid.UUID,
    webhook_id: uuid.UUID,
    _membership: Membership = Depends(_require_owner_or_admin),
    store: WebhookStore = Depends(get_webhook_store),
) -> Response:
    """Delete a webhook (owner/admin); 404 if it isn't in this organization."""
    if not await store.delete(org_id, webhook_id):
        raise HTTPException(status_code=404, detail="Webhook not found")
    return Response(status_code=204)
