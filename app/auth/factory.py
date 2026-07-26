"""
Authentication provider registry and factory.

Selects an ``AuthProvider`` by name. To add a federated provider (Google,
GitHub, Microsoft Entra, Auth0, any OIDC/OAuth2):

1. Implement :class:`~app.auth.base.AuthProvider` in a new module.
2. Add one entry to ``_PROVIDERS`` below.

The ``AuthProviderContext`` carries everything a provider might need (the user
store and application settings), so adding a provider needs no signature change
and no changes to business logic, routes, services, or authorization.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.auth.base import AuthProvider, UserStore
from app.auth.local_provider import LocalAuthProvider
from app.config import Settings


@dataclass(frozen=True)
class AuthProviderContext:
    """Inputs available to construct any auth provider."""

    user_store: UserStore
    settings: Settings


_PROVIDERS: dict[str, Callable[[AuthProviderContext], AuthProvider]] = {
    "local": lambda ctx: LocalAuthProvider(ctx.user_store),
}


def available_auth_providers() -> list[str]:
    """Return the sorted list of registered auth provider names."""
    return sorted(_PROVIDERS)


def build_auth_provider(name: str, context: AuthProviderContext) -> AuthProvider:
    """Construct the named auth provider.

    Raises:
        ValueError: If the provider name is not registered.
    """
    factory = _PROVIDERS.get(name.lower())
    if factory is None:
        raise ValueError(
            f"Unsupported auth provider {name!r}. Supported: "
            f"{', '.join(available_auth_providers())}."
        )
    return factory(context)
