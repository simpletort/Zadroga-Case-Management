"""
Audit Logging — HIPAA-compliant file access audit trail.

Every file access event is written to two destinations:

  1. Cloud Logging  (log: simpletort-file-access-audit)
     — Immutable, GCP-managed, tamper-resistant.
     — Export via Log Sink to a locked GCS bucket for 7-year retention.

  2. Firestore  collection: audit_logs/{auto-id}
     — Queryable by userId, caseId, action, and date range.
     — Documents are only ever created (.add()), never updated or deleted.
     — Firestore Security Rules enforce create-only access on this collection.

Failure policy:
  Audit failures are logged as ERRORs but never propagate to the caller.
  The Cloud Logging write is the authoritative, tamper-resistant record;
  Firestore provides the queryable index.

HIPAA requirements satisfied:
  ✓ All file operations logged (upload, download, view, metadata update, hold)
  ✓ Required fields: userId, action, documentId, caseId, timestamp, ipAddress
  ✓ Queryable by user, case, and date (Firestore composite indexes)
  ✓ Cloud Audit Logs integration via named Cloud Logging stream
  ✓ 7-year retention via Log Sink → locked GCS bucket (see audit-retention-setup.md)
  ✓ Immutable: Cloud Logging entries cannot be modified; Firestore write-only
"""

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from fastapi import Request

from app.config import get_settings
from app.utils.cloud_logging_client import get_cloud_logger
from app.utils.firestore import get_firestore_client

logger = logging.getLogger(__name__)
settings = get_settings()


class AuditAction(str, Enum):
    # ── Upload flow ──────────────────────────────────────────────────────────
    upload_register = "upload_register"    # POST /upload/register

    # ── Download / read ──────────────────────────────────────────────────────
    signed_url_read = "signed_url_read"    # GET /signed-url?action=read  → download
    signed_url_write = "signed_url_write"  # GET /signed-url?action=write → direct upload

    # ── Metadata access ───────────────────────────────────────────────────────
    view_metadata = "view_metadata"        # GET /{fileId}/metadata
    list_documents = "list_documents"      # GET /cases/{caseId}/documents
    update_metadata = "update_metadata"    # PATCH /cases/{caseId}/documents/{fileId}

    # ── Case hold (lifecycle protection) ─────────────────────────────────────
    hold_set = "hold_set"                  # PUT /cases/{caseId}/hold  hold=true
    hold_release = "hold_release"          # PUT /cases/{caseId}/hold  hold=false


def get_client_ip(request: Request) -> str:
    """
    Extract the originating client IP address.

    Cloud Run sits behind Google's load balancer which sets
    X-Forwarded-For: <client>, <proxy1>, <proxy2>.
    The first address is always the original client IP.
    """
    xff = request.headers.get("x-forwarded-for", "").strip()
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def log_audit_event(
    *,
    action: AuditAction,
    user: dict,
    request: Request,
    document_id: Optional[str] = None,
    case_id: Optional[str] = None,
    resource: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """
    Write a HIPAA audit event to Cloud Logging and Firestore.

    Args:
        action:      The file access action performed.
        user:        Verified Firebase token dict (uid, email, role).
        request:     FastAPI Request — source of IP address and user-agent.
        document_id: fileId of the document accessed (if applicable).
        case_id:     Case ID scoping the document (if applicable).
        resource:    Human-readable resource identifier (e.g. GCS blob path).
        metadata:    Extra context dict (category, content_type, etc.).
    """
    now = datetime.now(tz=timezone.utc)
    user_id = user.get("email") or user.get("uid", "unknown")
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent", "unknown")

    event: dict = {
        "userId": user_id,
        "action": action.value,
        "documentId": document_id,
        "caseId": case_id,
        "timestamp": now.isoformat(),
        "ipAddress": client_ip,
        "userAgent": user_agent,
        "resource": resource,
        "metadata": metadata or {},
        "service": settings.service_name,
    }

    # ── 1. Cloud Logging (authoritative, immutable) ───────────────────────────
    try:
        cloud_logger = get_cloud_logger()
        cloud_logger.log_struct(
            event,
            severity="NOTICE",
            labels={
                "action": action.value,
                "case_id": case_id or "",
                "user_id": user_id,
            },
        )
    except Exception as exc:
        logger.error(
            "AUDIT_CLOUD_LOG_FAILURE action=%s user=%s error=%s",
            action.value, user_id, exc,
        )

    # ── 2. Firestore (queryable index) ────────────────────────────────────────
    # .add() always creates a new document with an auto-generated ID.
    # This collection is strictly append-only — no .set(), .update(),
    # or .delete() calls are ever made against audit_logs.
    firestore_event = {**event, "timestamp": now}
    try:
        db = get_firestore_client()
        db.collection("audit_logs").add(firestore_event)
    except Exception as exc:
        logger.error(
            "AUDIT_FIRESTORE_FAILURE action=%s user=%s error=%s",
            action.value, user_id, exc,
        )
