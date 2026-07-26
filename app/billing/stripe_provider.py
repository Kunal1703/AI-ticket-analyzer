"""
Stripe implementation of the :class:`~app.billing.provider.BillingProvider`.

Signature verification and event parsing are delegated to the Stripe SDK
(``stripe.Webhook.construct_event``), which is imported **lazily** so the rest of
the application imports and runs without the optional ``stripe`` dependency
installed (it is only needed when Stripe webhooks are configured). All SDK
failures are translated into :class:`~app.billing.base.BillingProviderError`.

The provider stays behind the neutral ``BillingProvider`` interface: it maps a
verified Stripe event into a provider-agnostic :class:`BillingEvent`, resolving
the target organization from event metadata (``metadata.organization_id`` — the
standard Stripe pattern for linking a customer/subscription to a tenant) and the
target plan from the configured price→plan map.
"""

import logging
import uuid
from typing import Any

from app.billing.base import BillingProviderError
from app.billing.provider import BillingEvent, BillingProvider

logger = logging.getLogger(__name__)

PROVIDER_NAME = "stripe"

# Event types that carry a subscription/plan we sync onto the organization.
_SUBSCRIPTION_EVENTS = frozenset(
    {
        "customer.subscription.created",
        "customer.subscription.updated",
    }
)
_DELETED_EVENT = "customer.subscription.deleted"
_CHECKOUT_EVENT = "checkout.session.completed"


class StripeBillingProvider(BillingProvider):
    """Verify and normalize Stripe webhook events."""

    def __init__(
        self,
        *,
        webhook_secret: str,
        price_plan_map: dict[str, str],
        default_plan: str = "free",
    ) -> None:
        self._secret = webhook_secret
        self._price_plan_map = price_plan_map
        self._default_plan = default_plan

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def parse_webhook(self, payload: bytes, signature_header: str) -> BillingEvent:
        stripe = self._import_stripe()
        try:
            event = stripe.Webhook.construct_event(payload, signature_header, self._secret)
        except stripe.error.SignatureVerificationError as exc:
            raise BillingProviderError("Invalid Stripe webhook signature.") from exc
        except ValueError as exc:  # malformed payload
            raise BillingProviderError("Malformed Stripe webhook payload.") from exc

        event_id = str(event["id"])
        event_type = str(event["type"])
        obj: dict[str, Any] = event["data"]["object"]
        metadata: dict[str, Any] = obj.get("metadata") or {}

        return BillingEvent(
            provider=PROVIDER_NAME,
            event_id=event_id,
            type=event_type,
            organization_id=self._resolve_org(metadata),
            plan=self._resolve_plan(event_type, obj, metadata),
            customer_id=self._as_str(obj.get("customer")),
        )

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _import_stripe() -> Any:
        try:
            import stripe
        except ImportError as exc:  # optional dependency not installed
            raise BillingProviderError(
                "The 'stripe' package is required for Stripe webhooks but is not installed."
            ) from exc
        return stripe

    @staticmethod
    def _resolve_org(metadata: dict[str, Any]) -> uuid.UUID | None:
        raw = metadata.get("organization_id")
        if not raw:
            return None
        try:
            return uuid.UUID(str(raw))
        except ValueError:
            logger.warning("Stripe event metadata organization_id is not a UUID: %r", raw)
            return None

    def _resolve_plan(
        self, event_type: str, obj: dict[str, Any], metadata: dict[str, Any]
    ) -> str | None:
        if event_type == _DELETED_EVENT:
            return self._default_plan
        if event_type in _SUBSCRIPTION_EVENTS:
            return self._plan_from_price(obj)
        if event_type == _CHECKOUT_EVENT:
            # A checkout session may carry the plan directly in metadata.
            plan = metadata.get("plan")
            return str(plan) if plan else None
        return None

    def _plan_from_price(self, subscription: dict[str, Any]) -> str | None:
        try:
            price: dict[str, Any] = subscription["items"]["data"][0]["price"]
        except (KeyError, IndexError, TypeError):
            return None
        key = price.get("lookup_key") or price.get("id")
        if key is None:
            return None
        return self._price_plan_map.get(str(key))

    @staticmethod
    def _as_str(value: Any) -> str | None:
        return str(value) if value else None
