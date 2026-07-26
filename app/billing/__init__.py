"""
Billing & usage metering (Milestone M2.5a).

Meters analyses per organization and enforces plan-based monthly quotas. Follows
the same ports + service + best-effort-persistence conventions as the rest of the
codebase:

- ``plans`` — a configurable plan registry (placeholder limits; overridable via
  settings) mapping a plan slug to its monthly analysis limit.
- ``base`` — the ``UsageStore`` persistence port and the billing error hierarchy.
- ``service`` — ``BillingService`` (quota checks over the store + plan registry).
- ``metering`` — best-effort usage recording on the analyze path (mirrors
  ``persist_analysis``: own session, never breaks the response).

Quota enforcement is wired only into the tenant-scoped ``/v1/analyze`` (a
``require_quota`` dependency); the legacy ``/analyze`` is never metered or
limited.
"""

from app.billing.base import (
    BillingError,
    BillingProviderError,
    QuotaExceededError,
    UsageStore,
    WebhookEventStore,
)
from app.billing.plans import DEFAULT_PLAN, Plan, build_plans, get_plan
from app.billing.provider import BillingEvent, BillingProvider, build_billing_provider
from app.billing.service import BillingService, WebhookService

__all__ = [
    "DEFAULT_PLAN",
    "BillingError",
    "BillingEvent",
    "BillingProvider",
    "BillingProviderError",
    "BillingService",
    "Plan",
    "QuotaExceededError",
    "UsageStore",
    "WebhookEventStore",
    "WebhookService",
    "build_billing_provider",
    "build_plans",
    "get_plan",
]
