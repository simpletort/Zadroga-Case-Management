"""
auth/triggers.py — Firebase Auth blocking triggers
Uses identity_fn (requires Identity Platform / GCIP).
"""
from __future__ import annotations
import logging
from firebase_functions import identity_fn
from firebase_admin import firestore as fs_admin, auth as firebase_auth
from middleware.http import db, write_audit_event
from auth.rbac import get_role_display_name
from config import Config
logger = logging.getLogger(__name__)


@identity_fn.before_user_created()
def on_user_created(event: identity_fn.AuthBlockingEvent) -> identity_fn.BeforeCreateResponse | None:
    user = event.data
    role = (user.custom_claims or {}).get("role", "client")

    ref = db().collection("staff").document(user.uid)
    if not ref.get().exists:
        ref.set({
            "userId":            user.uid,
            "email":             user.email or "",
            "displayName":       user.display_name or "",
            "role":              role,
            "roleLabel":         get_role_display_name(role),
            "isActive":          True,
            "googleWorkspaceId": "",
            "lastLoginAt":       None,
            "createdAt":         fs_admin.SERVER_TIMESTAMP,
        })

    write_audit_event("user_created", uid=user.uid, email=user.email)

    return identity_fn.BeforeCreateResponse(
        custom_claims={"role": role}
    )


# Note: before_user_deleted is not available in the Python SDK.
# Deletion cleanup is handled in delete_user_fn() in api/users.py instead.