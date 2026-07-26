"""
Provider-agnostic billing interface (mirrors ``AuthProvider``/``AnalysisProvider``).

A ``BillingProvider`` verifies and normalizes an inbound webhook into a neutral
:class:`BillingEvent`. Business logic (the ``WebhookService``, routes) depends only
on this interface and the neutral event — never on the Stripe SDK. New billing
backends can be added by implementing this interface and registering them in
``_PROVIDERS``, with no change to routes, services, or persistence.
"""

import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from app.billing.base import BillingProviderError
from app.config import Settings


@dataclass(frozen=True)
class BillingEvent:
    """A normalized billing webhook event.

    Attributes:
        provider: Registered provider name (e.g. ``"stripe"``).
        event_id: Provider-unique event id (used for idempotency).
        type: Provider event type (e.g. ``"customer.subscription.updated"``).
        organization_id: The target org, resolved from event metadata, if present.
        plan: The local plan slug this event implies, if any.
        customer_id: The provider customer id, if present.
    """

    provider: str
    event_id: str
    type: str
    organization_id: uuid.UUID | None = None
    plan: str | None = None
    customer_id: str | None = None


class BillingProvider(ABC):
    """Interface every billing backend implements."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Registered provider name."""

    @abstractmethod
    def parse_webhook(self, payload: bytes, signature_header: str) -> BillingEvent:
        """Verify the webhook signature and return a normalized event.

        Args:
            payload: The raw request body bytes (verbatim — do not re-serialize).
            signature_header: The provider's signature header value.

        Raises:
            BillingProviderError: The signature/payload was invalid, or the
                provider SDK is unavailable/misconfigured.
        """


@dataclass(frozen=True)
class BillingProviderContext:
    """Inputs available to construct any billing provider."""

    settings: Settings


def _build_stripe(ctx: BillingProviderContext) -> BillingProvider:
    # Imported here (not at module top) so a missing optional dependency or an
    # unconfigured Stripe secret never affects importing this module.
    from app.billing.stripe_provider import StripeBillingProvider

    secret = ctx.settings.stripe_webhook_secret
    if not secret:
        raise BillingProviderError("Stripe webhook secret is not configured.")
    return StripeBillingProvider(
        webhook_secret=secret,
        price_plan_map=ctx.settings.stripe_price_plan_map or {},
    )


_PROVIDERS: dict[str, Callable[[BillingProviderContext], BillingProvider]] = {
    "stripe": _build_stripe,
}


def available_billing_providers() -> list[str]:
    """Return the sorted list of registered billing provider names."""
    return sorted(_PROVIDERS)


def build_billing_provider(settings: Settings) -> BillingProvider:
    """Construct the configured billing provider.

    Raises:
        ValueError: If ``settings.billing_provider`` is not registered.
        BillingProviderError: If the provider is selected but not configured.
    """
    name = settings.billing_provider.lower()
    factory = _PROVIDERS.get(name)
    if factory is None:
        raise ValueError(
            f"Unsupported billing provider {name!r}. Supported: "
            f"{', '.join(available_billing_providers())}."
        )
    return factory(BillingProviderContext(settings=settings))
