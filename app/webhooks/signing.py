"""
Outbound webhook signing.

The app signs each delivery so the receiver can verify authenticity — the mirror
of the inbound Stripe verification (M2.5b). Scheme: ``HMAC-SHA256`` over
``{timestamp}.{body}`` with the webhook's secret, sent as
``X-Webhook-Signature: t=<unix>,v1=<hex>``. Receivers should recompute and compare
in constant time, and reject stale timestamps.
"""

import hashlib
import hmac
import secrets
import time

WEBHOOK_SIGNATURE_HEADER = "X-Webhook-Signature"
SECRET_PREFIX = "whsec_"


def generate_webhook_secret() -> str:
    """Return a new random signing secret (returned to the tenant once)."""
    return f"{SECRET_PREFIX}{secrets.token_urlsafe(32)}"


def compute_signature(secret: str, body: bytes, timestamp: int) -> str:
    """Return the hex HMAC-SHA256 of ``{timestamp}.{body}`` under ``secret``."""
    signed = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def signature_header(secret: str, body: bytes, *, timestamp: int | None = None) -> str:
    """Build the ``t=…,v1=…`` signature header value for a delivery."""
    ts = int(time.time()) if timestamp is None else timestamp
    return f"t={ts},v1={compute_signature(secret, body, ts)}"
