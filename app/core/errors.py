"""
Standardized error responses for AI Ticket Analyzer.

Defines a consistent error envelope and exception handlers that preserve HTTP
status codes while ensuring every error carries a correlation id.

Envelope shape::

    {
        "error": {
            "code": "<machine_readable_slug>",
            "message": "<human readable message>",
            "request_id": "<correlation id>",
            "details": <optional, e.g. validation errors>
        }
    }
"""

import logging
from http import HTTPStatus
from typing import Any
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app.ai.base import (
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from app.core.middleware import REQUEST_ID_HEADER, SECURITY_HEADERS

logger = logging.getLogger(__name__)

# Stable, version-independent machine-readable codes. Deliberately decoupled
# from ``HTTPStatus.phrase`` (which varies across Python versions, e.g. 422
# "Unprocessable Entity" vs "Unprocessable Content") so the API contract is
# stable for clients.
_STATUS_CODES: dict[int, str] = {
    HTTPStatus.BAD_REQUEST: "bad_request",
    HTTPStatus.PAYMENT_REQUIRED: "payment_required",
    HTTPStatus.NOT_FOUND: "not_found",
    HTTPStatus.UNPROCESSABLE_ENTITY: "validation_error",
    HTTPStatus.TOO_MANY_REQUESTS: "rate_limited",
    HTTPStatus.INTERNAL_SERVER_ERROR: "internal_error",
    HTTPStatus.BAD_GATEWAY: "upstream_error",
    HTTPStatus.SERVICE_UNAVAILABLE: "service_unavailable",
    HTTPStatus.GATEWAY_TIMEOUT: "upstream_timeout",
}


def _code_for_status(status_code: int) -> str:
    """Return a stable, machine-readable code slug for an HTTP status code."""
    return _STATUS_CODES.get(status_code, f"http_{status_code}")


def _request_id(request: Request) -> str:
    """Return the request's correlation id, generating one if absent.

    The ``RequestContextMiddleware`` normally sets this; the fallback guards
    error paths (e.g. unhandled 500s handled outside the middleware stack).
    """
    request_id: str | None = getattr(request.state, "request_id", None)
    if not request_id:
        request_id = uuid4().hex
        request.state.request_id = request_id
    return request_id


def build_error_response(
    status_code: int,
    message: str,
    request_id: str,
    details: Any | None = None,
) -> JSONResponse:
    """Build a JSON error response using the standard envelope.

    Security headers and the correlation-id header are attached directly so the
    response is consistent even when produced outside the middleware stack.
    """
    error: dict[str, Any] = {
        "code": _code_for_status(status_code),
        "message": message,
        "request_id": request_id,
    }
    if details is not None:
        error["details"] = details

    headers = {REQUEST_ID_HEADER: request_id, **SECURITY_HEADERS}
    return JSONResponse(status_code=status_code, content={"error": error}, headers=headers)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Render Starlette/FastAPI HTTPExceptions in the standard envelope."""
    request_id = _request_id(request)
    logger.info(
        "HTTP error [request_id=%s] %s %s -> %d",
        request_id,
        request.method,
        request.url.path,
        exc.status_code,
    )
    return build_error_response(exc.status_code, str(exc.detail), request_id)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Render request-validation errors (422) in the standard envelope."""
    request_id = _request_id(request)
    return build_error_response(
        HTTPStatus.UNPROCESSABLE_ENTITY,
        "Request validation failed",
        request_id,
        details=jsonable_encoder(exc.errors()),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render unexpected errors (500) without leaking internal details."""
    request_id = _request_id(request)
    logger.exception("Unhandled error [request_id=%s]", request_id)
    return build_error_response(
        HTTPStatus.INTERNAL_SERVER_ERROR,
        "An internal error occurred.",
        request_id,
    )


async def provider_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map provider-agnostic ``Provider*`` errors to HTTP responses.

    Centralizing this means every endpoint that calls a provider (legacy
    ``/analyze`` and ``/v1/analyze``) gets identical error behavior without
    duplicating the mapping. Registered for ``ProviderError``, so all subclasses
    are covered.
    """
    request_id = _request_id(request)
    if isinstance(exc, ProviderTimeoutError):
        status, message = HTTPStatus.GATEWAY_TIMEOUT, "The AI service timed out. Please try again."
    elif isinstance(exc, ProviderRateLimitError):
        status, message = (
            HTTPStatus.TOO_MANY_REQUESTS,
            "AI service rate limit reached. Please retry after a moment.",
        )
    elif isinstance(exc, ProviderResponseError):
        status, message = HTTPStatus.BAD_GATEWAY, f"Invalid AI response: {exc}"
    else:
        status, message = (
            HTTPStatus.BAD_GATEWAY,
            "The AI service is currently unavailable. Please try again later.",
        )
    logger.error("AI provider error [request_id=%s]: %s", request_id, exc)
    return build_error_response(status, message, request_id)
