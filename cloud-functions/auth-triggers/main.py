"""
auth-triggers/main.py — Firebase Auth blocking trigger.

Fires before a new user is created in Firebase Auth (Identity Platform).
Sets the `role` custom claim on the token and creates the staff Firestore
document so other services can do direct UID lookups.
"""
from __future__ import annotations
import logging
from firebase_functions import identity_fn
from firebase_admin import firestore as fs_admin, auth as firebase_auth
import firebase_admin

firebase_admin.initialize_app()

logger = logging.getLogger(__name__)

DATABASE_ID = "simpletort-dev"


def _db():
    return fs_admin.client(database_id=DATABASE_ID)


def _get_role_display_name(role_id: str) -> str:
    labels = {
        "admin_staff":    "Admin Staff",
        "paralegal":      "Paralegal",
        "junior_partner": "Junior Partner",
        "senior_partner": "Senior Partner",
        "system_admin":   "System Admin",
        "client":         "Client",
    }
    return labels.get(role_id, role_id)


@identity_fn.before_user_created()
def on_user_created(event: identity_fn.AuthBlockingEvent) -> identity_fn.BeforeCreateResponse | None:
    user = event.data
    role = (user.custom_claims or {}).get("role", "client")

    ref = _db().collection("staff").document(user.uid)
    if not ref.get().exists:
        ref.set({
            "userId":            user.uid,
            "email":             user.email or "",
            "displayName":       user.display_name or "",
            "role":              role,
            "roleLabel":         _get_role_display_name(role),
            "isActive":          True,
            "googleWorkspaceId": "",
            "lastLoginAt":       None,
            "createdAt":         fs_admin.SERVER_TIMESTAMP,
        })

    try:
        payload = {
            "event_type": "user_created",
            "timestamp":  fs_admin.SERVER_TIMESTAMP,
            "uid":        user.uid,
            "email":      user.email,
        }
        _db().collection("auditLog").add(payload)
    except Exception as exc:
        logger.error("Failed to write audit event: %s", exc)

    return identity_fn.BeforeCreateResponse(
        custom_claims={"role": role}
    )
