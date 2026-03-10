"""
auth/triggers.py — Firebase Auth event triggers
=================================================
These run automatically when users are created or deleted in Firebase Auth.
No HTTP endpoint needed — Firebase invokes them directly.

Changes from original:
  Refactor — audit writes now use write_audit_event() from middleware/http.py.
             db() shortcut replaces fs_admin.client().
"""

from __future__ import annotations

import logging

from firebase_functions import auth_fn
from firebase_admin import firestore as fs_admin

from middleware.http import db, write_audit_event

logger = logging.getLogger(__name__)


@auth_fn.on_user_created()
def on_user_created(event: auth_fn.AuthBlockingEvent) -> None:
    """
    Fires when a new Firebase Auth user is created.
    Ensures a Firestore profile always exists even if the REST API call
    that created the user failed partway through.
    """
    user = event.data
    ref  = db().collection("users").document(user.uid)

    if not ref.get().exists:
        ref.set({
            "uid":            user.uid,
            "email":          user.email or "",
            "display_name":   user.display_name or "",
            "role":           "client",   # default — admin promotes via API
            "status":         "active",
            "email_verified": user.email_verified,
            "created_at":     fs_admin.SERVER_TIMESTAMP,
            "updated_at":     fs_admin.SERVER_TIMESTAMP,
        })
        logger.info("Created Firestore profile for uid=%s", user.uid)

    write_audit_event("user_created", uid=user.uid, email=user.email)


@auth_fn.on_user_deleted()
def on_user_deleted(event: auth_fn.AuthBlockingEvent) -> None:
    """
    Fires when a Firebase Auth user is deleted.
    Soft-deletes their Firestore profile to preserve the audit trail.
    """
    user = event.data
    db().collection("users").document(user.uid).update({
        "status":     "deleted",
        "deleted_at": fs_admin.SERVER_TIMESTAMP,
    })
    write_audit_event("user_deleted_from_auth", uid=user.uid)
    logger.info("Soft-deleted Firestore profile for uid=%s", user.uid)
