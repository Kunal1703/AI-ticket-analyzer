"""
Custom ASGI middleware for AI Ticket Analyzer.

Provides:

* ``RequestContextMiddleware`` — assigns a correlation id to every request and
  echoes it back via the ``X-Request-ID`` response header.
* ``SecurityHeadersMiddleware`` — attaches a conservative set of security
  headers to every response.
"""

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"

# Conservative security headers applied to every response. ``setdefault`` is
# used at application time so explicitly-set values are never overwritten.
SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a correlation id to each request and echo it in the response.

    Honors an inbound ``X-Request-ID`` header when present; otherwise generates
    a new identifier. The id is stored on ``request.state.request_id`` so that
    handlers and exception handlers can include it in log lines and responses.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid4().hex
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach a conservative set of security headers to every response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response
