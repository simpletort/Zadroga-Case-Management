"""
middleware/http.py — Shared HTTP, Firestore, and audit utilities
================================================================
Consolidates logic that was previously duplicated across:
  - middleware/jwt_middleware.py  (CORS_HEADERS, json_ok/err, REGION)
  - api/users.py                  (timestamp serialization, PHI stripping, audit write)
  - api/audit.py                  (timestamp serialization)
  - auth/rbac.py                  (audit write)
  - auth/triggers.py              (audit write)

Everything in this file is pure utility — no business logic.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from config import Config
from firebase_admin import firestore as fs_admin
from firebase_functions import https_fn
from firebase_functions.options import CorsOptions
import os

# Comma-separated list of allowed origins.
# Override via ALLOWED_ORIGINS env var on deployed functions.
# Default includes the production Firebase app and local Vite dev server.
ALLOWED_ORIGINS: list[str] = [
    o.strip()
    for o in os.environ.get(
        "ALLOWED_ORIGINS",
        "https://simpletort-zadroga-dev.web.app,http://localhost:5173",
    ).split(",")
    if o.strip()
]

CORS_OPTIONS = CorsOptions(
    cors_origins=ALLOWED_ORIGINS,
    cors_methods=["get", "post", "put", "delete", "options", "patch"],
)

logger = logging.getLogger(__name__)

# ── Deployment region ─────────────────────────────────────────────────────────
# Single source of truth — was copy-pasted in api/users.py, api/auth_api.py,
# and api/audit.py as `REGION = "us-central1"`.
REGION: str = "us-central1"

# ── CORS headers ──────────────────────────────────────────────────────────────
# Base headers (no origin — set dynamically per-request by cors_preflight).
# CORS_HEADERS retains ALLOWED_ORIGINS[0] for any code that imports it directly.
CORS_HEADERS_BASE: dict[str, str] = {
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Max-Age":       "3600",
}
# Backward-compatible alias (used by _json_response and external importers).
CORS_HEADERS: dict[str, str] = {
    **CORS_HEADERS_BASE,
    "Access-Control-Allow-Origin": ALLOWED_ORIGINS[0],
}

# ── PHI field names ────────────────────────────────────────────────────────────
# Previously duplicated as inline lists in api/users.py (list_users_fn used
# ["phi_data","ssn","dob"] and get_user_fn used ["phi_data","ssn","dob","medical_info"]).
# Canonical set used everywhere.
PHI_FIELDS: frozenset[str] = frozenset({"phi_data", "ssn", "dob", "medical_info"})

# ── Timestamp fields on user documents ───────────────────────────────────────
# Used by serialise_doc() below; avoids magic string repetition.
TIMESTAMP_FIELDS: tuple[str, ...] = ("created_at", "updated_at", "deleted_at", "timestamp", "createdAt", "lastLoginAt", "deletedAt")


# ── Firestore shortcut ────────────────────────────────────────────────────────
def db() -> Any:
    """
    Return the default Firestore client.

    Was called as `fs_admin.client()` in 18 separate places across 6 files.
    Using this wrapper makes mocking in tests trivial (patch one symbol).
    """
    return fs_admin.client(database_id=Config.DATABASE_ID)


# ── JSON response helpers ─────────────────────────────────────────────────────
# Previously defined in middleware/jwt_middleware.py and imported by every
# API file.  Now the canonical home is here; jwt_middleware re-exports them
# for backward compatibility.

def _json_response(data: dict, status: int = 200) -> https_fn.Response:
    # Reflect the request's Origin if it's in the allow-list, otherwise fall
    # back to the primary origin.  Flask's request context is always present
    # inside a firebase-functions handler (the SDK runs on Flask internally).
    try:
        from flask import request as _flask_req
        origin = _flask_req.headers.get("Origin", "")
    except RuntimeError:
        origin = ""
    allowed = origin if origin in ALLOWED_ORIGINS else ALLOWED_ORIGINS[0]
    return https_fn.Response(
        json.dumps(data),
        status=status,
        headers={**CORS_HEADERS_BASE, "Access-Control-Allow-Origin": allowed, "Content-Type": "application/json"},
    )


def cors_preflight(req: https_fn.Request | None = None) -> https_fn.Response:
    """Return a 204 CORS preflight response, reflecting the request's origin if allowed."""
    origin = req.headers.get("Origin", "") if req else ""
    allowed = origin if origin in ALLOWED_ORIGINS else ALLOWED_ORIGINS[0]
    return https_fn.Response("", 204, {**CORS_HEADERS_BASE, "Access-Control-Allow-Origin": allowed})


def json_ok(data: dict, status: int = 200) -> https_fn.Response:
    """Return a 200-class JSON success response."""
    return _json_response(data, status)


def json_err(message: str, status: int = 400) -> https_fn.Response:
    """Return an error JSON response with the given HTTP status."""
    return _json_response({"error": message}, status)


def handle_options(req: https_fn.Request) -> https_fn.Response | None:
    """
    If the request is an OPTIONS preflight, return the CORS response immediately.
    Otherwise return None so the caller continues.

    Usage (replaces 11 identical if-blocks across api/ files):
        early = handle_options(req)
        if early: return early
    """
    if req.method == "OPTIONS":
        return cors_preflight(req)
    return None


# ── Firestore document serialization ─────────────────────────────────────────
def _serialise_value(v: Any) -> Any:
    """
    Recursively make a Firestore value JSON-safe.

    - Any object with .isoformat() (DatetimeWithNanoseconds, datetime, date)
      is converted to an ISO-8601 string.
    - Nested dicts and lists are walked recursively.
    - All other values are returned unchanged.
    """
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _serialise_value(vv) for k, vv in v.items()}
    if isinstance(v, list):
        return [_serialise_value(item) for item in v]
    return v


def serialise_doc(
    doc_dict: dict,
    *,
    strip_phi: bool = False,
    extra_timestamp_fields: tuple[str, ...] = (),
) -> dict:
    """
    Prepare a Firestore document dict for JSON serialization.

    Converts ALL Firestore timestamp values (DatetimeWithNanoseconds, datetime)
    anywhere in the document tree to ISO-8601 strings — including nested dicts
    and lists, and regardless of field name. This replaces the previous
    field-name whitelist (TIMESTAMP_FIELDS) which silently missed any field
    not on the list (e.g. `updatedAt`, custom audit fields).

    Args:
        doc_dict:               Raw dict from doc.to_dict().
        strip_phi:              If True, remove all PHI_FIELDS keys before
                                serialising.
        extra_timestamp_fields: Kept for backward compatibility — ignored,
                                since all timestamps are now converted by
                                value inspection rather than field name.

    Returns:
        A new dict safe for json.dumps().
    """
    d = dict(doc_dict)  # shallow copy — don't mutate the caller's dict

    if strip_phi:
        for field in PHI_FIELDS:
            d.pop(field, None)

    return {k: _serialise_value(v) for k, v in d.items()}


# ── Audit log writer ─────────────────────────────────────────────────────────
def write_audit_event(event_type: str, **fields: Any) -> None:
    """
    Append an immutable entry to the audit_log Firestore collection.

    Previously duplicated as inline db.collection("audit_log").add({...}) calls in:
      - auth/rbac.py       _audit_denied()    — permission_denied events
      - auth/rbac.py       log_role_change()  — role_change events
      - auth/triggers.py   on_user_created()  — user_created events
      - auth/triggers.py   on_user_deleted()  — user_deleted_from_auth events
      - api/users.py       delete_user_fn()   — user_soft_deleted events

    Usage:
        write_audit_event("user_soft_deleted", target_uid=uid, performed_by=caller_uid)

    All entries automatically include a server-side timestamp.
    """
    try:
        payload = {
            "event_type": event_type,
            "timestamp":  fs_admin.SERVER_TIMESTAMP,
            **fields,
        }
        db().collection("auditLog").add(payload)
    except Exception as exc:
        # Audit failures must never block the primary operation.
        logger.error("Failed to write audit event '%s': %s", event_type, exc)
