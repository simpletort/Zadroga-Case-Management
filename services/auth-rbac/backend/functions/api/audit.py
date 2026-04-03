"""
api/audit.py — Audit log read endpoint (Senior Partner only)
=============================================================
Changes from original:
  Refactor — handle_options() replaces inline OPTIONS block.
             serialise_doc() replaces inline timestamp conversion loop.
             db() replaces fs_admin.client().
             REGION imported from middleware/http.py.
"""

from __future__ import annotations

from firebase_admin import firestore as fs_admin
from firebase_functions import https_fn

from auth.rbac import Permission, require_permission
from middleware.http import REGION, json_ok, json_err, handle_options, db, serialise_doc, CORS_OPTIONS
from middleware.jwt_middleware import require_auth


@https_fn.on_request(region=REGION, cors=CORS_OPTIONS)
def get_audit_log_fn(req: https_fn.Request) -> https_fn.Response:
    early = handle_options(req)
    if early:
        return early

    user, err = require_auth(req)
    if err:
        return err
    guard = require_permission(user, Permission.VIEW_AUDIT_LOG, req)
    if guard:
        return guard

    uid_filter = req.args.get("uid")
    limit      = min(int(req.args.get("limit", 50)), 200)

    query = db().collection("auditLog").order_by(
        "timestamp", direction=fs_admin.Query.DESCENDING
    )
    if uid_filter:
        query = query.where("uid", "==", uid_filter)
    query = query.limit(limit)

    logs = [serialise_doc(doc.to_dict()) for doc in query.stream()]
    return json_ok({"logs": logs})
