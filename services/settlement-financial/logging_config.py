"""
logging_config.py — Structured JSON logging for Cloud Logging.

All log records are emitted as newline-delimited JSON so that Cloud Logging
can parse them as structured entries.  Extra keyword arguments passed to any
logger method are forwarded as top-level JSON fields via the BoundLogger
wrapper below.
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any


class _JSONFormatter(logging.Formatter):
    """Emit each record as a single-line JSON object."""

    _SEVERITY = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARNING",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "CRITICAL",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": self._SEVERITY.get(record.levelno, "DEFAULT"),
            "message": record.getMessage(),
            "logger": record.name,
        }
        extra = getattr(record, "_extra", {})
        payload.update(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class BoundLogger:
    """
    Thin wrapper around a standard Logger that accepts keyword arguments and
    attaches them as structured fields on each log record.

    Usage::

        logger = get_logger(__name__)
        logger.info("calculation_saved", calculation_id="abc-123", case_id="ZAD-2024-01-0001")
    """

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _log(self, level: int, event: str, **kwargs: Any) -> None:
        if self._logger.isEnabledFor(level):
            record = self._logger.makeRecord(
                self._logger.name,
                level,
                fn="",
                lno=0,
                msg=event,
                args=(),
                exc_info=None,
            )
            record._extra = kwargs  # type: ignore[attr-defined]
            self._logger.handle(record)

    def debug(self, event: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        self._log(logging.INFO, event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, event, **kwargs)

    def critical(self, event: str, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, event, **kwargs)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the root logger with the JSON formatter."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JSONFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> BoundLogger:
    return BoundLogger(logging.getLogger(name))
