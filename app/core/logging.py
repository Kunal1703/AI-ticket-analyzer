"""
Logging configuration for AI Ticket Analyzer.

Provides structured (JSON) or human-readable logging, both correlated with a
per-request id via a ``ContextVar`` that the request middleware populates. The
application factory configures logging explicitly (not as an import-time side
effect).
"""

import json
import logging
from contextvars import ContextVar

from app.config import Settings

# Correlation id for the current request, set by RequestContextMiddleware.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    """Inject the current request id onto every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def resolve_log_level(debug: bool, log_level: str) -> str:
    """Resolve the effective logging level.

    When ``debug`` is enabled, logging is forced to ``DEBUG`` regardless of
    ``log_level``. Otherwise the configured ``log_level`` is used (upper-cased).
    """
    return "DEBUG" if debug else log_level.upper()


def _build_handler(log_format: str) -> logging.Handler:
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    if log_format.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | [%(request_id)s] | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    return handler


def configure_logging(settings: Settings) -> None:
    """Configure the root logger from application settings.

    Uses ``force=True`` so repeated configuration (e.g. building multiple apps
    in tests) replaces handlers cleanly rather than accumulating them.
    """
    logging.basicConfig(
        level=resolve_log_level(settings.debug, settings.log_level),
        handlers=[_build_handler(settings.log_format)],
        force=True,
    )
