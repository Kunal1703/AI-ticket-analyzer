"""Provider-agnostic authentication package."""

from app.auth.base import (
    AuthenticatedIdentity,
    AuthError,
    AuthProvider,
    AuthProviderError,
    InvalidCredentialsError,
    UserAlreadyExistsError,
    UserStore,
)
from app.auth.factory import (
    AuthProviderContext,
    available_auth_providers,
    build_auth_provider,
)
from app.auth.service import AuthService
from app.auth.tokens import TokenError, TokenPair, TokenService

__all__ = [
    "AuthProvider",
    "AuthenticatedIdentity",
    "AuthError",
    "AuthProviderError",
    "InvalidCredentialsError",
    "UserAlreadyExistsError",
    "UserStore",
    "AuthProviderContext",
    "available_auth_providers",
    "build_auth_provider",
    "AuthService",
    "TokenService",
    "TokenPair",
    "TokenError",
]
