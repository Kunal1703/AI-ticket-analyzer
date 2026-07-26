"""
Unit tests for the tenancy layer (Milestone M2.3): API key gen/hash, the
organization and API-key services, and the SQLAlchemy stores (mocked session).

Also defines in-memory fake stores reused by the route tests.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.db.api_key_store import SqlAlchemyApiKeyStore
from app.db.models import ApiKey, Membership, Organization
from app.db.org_store import SqlAlchemyOrgStore
from app.tenancy.api_key import KEY_PREFIX, generate_api_key, hash_api_key
from app.tenancy.base import ApiKeyNotFoundError, ForbiddenError, TenantNotResolvedError
from app.tenancy.service import ApiKeyService, OrganizationService

# ---------------------------------------------------------------------------
# In-memory fakes (shared with route tests)
# ---------------------------------------------------------------------------


class FakeOrgStore:
    def __init__(self) -> None:
        self.orgs: dict[uuid.UUID, Organization] = {}
        self.memberships: list[Membership] = []

    async def create(self, *, name: str, slug: str, owner_id: uuid.UUID) -> Organization:
        org = Organization(name=name, slug=slug)
        org.id = uuid.uuid4()
        org.plan = "free"
        org.status = "active"
        self.orgs[org.id] = org
        membership = Membership(organization_id=org.id, user_id=owner_id, role="owner")
        membership.id = uuid.uuid4()
        self.memberships.append(membership)
        return org

    async def get(self, organization_id: uuid.UUID) -> Organization | None:
        return self.orgs.get(organization_id)

    async def list_for_user(self, user_id: uuid.UUID) -> list[Organization]:
        return [
            self.orgs[m.organization_id]
            for m in self.memberships
            if m.user_id == user_id and m.organization_id in self.orgs
        ]

    async def get_membership(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> Membership | None:
        for m in self.memberships:
            if m.organization_id == organization_id and m.user_id == user_id:
                return m
        return None


class FakeApiKeyStore:
    def __init__(self) -> None:
        self.keys: dict[uuid.UUID, ApiKey] = {}

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        name: str,
        key_hash: str,
        prefix: str,
        scopes: list[str] | None,
    ) -> ApiKey:
        key = ApiKey(
            organization_id=organization_id,
            name=name,
            key_hash=key_hash,
            prefix=prefix,
            scopes=scopes,
        )
        key.id = uuid.uuid4()
        key.revoked_at = None
        key.last_used_at = None
        self.keys[key.id] = key
        return key

    async def get_active_by_hash(self, key_hash: str) -> ApiKey | None:
        for k in self.keys.values():
            if k.key_hash == key_hash and k.revoked_at is None:
                return k
        return None

    async def list_by_org(self, organization_id: uuid.UUID) -> list[ApiKey]:
        return [k for k in self.keys.values() if k.organization_id == organization_id]

    async def get(self, organization_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey | None:
        key = self.keys.get(key_id)
        return key if key is not None and key.organization_id == organization_id else None

    async def revoke(self, api_key: ApiKey) -> None:
        api_key.revoked_at = datetime.now(UTC)

    async def touch(self, api_key: ApiKey) -> None:
        api_key.last_used_at = datetime.now(UTC)


# ---------------------------------------------------------------------------
# API key generation / hashing
# ---------------------------------------------------------------------------


class TestApiKeyGeneration:
    def test_generate_shape(self) -> None:
        plaintext, prefix, key_hash = generate_api_key()
        assert plaintext.startswith(KEY_PREFIX)
        assert prefix == plaintext[:12]
        assert key_hash == hash_api_key(plaintext)
        assert len(key_hash) == 64  # sha256 hex

    def test_hash_is_deterministic_and_unique(self) -> None:
        assert hash_api_key("atk_abc") == hash_api_key("atk_abc")
        assert hash_api_key("atk_abc") != hash_api_key("atk_xyz")

    def test_generated_keys_differ(self) -> None:
        assert generate_api_key()[0] != generate_api_key()[0]


# ---------------------------------------------------------------------------
# OrganizationService
# ---------------------------------------------------------------------------


class TestOrganizationService:
    @pytest.mark.anyio
    async def test_create_and_list(self) -> None:
        store = FakeOrgStore()
        service = OrganizationService(store)
        owner = uuid.uuid4()
        org = await service.create_org(name="Acme Inc", owner_id=owner)
        assert org.slug.startswith("acme-inc-")
        orgs = list(await service.list_orgs(owner))
        assert [o.id for o in orgs] == [org.id]

    @pytest.mark.anyio
    async def test_require_membership(self) -> None:
        store = FakeOrgStore()
        service = OrganizationService(store)
        owner = uuid.uuid4()
        org = await service.create_org(name="Acme", owner_id=owner)
        assert (await service.require_membership(org.id, owner)).role == "owner"
        with pytest.raises(ForbiddenError):
            await service.require_membership(org.id, uuid.uuid4())


# ---------------------------------------------------------------------------
# ApiKeyService
# ---------------------------------------------------------------------------


class TestApiKeyService:
    @pytest.mark.anyio
    async def test_create_authenticate_revoke(self) -> None:
        store = FakeApiKeyStore()
        service = ApiKeyService(store)
        org = uuid.uuid4()
        key, plaintext = await service.create_key(
            organization_id=org, name="ci", scopes=["analyze"]
        )
        assert plaintext.startswith(KEY_PREFIX)

        authed = await service.authenticate(plaintext)
        assert authed.id == key.id
        assert authed.last_used_at is not None  # touched

        await service.revoke_key(org, key.id)
        with pytest.raises(TenantNotResolvedError):
            await service.authenticate(plaintext)

    @pytest.mark.anyio
    async def test_authenticate_unknown_key(self) -> None:
        with pytest.raises(TenantNotResolvedError):
            await ApiKeyService(FakeApiKeyStore()).authenticate("atk_nope")

    @pytest.mark.anyio
    async def test_revoke_unknown_key(self) -> None:
        with pytest.raises(ApiKeyNotFoundError):
            await ApiKeyService(FakeApiKeyStore()).revoke_key(uuid.uuid4(), uuid.uuid4())


# ---------------------------------------------------------------------------
# SQLAlchemy stores (mocked session)
# ---------------------------------------------------------------------------


class TestSqlAlchemyStores:
    @pytest.mark.anyio
    async def test_org_store_create_adds_org_and_membership(self) -> None:
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        store = SqlAlchemyOrgStore(session)
        org = await store.create(name="Acme", slug="acme-1", owner_id=uuid.uuid4())
        assert org.name == "Acme"
        assert session.add.call_count == 2  # org + membership
        assert session.flush.await_count == 2

    @pytest.mark.anyio
    async def test_api_key_store_create_and_revoke(self) -> None:
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        store = SqlAlchemyApiKeyStore(session)
        key = await store.create(
            organization_id=uuid.uuid4(),
            name="k",
            key_hash="h",
            prefix="atk_x",
            scopes=["analyze"],
        )
        assert key.name == "k"
        session.add.assert_called_once()

        await store.revoke(key)
        assert key.revoked_at is not None

    @pytest.mark.anyio
    async def test_api_key_store_get_active_by_hash(self) -> None:
        existing = ApiKey(organization_id=uuid.uuid4(), name="k", key_hash="h", prefix="p")
        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.first.return_value = existing
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyApiKeyStore(session)
        assert await store.get_active_by_hash("h") is existing
