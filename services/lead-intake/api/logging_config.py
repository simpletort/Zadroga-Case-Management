"""
api/logging_config.py — Structured JSON logging via structlog.

PHI POLICY: Never log firstName, lastName, email, phone, address, DOB, SSN,
or any medical data. The redact_phi processor below enforces this for
structured log events. Raw request body logging (middleware-level) must
also exclude these fields — see shared/middlewares/logging.py.
"""
from __future__ import annotations
import logging
import sys
import structlog


# ── PHI-safe log exclusion list ──────────────────────────────────────────────
# Any structlog event key matching this set is replaced with ***REDACTED***.
# Add new PHI/PII field names here as the schema grows.

PHI_SAFE_LOG_EXCLUDE_FIELDS: frozenset[str] = frozenset({
    "ssn",
    "ssn_encrypted",
    "ssn_hash",
    "dateOfBirth",
    "firstName",
    "lastName",
    "email",
    "phone",
    "address",
    "medicalInfo",
    "conditions",
})


def redact_phi_processor(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Structlog processor that redacts PHI fields before they reach any renderer."""
    for field in PHI_SAFE_LOG_EXCLUDE_FIELDS:
        if field in event_dict:
            event_dict[field] = "***REDACTED***"
    return event_dict


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
            redact_phi_processor,                # ← MUST be before JSONRenderer
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),  # was: PrintLoggerFactory
    )


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)