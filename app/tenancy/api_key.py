"""
API key generation and hashing.

API keys are high-entropy random tokens, so a fast hash (SHA-256) is
appropriate — unlike passwords, they don't need a slow KDF. Only the hash is
stored; the plaintext is shown to the caller exactly once at creation.
"""

import hashlib
import secrets

KEY_PREFIX = "atk_"


def generate_api_key() -> tuple[str, str, str]:
    """Return ``(plaintext, prefix, key_hash)`` for a new API key.

    The ``prefix`` is a short, non-secret identifier stored for display/lookup;
    the ``plaintext`` is returned to the caller once and never persisted.
    """
    plaintext = f"{KEY_PREFIX}{secrets.token_urlsafe(24)}"
    prefix = plaintext[:12]
    return plaintext, prefix, hash_api_key(plaintext)


def hash_api_key(plaintext: str) -> str:
    """Return the SHA-256 hex digest of an API key plaintext."""
    return hashlib.sha256(plaintext.encode()).hexdigest()
