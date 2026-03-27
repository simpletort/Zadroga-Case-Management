"""
api/logging_config.py — Structured JSON logging via structlog.
"""
from __future__ import annotations
import logging
import sys
import structlog


def setup_logging() -> None:
    # Configure stdlib logging to route output to stdout.
    # Required because structlog.stdlib.LoggerFactory() wraps stdlib loggers,
    # which in turn need a handler — without this nothing would print.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,   # needs a stdlib logger → now satisfied
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),  # was: PrintLoggerFactory
    )


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)