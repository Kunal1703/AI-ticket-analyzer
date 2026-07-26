"""
HTTP route tests for authentication (Milestone M2.2).

Exercises the full signup/login/me/refresh flow against the real app, with the
user store and token service overridden so no database is required.
"""

from collections.abc import Generator

import pytest
from app.auth.tokens import TokenService
from httpx import AsyncClient

from tests.test_auth import FakeUserStore


@pytest.fixture
def auth_overrides() -> Generator[FakeUserStore, None, None]:
    """Override the user store + token service so auth works without a DB."""
    from app.dependencies import get_token_service, get_user_store
    from app.main import app

    store = FakeUserStore()
    app.dependency_overrides[get_user_store] = lambda: store
    app.dependency_overrides[get_token_service] = lambda: TokenService("test-secret-key")
    yield store
    app.dependency_overrides.pop(get_user_store, None)
    app.dependency_overrides.pop(get_token_service, None)


class TestAuthFlow:
    @pytest.mark.anyio
    async def test_signup_login_me_refresh(
        self, client: AsyncClient, auth_overrides: FakeUserStore
    ) -> None:
        # Signup
        resp = await client.post(
            "/v1/auth/signup",
            json={"email": "user@example.com", "password": "password123", "name": "User"},
        )
        assert resp.status_code == 201
        tokens = resp.json()
        assert tokens["token_type"] == "bearer"
        assert tokens["access_token"] and tokens["refresh_token"]

        # Me (with access token)
        me = await client.get(
            "/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        assert me.status_code == 200
        assert me.json()["email"] == "user@example.com"

        # Login
        login = await client.post(
            "/v1/auth/login",
            json={"email": "user@example.com", "password": "password123"},
        )
        assert login.status_code == 200

        # Refresh
        refresh = await client.post(
            "/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert refresh.status_code == 200
        assert refresh.json()["access_token"]

    @pytest.mark.anyio
    async def test_signup_duplicate_returns_409(
        self, client: AsyncClient, auth_overrides: FakeUserStore
    ) -> None:
        body = {"email": "dup@example.com", "password": "password123"}
        assert (await client.post("/v1/auth/signup", json=body)).status_code == 201
        assert (await client.post("/v1/auth/signup", json=body)).status_code == 409

    @pytest.mark.anyio
    async def test_login_wrong_password_returns_401(
        self, client: AsyncClient, auth_overrides: FakeUserStore
    ) -> None:
        await client.post(
            "/v1/auth/signup", json={"email": "u@example.com", "password": "password123"}
        )
        resp = await client.post(
            "/v1/auth/login", json={"email": "u@example.com", "password": "wrong"}
        )
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_me_without_token_returns_401(
        self, client: AsyncClient, auth_overrides: FakeUserStore
    ) -> None:
        assert (await client.get("/v1/auth/me")).status_code == 401

    @pytest.mark.anyio
    async def test_me_with_bad_token_returns_401(
        self, client: AsyncClient, auth_overrides: FakeUserStore
    ) -> None:
        resp = await client.get("/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_refresh_invalid_token_returns_401(
        self, client: AsyncClient, auth_overrides: FakeUserStore
    ) -> None:
        resp = await client.post("/v1/auth/refresh", json={"refresh_token": "not-a-jwt"})
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_signup_validation_error(
        self, client: AsyncClient, auth_overrides: FakeUserStore
    ) -> None:
        # Password too short -> 422 validation error.
        resp = await client.post(
            "/v1/auth/signup", json={"email": "x@example.com", "password": "short"}
        )
        assert resp.status_code == 422


class TestAuthDisabled:
    @pytest.mark.anyio
    async def test_login_without_database_returns_503(self, client: AsyncClient) -> None:
        # No overrides: the default app has no DB configured.
        resp = await client.post(
            "/v1/auth/login", json={"email": "u@example.com", "password": "password123"}
        )
        assert resp.status_code == 503
