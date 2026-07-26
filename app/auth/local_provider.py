"""
Local email/password authentication provider.

Verifies credentials against the application's own user store. This is the only
provider that consults our database for credentials; federated providers verify
against an external IdP instead.
"""

from collections.abc import Mapping
from typing import Any

from app.auth.base import (
    AuthenticatedIdentity,
    AuthProvider,
    InvalidCredentialsError,
    UserStore,
)
from app.auth.password import verify_password


class LocalAuthProvider(AuthProvider):
    """Authenticate users by email + password against the local user store."""

    def __init__(self, user_store: UserStore) -> None:
        self._store = user_store

    @property
    def name(self) -> str:
        return "local"

    async def authenticate(self, credentials: Mapping[str, Any]) -> AuthenticatedIdentity:
        email = credentials.get("email")
        password = credentials.get("password")
        if not email or not password:
            raise InvalidCredentialsError("email and password are required")

        user = await self._store.get_by_email(email)
        if user is None or user.password_hash is None:
            raise InvalidCredentialsError("invalid email or password")
        if not verify_password(user.password_hash, password):
            raise InvalidCredentialsError("invalid email or password")

        return AuthenticatedIdentity(
            provider=self.name,
            subject=str(user.id),
            email=user.email,
            email_verified=user.is_verified,
            display_name=user.name,
        )
