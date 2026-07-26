"""
Provider-agnostic authentication interface.

Mirrors the ``AnalysisProvider`` design: an ``AuthProvider`` verifies an external
credential and returns a normalized :class:`AuthenticatedIdentity`. It never
issues sessions/JWTs or resolves application users — those are provider-agnostic
concerns handled by the token service and ``AuthService``. New providers
(Google, GitHub, Microsoft Entra, Auth0, any OIDC/OAuth2) can be added by
implementing this interface and registering them, with no changes to business
logic, routes, services, repositories, or authorization.
"""

import uuid
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from app.db.models import User


class AuthError(Exception):
    """Base class for authentication failures."""


class InvalidCredentialsError(AuthError):
    """The supplied credentials were missing or invalid (maps to HTTP 401)."""


class UserAlreadyExistsError(AuthError):
    """Registration attempted for an email that already exists (maps to HTTP 409)."""


class AuthProviderError(AuthError):
    """The provider is misconfigured or unavailable (maps to HTTP 503)."""


@dataclass(frozen=True)
class AuthenticatedIdentity:
    """A normalized identity returned by an auth provider.

    Attributes:
        provider: Registered provider name (e.g. ``"local"``, ``"google"``).
        subject: Provider-unique identifier for the principal.
        email: The principal's email address.
        email_verified: Whether the provider considers the email verified.
        display_name: Optional human-readable name.
    """

    provider: str
    subject: str
    email: str
    email_verified: bool = False
    display_name: str | None = None


class UserStore(Protocol):
    """Persistence port for application users (decouples auth from the ORM)."""

    async def get_by_email(self, email: str) -> User | None: ...

    async def get_by_id(self, user_id: uuid.UUID) -> User | None: ...

    async def create(self, *, email: str, password_hash: str | None, name: str | None) -> User: ...


class AuthProvider(ABC):
    """Interface every authentication backend implements."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Registered provider name."""

    @property
    def auto_provision(self) -> bool:
        """Whether an unknown identity should auto-create a user on first login.

        Local password auth returns ``False`` (users register explicitly);
        federated providers typically return ``True``.
        """
        return False

    @abstractmethod
    async def authenticate(self, credentials: Mapping[str, Any]) -> AuthenticatedIdentity:
        """Verify credentials and return the authenticated identity.

        Raises:
            InvalidCredentialsError: Credentials are missing or invalid.
            AuthProviderError: The provider is misconfigured/unavailable.
        """
