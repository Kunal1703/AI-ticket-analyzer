"""
Billing HTTP routes: the inbound provider webhook and per-org usage.

The webhook endpoint is unauthenticated (it is authenticated by the provider's
signature, verified inside the ``BillingProvider``) and idempotent. The usage
endpoint is org-scoped (requires membership).
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from app.billing.base import BillingProviderError
from app.billing.service import BillingService, WebhookService, current_period_start
from app.db.models import Membership
from app.dependencies import (
    get_billing_service,
    get_org_service,
    get_webhook_service,
    require_org_membership,
)
from app.models import UsageResponse, WebhookAck
from app.observability import metrics
from app.tenancy.service import OrganizationService

router = APIRouter(prefix="/v1", tags=["Billing"])

# Stripe sends the signature in this header.
_SIGNATURE_HEADER = "Stripe-Signature"


@router.post(
    "/billing/webhook",
    response_model=WebhookAck,
    summary="Billing provider webhook",
    description=(
        "Receives signature-verified billing webhooks (e.g. Stripe). Idempotent: "
        "duplicate deliveries are acknowledged without reprocessing. Returns 503 "
        "when billing is not configured, 400 on an invalid signature/payload."
    ),
    responses={
        400: {"description": "Invalid webhook signature or payload"},
        503: {"description": "Billing is not configured"},
    },
)
async def billing_webhook(
    request: Request,
    service: WebhookService = Depends(get_webhook_service),
) -> WebhookAck:
    """Verify, de-duplicate, and apply a billing provider webhook."""
    payload = await request.body()
    signature = request.headers.get(_SIGNATURE_HEADER, "")
    try:
        status = await service.handle(payload, signature)
    except BillingProviderError as exc:
        metrics.record_billing_webhook("stripe", "invalid")
        raise HTTPException(status_code=400, detail="Invalid webhook signature or payload") from exc
    metrics.record_billing_webhook("stripe", status)
    return WebhookAck(status=status)


@router.get(
    "/orgs/{org_id}/usage",
    response_model=UsageResponse,
    summary="Current usage vs. plan limit",
)
async def get_org_usage(
    org_id: uuid.UUID,
    _membership: Membership = Depends(require_org_membership),
    org_service: OrganizationService = Depends(get_org_service),
    billing: BillingService = Depends(get_billing_service),
) -> UsageResponse:
    """Return the organization's current-period usage against its plan limit."""
    org = await org_service.get_org(org_id)
    plan = billing.plan_for(org.plan if org is not None else None)
    used = await billing.current_usage(org_id)
    period_start = current_period_start(datetime.now(UTC))
    return UsageResponse(
        plan=plan.name,
        used=used,
        limit=plan.monthly_analysis_limit,
        period_start=period_start.isoformat(),
    )
