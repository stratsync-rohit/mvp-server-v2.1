"""Structured JSON logging configuration."""

import logging
import sys
from contextvars import ContextVar

from pythonjsonlogger.json import JsonFormatter

request_id_context: ContextVar[str] = ContextVar("request_id", default="")


class RequestContextFilter(logging.Filter):
    """Add the request correlation ID stored in the current context."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Attach the current request ID to a log record."""
        record.request_id = request_id_context.get()
        return True


def configure_logging(level: str) -> None:
    """Configure one JSON-compatible stdout handler for the application."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(
        JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
