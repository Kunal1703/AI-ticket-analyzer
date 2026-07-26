"""
HTTP route tests for tenancy (Milestone M2.3): org creation, API key lifecycle,
tenant-context resolution (API key vs user JWT), and cross-tenant isolation.

All stores are overridden with in-memory fakes, so no database is required.
"""

from collections.abc import Generator
from typing import Any

import pytest
from app.auth.tokens import TokenService
from httpx import AsyncClient

from tests.test_auth import FakeUserStore
from tests.test_tenancy_service import FakeApiKeyStore, FakeOrgStore


@pytest.fixture
def tenancy_overrides() -> Generator[dict[str, Any], None, None]:
    from app.dependencies import (
        get_api_key_store,
        get_optional_token_service,
        get_org_store,
        get_token_service,
        get_user_store,
    )
    from app.main import app

    stores = {"users": FakeUserStore(), "orgs": FakeOrgStore(), "keys": FakeApiKeyStore()}
    token_service = TokenService("test-secret-key")
    app.dependency_overrides[get_user_store] = lambda: stores["users"]
    app.dependency_overrides[get_org_store] = lambda: stores["orgs"]
    app.dependency_overrides[get_api_key_store] = lambda: stores["keys"]
    app.dependency_overrides[get_token_service] = lambda: token_service
    app.dependency_overrides[get_optional_token_service] = lambda: token_service
    yield stores
    for dep in (
        get_user_store,
        get_org_store,
        get_api_key_store,
        get_token_service,
        get_optional_token_service,
    ):
        app.dependency_overrides.pop(dep, None)


async def _signup(client: AsyncClient, email: str) -> str:
    resp = await client.post("/v1/auth/signup", json={"email": email, "password": "password123"})
    assert resp.status_code == 201
    return str(resp.json()["access_token"])


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestTenancyFlow:
    @pytest.mark.anyio
    async def test_full_lifecycle(
        self, client: AsyncClient, tenancy_overrides: dict[str, Any]
    ) -> None:
        token = await _signup(client, "owner@example.com")

        # Create org
        org = await client.post("/v1/orgs", json={"name": "Acme"}, headers=_bearer(token))
        assert org.status_code == 201
        org_id = org.json()["id"]

        # Create API key (plaintext returned once)
        created = await client.post(
            f"/v1/orgs/{org_id}/api-keys",
            json={"name": "ci", "scopes": ["analyze"]},
            headers=_bearer(token),
        )
        assert created.status_code == 201
        body = created.json()
        api_key = body["api_key"]
        key_id = body["id"]
        assert api_key.startswith("atk_")

        # Tenant context via API key
        via_key = await client.get("/v1/tenant", headers={"X-API-Key": api_key})
        assert via_key.status_code == 200
        assert via_key.json()["organization_id"] == org_id
        assert via_key.json()["principal_type"] == "api_key"
        assert via_key.json()["scopes"] == ["analyze"]

        # Tenant context via user JWT (single org)
        via_user = await client.get("/v1/tenant", headers=_bearer(token))
        assert via_user.status_code == 200
        assert via_user.json()["organization_id"] == org_id
        assert via_user.json()["principal_type"] == "user"

        # List keys (never exposes the secret)
        listed = await client.get(f"/v1/orgs/{org_id}/api-keys", headers=_bearer(token))
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        assert "api_key" not in listed.json()[0]

        # Revoke
        revoked = await client.delete(
            f"/v1/orgs/{org_id}/api-keys/{key_id}", headers=_bearer(token)
        )
        assert revoked.status_code == 204

        # Revoked key no longer resolves
        after = await client.get("/v1/tenant", headers={"X-API-Key": api_key})
        assert after.status_code == 401

    @pytest.mark.anyio
    async def test_cross_tenant_denied(
        self, client: AsyncClient, tenancy_overrides: dict[str, Any]
    ) -> None:
        token1 = await _signup(client, "u1@example.com")
        token2 = await _signup(client, "u2@example.com")
        # user2 creates their own org
        org2 = (
            await client.post("/v1/orgs", json={"name": "Org2"}, headers=_bearer(token2))
        ).json()
        # user1 tries to create a key in user2's org -> 403
        resp = await client.post(
            f"/v1/orgs/{org2['id']}/api-keys", json={"name": "x"}, headers=_bearer(token1)
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_tenant_requires_auth(
        self, client: AsyncClient, tenancy_overrides: dict[str, Any]
    ) -> None:
        assert (await client.get("/v1/tenant")).status_code == 401

    @pytest.mark.anyio
    async def test_user_without_org_is_forbidden(
        self, client: AsyncClient, tenancy_overrides: dict[str, Any]
    ) -> None:
        token = await _signup(client, "noorg@example.com")
        assert (await client.get("/v1/tenant", headers=_bearer(token))).status_code == 403

    @pytest.mark.anyio
    async def test_multiple_orgs_require_selection(
        self, client: AsyncClient, tenancy_overrides: dict[str, Any]
    ) -> None:
        token = await _signup(client, "multi@example.com")
        a = (await client.post("/v1/orgs", json={"name": "A"}, headers=_bearer(token))).json()
        await client.post("/v1/orgs", json={"name": "B"}, headers=_bearer(token))

        ambiguous = await client.get("/v1/tenant", headers=_bearer(token))
        assert ambiguous.status_code == 400

        selected = await client.get(
            "/v1/tenant", headers={**_bearer(token), "X-Organization-Id": a["id"]}
        )
        assert selected.status_code == 200
        assert selected.json()["organization_id"] == a["id"]

    @pytest.mark.anyio
    async def test_revoke_unknown_key_404(
        self, client: AsyncClient, tenancy_overrides: dict[str, Any]
    ) -> None:
        token = await _signup(client, "rk@example.com")
        org = (await client.post("/v1/orgs", json={"name": "Acme"}, headers=_bearer(token))).json()
        import uuid

        resp = await client.delete(
            f"/v1/orgs/{org['id']}/api-keys/{uuid.uuid4()}", headers=_bearer(token)
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_list_orgs(self, client: AsyncClient, tenancy_overrides: dict[str, Any]) -> None:
        token = await _signup(client, "lister@example.com")
        await client.post("/v1/orgs", json={"name": "A"}, headers=_bearer(token))
        await client.post("/v1/orgs", json={"name": "B"}, headers=_bearer(token))
        resp = await client.get("/v1/orgs", headers=_bearer(token))
        assert resp.status_code == 200
        assert len(resp.json()) == 2
