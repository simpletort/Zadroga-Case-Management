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
from google.cloud import firestore
from firebase_admin import firestore as fs_admin
from firebase_functions import https_fn
from firebase_functions.options import CorsOptions
import os
ALLOWED_ORIGIN = os.environ.get(
    "ALLOWED_ORIGIN",
    "https://simpletort-zadroga-dev.web.app"
)


CORS_OPTIONS = CorsOptions(cors_origins=ALLOWED_ORIGIN, cors_methods=["get", "post", "put", "delete", "options","patch"])

logger = logging.getLogger(__name__)

# ── Deployment region ─────────────────────────────────────────────────────────
# Single source of truth — was copy-pasted in api/users.py, api/auth_api.py,
# and api/audit.py as `REGION = "us-central1"`.
REGION: str = "us-central1"

# ── CORS headers ──────────────────────────────────────────────────────────────
# Was defined in middleware/jwt_middleware.py and imported by every API file.
# Tighten Access-Control-Allow-Origin to your domain in production.
CORS_HEADERS: dict[str, str] = {
    "Access-Control-Allow-Origin":  ALLOWED_ORIGIN,
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Max-Age":       "3600",
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
    return firestore.client(project="simpletort-zadroga-dev", database_id="simpletort-dev")


# ── JSON response helpers ─────────────────────────────────────────────────────
# Previously defined in middleware/jwt_middleware.py and imported by every
# API file.  Now the canonical home is here; jwt_middleware re-exports them
# for backward compatibility.

def _json_response(data: dict, status: int = 200) -> https_fn.Response:
    return https_fn.Response(
        json.dumps(data),
        status=status,
        headers={**CORS_HEADERS, "Content-Type": "application/json"},
    )


def cors_preflight() -> https_fn.Response:
    """Return a 204 CORS preflight response."""
    return https_fn.Response("", 204, CORS_HEADERS)


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
        return cors_preflight()
    return None


# ── Firestore document serialization ─────────────────────────────────────────
def serialise_doc(
    doc_dict: dict,
    *,
    strip_phi: bool = False,
    extra_timestamp_fields: tuple[str, ...] = (),
) -> dict:
    """
    Prepare a Firestore document dict for JSON serialization.

    Previously duplicated as inline loops in:
      - api/users.py  list_users_fn  (created_at, updated_at, deleted_at)
      - api/users.py  get_user_fn    (created_at, updated_at)
      - api/audit.py  get_audit_log_fn (timestamp)

    Args:
        doc_dict:               Raw dict from doc.to_dict().
        strip_phi:              If True, remove all PHI_FIELDS keys.
        extra_timestamp_fields: Additional timestamp key names beyond TIMESTAMP_FIELDS.

    Returns:
        A new dict safe for json.dumps().
    """
    d = dict(doc_dict)  # shallow copy — don't mutate the caller's dict

    if strip_phi:
        for field in PHI_FIELDS:
            d.pop(field, None)

    all_ts_fields = TIMESTAMP_FIELDS + extra_timestamp_fields
    for key in all_ts_fields:
        if key in d and hasattr(d[key], "isoformat"):
            d[key] = d[key].isoformat()

    return d


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
