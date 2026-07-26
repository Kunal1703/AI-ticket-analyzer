"""
Tenancy primitives: the resolved request tenant context, persistence ports, and
the error hierarchy.

``TenantContext`` is what business logic depends on — it identifies the active
organization for a request regardless of how the caller authenticated (user JWT
or API key).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from app.db.models import ApiKey, Membership, Organization


class Role(str, Enum):
    """Membership roles, ordered most→least privileged.

    Stored as strings on ``Membership.role``. Enforcement is via the
    ``require_role`` dependency; the org creator is ``OWNER``. Member invitation
    and role assignment endpoints are a later milestone, so today an org has a
    single owner member.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    AGENT = "agent"
    READONLY = "readonly"


class TenantError(Exception):
    """Base class for tenancy failures."""


class TenantNotResolvedError(TenantError):
    """No valid tenant could be resolved for the request (maps to HTTP 401)."""


class ForbiddenError(TenantError):
    """The principal is not permitted to act on the target org (maps to HTTP 403)."""


class ApiKeyNotFoundError(TenantError):
    """The referenced API key does not exist (maps to HTTP 404)."""


@dataclass(frozen=True)
class TenantContext:
    """The active organization + principal for a request."""

    organization_id: uuid.UUID
    principal_type: str  # "user" | "api_key"
    user_id: uuid.UUID | None = None
    api_key_id: uuid.UUID | None = None
    scopes: tuple[str, ...] = field(default_factory=tuple)


class OrgStore(Protocol):
    """Persistence port for organizations and memberships."""

    async def create(self, *, name: str, slug: str, owner_id: uuid.UUID) -> Organization: ...

    async def get(self, organization_id: uuid.UUID) -> Organization | None: ...

    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[Organization]: ...

    async def get_membership(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> Membership | None: ...


class ApiKeyStore(Protocol):
    """Persistence port for API keys."""

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        name: str,
        key_hash: str,
        prefix: str,
        scopes: list[str] | None,
    ) -> ApiKey: ...

    async def get_active_by_hash(self, key_hash: str) -> ApiKey | None: ...

    async def list_by_org(self, organization_id: uuid.UUID) -> Sequence[ApiKey]: ...

    async def get(self, organization_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey | None: ...

    async def revoke(self, api_key: ApiKey) -> None: ...

    async def touch(self, api_key: ApiKey) -> None: ...
