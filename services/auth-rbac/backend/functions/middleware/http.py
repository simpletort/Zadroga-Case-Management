"""
middleware/http.py — Shared HTTP, Firestore, and audit utilities
"""

from __future__ import annotations

import json
import logging
from typing import Any

from firebase_admin import firestore as fs_admin
from firebase_functions import https_fn

logger = logging.getLogger(__name__)

REGION: str = "us-central1"

CORS_HEADERS: dict[str, str] = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Max-Age":       "3600",
}

PHI_FIELDS: frozenset[str] = frozenset({"phi_data", "ssn", "dob", "medical_info"})
TIMESTAMP_FIELDS: tuple[str, ...] = (
    "created_at", "updated_at", "deleted_at", "timestamp",
    "createdAt", "updatedAt", "deletedAt", "lastLoginAt",
)

# ── Named Firestore database ──────────────────────────────────────────────────
_DB_NAME = "simpletort-dev"


def db() -> Any:
    """Return the simpletort-dev Firestore client."""
    return fs_admin.client(database=_DB_NAME)


# ── JSON response helpers ─────────────────────────────────────────────────────
def _json_response(data: dict, status: int = 200) -> https_fn.Response:
    return https_fn.Response(
        json.dumps(data),
        status=status,
        headers={**CORS_HEADERS, "Content-Type": "application/json"},
    )


def cors_preflight() -> https_fn.Response:
    return https_fn.Response("", 204, CORS_HEADERS)


def json_ok(data: dict, status: int = 200) -> https_fn.Response:
    return _json_response(data, status)


def json_err(message: str, status: int = 400) -> https_fn.Response:
    return _json_response({"error": message}, status)


def handle_options(req: https_fn.Request) -> https_fn.Response | None:
    if req.method == "OPTIONS":
        return cors_preflight()
    return None


# ── Firestore document serialization ─────────────────────────────────────────
def serialise_doc(
    doc_dict: dict,
    *,
    strip_phi: bool = False,
    extra_timestamp_fields: tuple[str, ...] = (),
) -> dict:
    d = dict(doc_dict)
    if strip_phi:
        for field in PHI_FIELDS:
            d.pop(field, None)
    for key in TIMESTAMP_FIELDS + extra_timestamp_fields:
        if key in d and hasattr(d[key], "isoformat"):
            d[key] = d[key].isoformat()
        elif key in d and d[key] is None:
            d[key] = None
    return d


# ── Audit log writer ─────────────────────────────────────────────────────────
def write_audit_event(event_type: str, **fields: Any) -> None:
    try:
        payload = {
            "event_type": event_type,
            "timestamp":  fs_admin.SERVER_TIMESTAMP,
            **fields,
        }
        db().collection("audit_log").add(payload)
    except Exception as exc:
        logger.error("Failed to write audit event '%s': %s", event_type, exc)
