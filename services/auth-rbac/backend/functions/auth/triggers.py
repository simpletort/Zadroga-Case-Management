"""
auth/triggers.py — Firebase Auth async triggers
Uses auth_fn.on_user_created (non-blocking, no GCIP required).
"""
from __future__ import annotations
import logging
from firebase_functions import auth_fn
from firebase_admin import firestore as fs_admin, auth as firebase_auth
from middleware.http import db, write_audit_event

logger = logging.getLogger(__name__)

_ROLE_LABELS = {
    "admin_staff":    "Admin Staff",
    "paralegal":      "Paralegal",
    "junior_partner": "Junior Partner",
    "senior_partner": "Senior Partner",
    "system_admin":   "System Admin",
}


@auth_fn.on_user_created()  # ← changed from before_user_created
def on_user_created(event: auth_fn.AuthEvent) -> None:  # ← AuthEvent not AuthBlockingEvent, return None
    user = event.data
    role = (user.custom_claims or {}).get("role", "admin_staff")

    # Set default claims since we can no longer do it in the blocking response
    firebase_auth.set_custom_user_claims(user.uid, {"role": role})

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


@auth_fn.on_user_deleted()
def on_user_deleted(event: auth_fn.AuthEvent) -> None:
    """
    Fires when a Firebase Auth user is deleted.
    Soft-deletes their Firestore profile to preserve the audit trail.
    """
    user = event.data
    # Soft-delete: find the staff doc by uid field, then mark deleted
    docs = db().collection("staff").where("userId", "==", user.uid).stream()
    for doc in docs:
        doc.reference.update({
            "isActive":   False,
            "deletedAt":  fs_admin.SERVER_TIMESTAMP,
        })
    write_audit_event("user_deleted_from_auth", uid=user.uid)
    logger.info("Soft-deleted Firestore profile for uid=%s", user.uid)