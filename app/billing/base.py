"""
Billing primitives: the usage persistence port and the error hierarchy.

``UsageStore`` is the port that business logic depends on (mirroring
``OrgStore``/``ApiKeyStore``); the SQLAlchemy implementation lives in
``app/db/usage_store.py``. Billing errors translate to HTTP at the
route/dependency boundary (``QuotaExceededError`` → 402), like the tenancy
errors.
"""

import uuid
from datetime import datetime
from typing import Protocol

from app.db.models import ProcessedWebhookEvent, UsageEvent


class BillingError(Exception):
    """Base class for billing/metering failures."""


class QuotaExceededError(BillingError):
    """The organization has reached its plan's usage limit (maps to HTTP 402)."""


class BillingProviderError(BillingError):
    """A billing provider failed to parse/verify a request (maps to HTTP 400)."""


class UsageStore(Protocol):
    """Persistence port for metered usage events."""

    async def record(
        self,
        *,
        organization_id: uuid.UUID,
        event_type: str,
        quantity: int,
        model: str | None,
        total_tokens: int | None,
    ) -> UsageEvent: ...

    async def count_since(
        self,
        organization_id: uuid.UUID,
        *,
        since: datetime,
        event_type: str,
    ) -> int: ...


class WebhookEventStore(Protocol):
    """Persistence port for processed webhook events (idempotency)."""

    async def exists(self, *, provider: str, event_id: str) -> bool: ...

    async def record(
        self, *, provider: str, event_id: str, event_type: str
    ) -> ProcessedWebhookEvent: ...
