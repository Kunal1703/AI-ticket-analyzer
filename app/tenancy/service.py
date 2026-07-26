"""
Tenancy services: organization and API-key orchestration.

Thin coordinators over the persistence ports. They contain no HTTP concerns; the
route/dependency layer translates the tenancy errors into HTTP responses.
"""

import re
import secrets
import uuid
from collections.abc import Sequence

from app.db.models import ApiKey, Membership, Organization
from app.tenancy.api_key import generate_api_key, hash_api_key
from app.tenancy.base import (
    ApiKeyNotFoundError,
    ApiKeyStore,
    ForbiddenError,
    OrgStore,
    TenantNotResolvedError,
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    base = _SLUG_RE.sub("-", name.strip().lower()).strip("-") or "org"
    # A short random suffix keeps slugs unique without an extra lookup.
    return f"{base}-{secrets.token_hex(3)}"


class OrganizationService:
    """Create and query organizations and memberships."""

    def __init__(self, org_store: OrgStore) -> None:
        self._orgs = org_store

    async def create_org(self, *, name: str, owner_id: uuid.UUID) -> Organization:
        return await self._orgs.create(name=name, slug=_slugify(name), owner_id=owner_id)

    async def get_org(self, organization_id: uuid.UUID) -> Organization | None:
        return await self._orgs.get(organization_id)

    async def list_orgs(self, user_id: uuid.UUID) -> Sequence[Organization]:
        return await self._orgs.list_for_user(user_id)

    async def require_membership(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> Membership:
        membership = await self._orgs.get_membership(organization_id, user_id)
        if membership is None:
            raise ForbiddenError("not a member of this organization")
        return membership


class ApiKeyService:
    """Create, list, revoke, and authenticate API keys."""

    def __init__(self, api_key_store: ApiKeyStore) -> None:
        self._keys = api_key_store

    async def create_key(
        self, *, organization_id: uuid.UUID, name: str, scopes: list[str] | None
    ) -> tuple[ApiKey, str]:
        """Create a key; returns the ORM row and the one-time plaintext."""
        plaintext, prefix, key_hash = generate_api_key()
        key = await self._keys.create(
            organization_id=organization_id,
            name=name,
            key_hash=key_hash,
            prefix=prefix,
            scopes=scopes,
        )
        return key, plaintext

    async def list_keys(self, organization_id: uuid.UUID) -> Sequence[ApiKey]:
        return await self._keys.list_by_org(organization_id)

    async def revoke_key(self, organization_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey:
        key = await self._keys.get(organization_id, key_id)
        if key is None:
            raise ApiKeyNotFoundError("api key not found")
        await self._keys.revoke(key)
        return key

    async def authenticate(self, plaintext: str) -> ApiKey:
        """Resolve an active API key from its plaintext, updating last-used."""
        key = await self._keys.get_active_by_hash(hash_api_key(plaintext))
        if key is None:
            raise TenantNotResolvedError("invalid or revoked API key")
        await self._keys.touch(key)
        return key
