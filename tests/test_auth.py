"""
Unit tests for the authentication layer (Milestone M2.2).

Covers password hashing, the token service, the local provider, the
provider-agnostic AuthService, the SQLAlchemy user store (mocked session), and
the auth DI dependencies — all without a live database.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.auth.base import (
    AuthenticatedIdentity,
    InvalidCredentialsError,
    UserAlreadyExistsError,
)
from app.auth.local_provider import LocalAuthProvider
from app.auth.password import hash_password, verify_password
from app.auth.service import AuthService
from app.auth.tokens import TokenError, TokenService
from app.config import Settings
from app.db.models import User
from app.db.user_store import SqlAlchemyUserStore


class FakeUserStore:
    """In-memory UserStore for tests (no database required)."""

    def __init__(self) -> None:
        self._by_email: dict[str, User] = {}
        self._by_id: dict[uuid.UUID, User] = {}

    async def get_by_email(self, email: str) -> User | None:
        return self._by_email.get(email)

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self._by_id.get(user_id)

    async def create(self, *, email: str, password_hash: str | None, name: str | None) -> User:
        user = User(email=email, password_hash=password_hash, name=name)
        user.id = uuid.uuid4()
        user.is_verified = False
        self._by_email[email] = user
        self._by_id[user.id] = user
        return user


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _token_service(**overrides: object) -> TokenService:
    return TokenService("test-secret-key", **overrides)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


class TestPassword:
    def test_hash_and_verify_roundtrip(self) -> None:
        h = hash_password("s3cret-pass")
        assert h != "s3cret-pass"
        assert verify_password(h, "s3cret-pass") is True

    def test_wrong_password_fails(self) -> None:
        h = hash_password("s3cret-pass")
        assert verify_password(h, "wrong") is False

    def test_invalid_hash_returns_false(self) -> None:
        assert verify_password("not-a-hash", "x") is False


# ---------------------------------------------------------------------------
# Token service
# ---------------------------------------------------------------------------


class TestTokens:
    def test_issue_and_decode_pair(self) -> None:
        ts = _token_service()
        pair = ts.issue_pair("user-1")
        access = ts.decode(pair.access_token, expected_type="access")
        refresh = ts.decode(pair.refresh_token, expected_type="refresh")
        assert access["sub"] == "user-1"
        assert refresh["sub"] == "user-1"

    def test_wrong_type_rejected(self) -> None:
        ts = _token_service()
        token = ts.create_access_token("user-1")
        with pytest.raises(TokenError):
            ts.decode(token, expected_type="refresh")

    def test_tampered_token_rejected(self) -> None:
        ts = _token_service()
        token = ts.create_access_token("user-1")
        with pytest.raises(TokenError):
            ts.decode(token + "tamper", expected_type="access")

    def test_expired_token_rejected(self) -> None:
        ts = _token_service(access_ttl_seconds=-10)
        token = ts.create_access_token("user-1")
        with pytest.raises(TokenError):
            ts.decode(token, expected_type="access")


# ---------------------------------------------------------------------------
# Local provider
# ---------------------------------------------------------------------------


class TestLocalProvider:
    @pytest.mark.anyio
    async def test_authenticate_success(self) -> None:
        store = FakeUserStore()
        await store.create(email="a@b.test", password_hash=hash_password("pw12345678"), name="A")
        provider = LocalAuthProvider(store)
        identity = await provider.authenticate({"email": "a@b.test", "password": "pw12345678"})
        assert isinstance(identity, AuthenticatedIdentity)
        assert identity.provider == "local"
        assert identity.email == "a@b.test"

    @pytest.mark.anyio
    async def test_authenticate_wrong_password(self) -> None:
        store = FakeUserStore()
        await store.create(email="a@b.test", password_hash=hash_password("pw12345678"), name=None)
        with pytest.raises(InvalidCredentialsError):
            await LocalAuthProvider(store).authenticate({"email": "a@b.test", "password": "no"})

    @pytest.mark.anyio
    async def test_authenticate_unknown_user(self) -> None:
        with pytest.raises(InvalidCredentialsError):
            await LocalAuthProvider(FakeUserStore()).authenticate(
                {"email": "x@y.test", "password": "whatever"}
            )

    @pytest.mark.anyio
    async def test_authenticate_missing_fields(self) -> None:
        with pytest.raises(InvalidCredentialsError):
            await LocalAuthProvider(FakeUserStore()).authenticate({"email": "x@y.test"})


# ---------------------------------------------------------------------------
# AuthService
# ---------------------------------------------------------------------------


class TestAuthService:
    def _service(self) -> tuple[AuthService, FakeUserStore]:
        store = FakeUserStore()
        return AuthService(store, _token_service(), _settings()), store

    @pytest.mark.anyio
    async def test_signup_then_login(self) -> None:
        service, _ = self._service()
        user, pair = await service.signup("new@user.test", "password123", "New")
        assert user.email == "new@user.test"
        assert pair.access_token and pair.refresh_token

        logged_in, login_pair = await service.login(
            {"email": "new@user.test", "password": "password123"}
        )
        assert logged_in.id == user.id
        assert login_pair.access_token

    @pytest.mark.anyio
    async def test_signup_duplicate_rejected(self) -> None:
        service, _ = self._service()
        await service.signup("dup@user.test", "password123")
        with pytest.raises(UserAlreadyExistsError):
            await service.signup("dup@user.test", "password123")

    @pytest.mark.anyio
    async def test_login_wrong_password(self) -> None:
        service, _ = self._service()
        await service.signup("u@user.test", "password123")
        with pytest.raises(InvalidCredentialsError):
            await service.login({"email": "u@user.test", "password": "nope"})

    @pytest.mark.anyio
    async def test_refresh_issues_new_pair(self) -> None:
        service, _ = self._service()
        _user, pair = await service.signup("r@user.test", "password123")
        new_pair = await service.refresh(pair.refresh_token)
        assert new_pair.access_token

    @pytest.mark.anyio
    async def test_refresh_rejects_access_token(self) -> None:
        service, _ = self._service()
        _user, pair = await service.signup("r2@user.test", "password123")
        with pytest.raises(TokenError):
            await service.refresh(pair.access_token)

    @pytest.mark.anyio
    async def test_get_current_user(self) -> None:
        service, _ = self._service()
        user, pair = await service.signup("me@user.test", "password123")
        resolved = await service.get_current_user(pair.access_token)
        assert resolved.id == user.id

    @pytest.mark.anyio
    async def test_get_current_user_rejects_refresh_token(self) -> None:
        service, _ = self._service()
        _user, pair = await service.signup("me2@user.test", "password123")
        with pytest.raises(TokenError):
            await service.get_current_user(pair.refresh_token)

    @pytest.mark.anyio
    async def test_refresh_unknown_user(self) -> None:
        service, store = self._service()
        user, pair = await service.signup("gone@user.test", "password123")
        store._by_id.pop(user.id)  # simulate deleted user
        with pytest.raises(InvalidCredentialsError):
            await service.refresh(pair.refresh_token)

    @pytest.mark.anyio
    async def test_get_current_user_unknown(self) -> None:
        service, store = self._service()
        user, pair = await service.signup("gone2@user.test", "password123")
        store._by_id.pop(user.id)
        with pytest.raises(InvalidCredentialsError):
            await service.get_current_user(pair.access_token)

    @pytest.mark.anyio
    async def test_federated_provider_auto_provisions_user(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A provider with auto_provision=True creates a user on first login.

        Demonstrates that the provider-agnostic AuthService supports federated
        (OAuth/OIDC-style) providers with no changes to its logic.
        """
        import app.auth.factory as factory

        class _FederatedProvider(LocalAuthProvider):
            @property
            def name(self) -> str:
                return "fake-oauth"

            @property
            def auto_provision(self) -> bool:
                return True

            async def authenticate(self, credentials: dict) -> AuthenticatedIdentity:  # type: ignore[override]
                return AuthenticatedIdentity(
                    provider="fake-oauth",
                    subject="ext-123",
                    email=credentials["email"],
                    email_verified=True,
                    display_name="Federated User",
                )

        monkeypatch.setitem(
            factory._PROVIDERS, "fake-oauth", lambda ctx: _FederatedProvider(ctx.user_store)
        )
        service, store = self._service()
        user, pair = await service.login({"email": "fed@user.test"}, provider="fake-oauth")
        assert user.email == "fed@user.test"
        assert await store.get_by_email("fed@user.test") is not None
        assert pair.access_token


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------


class TestAuthFactory:
    def test_local_is_registered(self) -> None:
        from app.auth.factory import available_auth_providers

        assert "local" in available_auth_providers()

    def test_unknown_provider_raises(self) -> None:
        from app.auth.factory import AuthProviderContext, build_auth_provider

        ctx = AuthProviderContext(user_store=FakeUserStore(), settings=_settings())
        with pytest.raises(ValueError, match="Unsupported auth provider"):
            build_auth_provider("does-not-exist", ctx)


# ---------------------------------------------------------------------------
# SqlAlchemyUserStore (mocked session)
# ---------------------------------------------------------------------------


class TestSqlAlchemyUserStore:
    @pytest.mark.anyio
    async def test_get_by_email(self) -> None:
        existing = User(email="a@b.test")
        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.first.return_value = existing
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyUserStore(session)
        assert await store.get_by_email("a@b.test") is existing

    @pytest.mark.anyio
    async def test_get_by_id(self) -> None:
        existing = User(email="a@b.test")
        session = MagicMock()
        session.get = AsyncMock(return_value=existing)
        store = SqlAlchemyUserStore(session)
        assert await store.get_by_id(uuid.uuid4()) is existing

    @pytest.mark.anyio
    async def test_create(self) -> None:
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        store = SqlAlchemyUserStore(session)
        user = await store.create(email="a@b.test", password_hash="h", name="A")
        assert user.email == "a@b.test"
        session.add.assert_called_once()
        session.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# Auth dependencies
# ---------------------------------------------------------------------------


class _CtxSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolledback = False

    async def __aenter__(self) -> "_CtxSession":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolledback = True


class TestAuthDependencies:
    def test_get_token_service_returns_configured(self) -> None:
        from app.dependencies import get_token_service

        ts = _token_service()
        request = MagicMock()
        request.app.state.token_service = ts
        assert get_token_service(request) is ts

    def test_get_token_service_unconfigured_raises_503(self) -> None:
        from app.dependencies import get_token_service
        from fastapi import HTTPException

        request = MagicMock()
        request.app.state.token_service = None
        with pytest.raises(HTTPException) as exc:
            get_token_service(request)
        assert exc.value.status_code == 503

    def test_get_user_store_and_auth_service(self) -> None:
        from app.dependencies import get_auth_service, get_user_store

        store = get_user_store(session=MagicMock())
        assert isinstance(store, SqlAlchemyUserStore)

        request = MagicMock()
        request.app.state.settings = _settings()
        service = get_auth_service(
            request, user_store=FakeUserStore(), token_service=_token_service()
        )
        assert isinstance(service, AuthService)

    @pytest.mark.anyio
    async def test_get_db_session_unconfigured_raises_503(self) -> None:
        from app.dependencies import get_db_session
        from fastapi import HTTPException

        gen = get_db_session(None)
        with pytest.raises(HTTPException) as exc:
            await gen.__anext__()
        assert exc.value.status_code == 503

    @pytest.mark.anyio
    async def test_get_db_session_yields_and_commits(self) -> None:
        from app.dependencies import get_db_session

        session = _CtxSession()
        gen = get_db_session(MagicMock(return_value=session))
        yielded = await gen.__anext__()
        assert yielded is session
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()
        assert session.committed is True

    @pytest.mark.anyio
    async def test_get_db_session_rolls_back_on_error(self) -> None:
        from app.dependencies import get_db_session

        session = _CtxSession()
        gen = get_db_session(MagicMock(return_value=session))
        await gen.__anext__()
        with pytest.raises(RuntimeError):
            await gen.athrow(RuntimeError("boom"))
        assert session.rolledback is True
