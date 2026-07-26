"""
JWT access/refresh token service.

Provider-agnostic: every authentication provider's identity is turned into the
application's own session tokens here, so session handling is identical across
local and federated providers.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


class TokenError(Exception):
    """A token was missing, malformed, expired, or of the wrong type."""


@dataclass(frozen=True)
class TokenPair:
    """An issued access + refresh token pair."""

    access_token: str
    refresh_token: str


class TokenService:
    """Issues and verifies signed JWT access/refresh tokens."""

    def __init__(
        self,
        secret: str,
        *,
        algorithm: str = "HS256",
        access_ttl_seconds: int = 900,
        refresh_ttl_seconds: int = 1_209_600,
    ) -> None:
        self._secret = secret
        self._algorithm = algorithm
        self._access_ttl = access_ttl_seconds
        self._refresh_ttl = refresh_ttl_seconds

    def _encode(self, subject: str, token_type: str, ttl_seconds: int) -> str:
        now = datetime.now(UTC)
        payload: dict[str, Any] = {
            "sub": subject,
            "type": token_type,
            "iat": now,
            "exp": now + timedelta(seconds=ttl_seconds),
            "jti": uuid.uuid4().hex,
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def create_access_token(self, subject: str) -> str:
        """Create a short-lived access token for the given user id."""
        return self._encode(subject, ACCESS_TOKEN_TYPE, self._access_ttl)

    def create_refresh_token(self, subject: str) -> str:
        """Create a long-lived refresh token for the given user id."""
        return self._encode(subject, REFRESH_TOKEN_TYPE, self._refresh_ttl)

    def issue_pair(self, subject: str) -> TokenPair:
        """Create a fresh access + refresh token pair."""
        return TokenPair(
            access_token=self.create_access_token(subject),
            refresh_token=self.create_refresh_token(subject),
        )

    def decode(self, token: str, *, expected_type: str) -> dict[str, Any]:
        """Verify a token's signature/expiry/type and return its claims.

        Raises:
            TokenError: If the token is invalid, expired, or the wrong type.
        """
        try:
            payload: dict[str, Any] = jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except jwt.PyJWTError as exc:
            raise TokenError(str(exc)) from exc
        if payload.get("type") != expected_type:
            raise TokenError("unexpected token type")
        return payload
