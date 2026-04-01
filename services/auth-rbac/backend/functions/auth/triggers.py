# """
# auth/triggers.py
# Auth triggers rewritten using identity_fn (blocking functions).
# Note: on_user_created / on_user_deleted background triggers do not exist
# in the Python Firebase Functions SDK. identity_fn.before_user_created()
# is the supported Python equivalent.
# """

# from __future__ import annotations
# import logging
# from firebase_functions import auth_fn
# from firebase_admin import firestore as fs_admin
# from middleware.http import db, write_audit_event

# logger = logging.getLogger(__name__)

# _ROLE_LABELS = {
#     "client":         "Client",
#     "admin_staff":    "Admin Staff",
#     "paralegal":      "Paralegal",
#     "junior_partner": "Junior Partner",
#     "senior_partner": "Senior Partner",
#     "system_admin":   "System Admin",
# }


# @auth_fn.on_user_deleted()
# def on_user_created(event: identity_fn.AuthBlockingEvent) -> identity_fn.BeforeCreateResponse | None:
#     user = event.data
#     ref = db().collection("staff").document(user.uid)
#     if not ref.get().exists:
#         ref.set({
#             "userId":            user.uid,
#             "email":             user.email or "",
#             "displayName":       user.display_name or "",
#             "role":              _ROLE_LABELS.get("client", "client"),
#             "isActive":          True,
#             "googleWorkspaceId": "",
#             "lastLoginAt":       None,
#             "createdAt":         fs_admin.SERVER_TIMESTAMP,
#         })
#     write_audit_event("user_created", uid=user.uid, email=user.email)
#     return None


# @identity_fn.before_user_deleted()
# def on_user_deleted(event: identity_fn.AuthBlockingEvent) -> None:
#     user = event.data
#     docs = db().collection("staff").where("userId", "==", user.uid).stream()
#     for doc in docs:
#         doc.reference.update({
#             "isActive":  False,
#             "deletedAt": fs_admin.SERVER_TIMESTAMP,
#         })
#     write_audit_event("user_deleted_from_auth", uid=user.uid)