"""
auth/triggers.py — Firebase Auth blocking triggers
Uses identity_fn (Python SDK equivalent of JS onCreate/onDelete).
"""
from __future__ import annotations
import logging
from firebase_functions import identity_fn
from firebase_admin import firestore as fs_admin
from middleware.http import db, write_audit_event

logger = logging.getLogger(__name__)

_ROLE_LABELS = {
    "admin_staff":    "Admin Staff",
    "paralegal":      "Paralegal",
    "junior_partner": "Junior Partner",
    "senior_partner": "Senior Partner",
    "system_admin":   "System Admin",
}


@identity_fn.before_user_created()
def on_user_created(event: identity_fn.AuthBlockingEvent) -> identity_fn.BeforeCreateResponse | None:
    user = event.data
    role = (user.custom_claims or {}).get("role", "admin_staff")
    ref = db().collection("staff").document(user.uid)
    if not ref.get().exists:
        ref.set({
            "userId":            user.uid,
            "email":             user.email or "",
            "displayName":       user.display_name or "",
            "role":              role,
            "roleLabel":         _ROLE_LABELS.get(role, role),
            "isActive":          True,
            "googleWorkspaceId": "",
            "lastLoginAt":       None,
            "createdAt":         fs_admin.SERVER_TIMESTAMP,
        })
    write_audit_event("user_created", uid=user.uid, email=user.email)
    return None


# Note: before_user_deleted is not available in Python SDK v0.5.0.
# Handle deletion cleanup in delete_user_fn() in api/users.py instead.
# Monitor firebase-functions-python releases for on_user_deleted support.
