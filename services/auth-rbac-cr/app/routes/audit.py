"""
app/routes/audit.py — Audit log read endpoint (auditLog.read permission required)
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from google.cloud.firestore_v1 import Query as FSQuery

from app.services.rbac_service import serialise_doc

router = APIRouter(tags=["audit"])


def _get_db():
    from app.utils.firestore import get_firestore_client
    return get_firestore_client()


@router.get("/api/v1/audit-log")
def get_audit_log(
    request: Request,
    uid: str = Query(default=None),
    limit: int = Query(default=50, le=200),
):
    query = _get_db().collection("auditLog").order_by(
        "timestamp", direction=FSQuery.DESCENDING
    )
    if uid:
        query = query.where("uid", "==", uid)
    query = query.limit(limit)

    logs = [serialise_doc(doc.to_dict()) for doc in query.stream()]
    return {"logs": logs}
