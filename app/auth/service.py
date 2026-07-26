"""
Authentication orchestration.

``AuthService`` is provider-agnostic: it resolves a provider from the registry,
turns the returned identity into an application user, and issues session tokens.
Local registration (signup) is handled here because it is a credential-provider
concern; federated providers auto-provision users on first login instead.
"""

import uuid

from app.auth.base import (
    AuthenticatedIdentity,
    InvalidCredentialsError,
    UserAlreadyExistsError,
    UserStore,
)
from app.auth.factory import AuthProviderContext, build_auth_provider
from app.auth.password import hash_password
from app.auth.tokens import TokenPair, TokenService
from app.config import Settings
from app.db.models import User


class AuthService:
    """Coordinates providers, the user store, and token issuance."""

    def __init__(
        self,
        user_store: UserStore,
        token_service: TokenService,
        settings: Settings,
    ) -> None:
        self._store = user_store
        self._tokens = token_service
        self._settings = settings

    def _context(self) -> AuthProviderContext:
        return AuthProviderContext(user_store=self._store, settings=self._settings)

    async def signup(
        self, email: str, password: str, name: str | None = None
    ) -> tuple[User, TokenPair]:
        """Register a new local user and issue tokens."""
        if await self._store.get_by_email(email) is not None:
            raise UserAlreadyExistsError("email already registered")
        user = await self._store.create(
            email=email, password_hash=hash_password(password), name=name
        )
        return user, self._tokens.issue_pair(str(user.id))

    async def login(
        self, credentials: dict[str, object], provider: str = "local"
    ) -> tuple[User, TokenPair]:
        """Authenticate via the named provider and issue tokens."""
        provider_obj = build_auth_provider(provider, self._context())
        identity = await provider_obj.authenticate(credentials)
        user = await self._resolve_user(identity, auto_provision=provider_obj.auto_provision)
        return user, self._tokens.issue_pair(str(user.id))

    async def refresh(self, refresh_token: str) -> TokenPair:
        """Exchange a valid refresh token for a new token pair."""
        payload = self._tokens.decode(refresh_token, expected_type="refresh")
        user = await self._store.get_by_id(uuid.UUID(str(payload["sub"])))
        if user is None:
            raise InvalidCredentialsError("user no longer exists")
        return self._tokens.issue_pair(str(user.id))

    async def get_current_user(self, access_token: str) -> User:
        """Resolve the user for a valid access token."""
        payload = self._tokens.decode(access_token, expected_type="access")
        user = await self._store.get_by_id(uuid.UUID(str(payload["sub"])))
        if user is None:
            raise InvalidCredentialsError("user no longer exists")
        return user

    async def _resolve_user(self, identity: AuthenticatedIdentity, *, auto_provision: bool) -> User:
        user = await self._store.get_by_email(identity.email)
        if user is None:
            if not auto_provision:
                raise InvalidCredentialsError("user not found")
            user = await self._store.create(
                email=identity.email, password_hash=None, name=identity.display_name
            )
        return user
