"""
Billing service: plan-based quota checks over the usage store.

A thin coordinator (like ``OrganizationService``) with no HTTP concerns. The
dependency layer translates ``QuotaExceededError`` into an HTTP 402. Metering
*writes* are handled separately, best-effort, on the analyze path (see
``app.billing.metering``); this service owns the read-side quota decision.
"""

import logging
import uuid
from datetime import UTC, datetime

from app.billing.base import QuotaExceededError, UsageStore, WebhookEventStore
from app.billing.plans import Plan, build_plans, get_plan
from app.billing.provider import BillingEvent, BillingProvider
from app.tenancy.base import OrgStore

logger = logging.getLogger(__name__)

# The metered event type recorded per analysis; also the unit quota is counted in.
ANALYSIS_EVENT = "analysis"


def current_period_start(now: datetime | None = None) -> datetime:
    """Return the start of the current calendar month in UTC.

    Quotas reset monthly. Injecting ``now`` keeps this testable.
    """
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class BillingService:
    """Evaluate plan quotas against recorded usage."""

    def __init__(self, usage_store: UsageStore, plans: dict[str, Plan] | None = None) -> None:
        self._usage = usage_store
        # Default to the placeholder registry so the service is usable without a
        # configured registry (e.g. in unit tests).
        self._plans = plans if plans is not None else build_plans()

    async def check_quota(
        self,
        organization_id: uuid.UUID,
        plan_name: str | None,
        *,
        event_type: str = ANALYSIS_EVENT,
        now: datetime | None = None,
    ) -> None:
        """Raise ``QuotaExceededError`` if the org is at/over its monthly limit.

        Unlimited plans (``monthly_analysis_limit is None``) always pass without
        touching the store.
        """
        plan = get_plan(self._plans, plan_name)
        if plan.monthly_analysis_limit is None:
            return
        since = current_period_start(now)
        used = await self._usage.count_since(organization_id, since=since, event_type=event_type)
        if used >= plan.monthly_analysis_limit:
            raise QuotaExceededError(
                f"Monthly '{event_type}' quota reached for plan '{plan.name}' "
                f"({used}/{plan.monthly_analysis_limit})."
            )

    def plan_for(self, plan_name: str | None) -> Plan:
        """Resolve a plan from the registry (falls back to the default plan)."""
        return get_plan(self._plans, plan_name)

    async def current_usage(
        self,
        organization_id: uuid.UUID,
        *,
        event_type: str = ANALYSIS_EVENT,
        now: datetime | None = None,
    ) -> int:
        """Return the org's metered usage so far in the current period."""
        return await self._usage.count_since(
            organization_id, since=current_period_start(now), event_type=event_type
        )


class WebhookService:
    """Ingest verified billing webhooks idempotently and sync the org's plan."""

    def __init__(
        self,
        provider: BillingProvider,
        event_store: WebhookEventStore,
        org_store: OrgStore,
    ) -> None:
        self._provider = provider
        self._events = event_store
        self._orgs = org_store

    async def handle(self, payload: bytes, signature_header: str) -> str:
        """Verify, de-duplicate, and apply a billing webhook.

        Returns a short status string: ``"duplicate"`` (already processed),
        ``"plan_updated"`` (org plan synced), or ``"ignored"`` (nothing to do).
        Raises ``BillingProviderError`` (mapped to 400) on an invalid signature.
        """
        event: BillingEvent = self._provider.parse_webhook(payload, signature_header)

        if await self._events.exists(provider=event.provider, event_id=event.event_id):
            logger.info("Ignoring duplicate webhook event %s", event.event_id)
            return "duplicate"
        await self._events.record(
            provider=event.provider, event_id=event.event_id, event_type=event.type
        )

        if event.organization_id is None or event.plan is None:
            return "ignored"
        org = await self._orgs.get(event.organization_id)
        if org is None:
            logger.warning(
                "Webhook %s references unknown org %s", event.event_id, event.organization_id
            )
            return "ignored"
        org.plan = event.plan
        if event.customer_id and org.stripe_customer_id is None:
            org.stripe_customer_id = event.customer_id
        logger.info("Synced org %s to plan %s via webhook", org.id, event.plan)
        return "plan_updated"
