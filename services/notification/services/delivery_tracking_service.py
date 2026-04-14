"""
services/delivery_tracking_service.py — Unified notification delivery tracker.

Writes every notification dispatch event to TWO Firestore paths simultaneously:

    notifications/{notificationId}                        ← top-level (cross-case queries)
    cases/{caseId}/notifications/{notificationId}         ← subcollection (per-case timeline)

Schema
------
    notificationId    : str           — UUID (document ID in both collections)
    caseId            : str           — Firestore case ID
    clientId          : str           — client identifier from case leadData
    channel           : str           — "SMS" | "EMAIL"
    templateId        : str           — Firestore template document ID
    status            : str           — "sent" | "delivered" | "failed" | "bounced"
                                        | "opted_out" | "template_error"
    sentAt            : str (ISO-8601)— API call timestamp
    deliveredAt       : str | null    — set on provider webhook confirmation
    errorMessage      : str | null
    errorCode         : int | null    — provider error code
    retryCount        : int           — dispatch attempts (0 = first attempt)
    requestId         : str           — upstream trace ID
    providerMessageId : str | null    — Twilio MessageSid or SendGrid X-Message-Id
    createdAt         : SERVER_TIMESTAMP
    updatedAt         : SERVER_TIMESTAMP

SMS-only fields:
    smsSegmentCount   : int
    smsCharCount      : int
    twilioStatus      : str | null

Email-only fields:
    emailSubject      : str | null    — rendered subject (no PII in field name)
    sendgridStatusCode: int | null
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore as _fs
from google.cloud.firestore_v1.async_client import AsyncClient

from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)

NOTIFICATIONS_COLLECTION = "notifications"

# ── Status constants ───────────────────────────────────────────────────────────
STATUS_SENT           = "sent"
STATUS_DELIVERED      = "delivered"
STATUS_FAILED         = "failed"
STATUS_BOUNCED        = "bounced"
STATUS_OPTED_OUT      = "opted_out"
STATUS_TEMPLATE_ERROR = "template_error"

# ── Channel constants ──────────────────────────────────────────────────────────
CHANNEL_SMS   = "SMS"
CHANNEL_EMAIL = "EMAIL"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def write_notification_record(
    *,
    notification_id: str,
    case_id: str,
    client_id: str,
    channel: str,
    template_id: str,
    status: str,
    request_id: str,
    sent_at: Optional[str] = None,
    delivered_at: Optional[str] = None,
    error_message: Optional[str] = None,
    error_code: Optional[int] = None,
    retry_count: int = 0,
    provider_message_id: Optional[str] = None,
    # SMS-specific
    sms_segment_count: Optional[int] = None,
    sms_char_count: Optional[int] = None,
    twilio_status: Optional[str] = None,
    # Email-specific
    email_subject: Optional[str] = None,
    sendgrid_status_code: Optional[int] = None,
    db: Optional[AsyncClient] = None,
) -> None:
    """
    Write a notification delivery record to both Firestore paths.

    Writes are fire-and-forget — failures are logged but never re-raised
    so the caller's HTTP response is never blocked.
    """
    if db is None:
        logger.warning("write_notification_record_skipped", reason="no db client")
        return

    settings = get_settings()
    sent_at = sent_at or _now_iso()

    record: dict = {
        "notificationId":   notification_id,
        "caseId":           case_id,
        "clientId":         client_id,
        "channel":          channel,
        "templateId":       template_id,
        "status":           status,
        "sentAt":           sent_at,
        "deliveredAt":      delivered_at,
        "errorMessage":     error_message,
        "errorCode":        error_code,
        "retryCount":       retry_count,
        "requestId":        request_id,
        "providerMessageId": provider_message_id,
        "createdAt":        _fs.SERVER_TIMESTAMP,
        "updatedAt":        _fs.SERVER_TIMESTAMP,
    }

    # Channel-specific fields
    if channel == CHANNEL_SMS:
        record["smsSegmentCount"] = sms_segment_count
        record["smsCharCount"]    = sms_char_count
        record["twilioStatus"]    = twilio_status

    if channel == CHANNEL_EMAIL:
        record["emailSubject"]        = email_subject
        record["sendgridStatusCode"]  = sendgrid_status_code

    # Write to both paths simultaneously
    top_level_ref = db.collection(NOTIFICATIONS_COLLECTION).document(notification_id)
    subcol_ref    = (
        db.collection(settings.cases_collection)
        .document(case_id)
        .collection(NOTIFICATIONS_COLLECTION)
        .document(notification_id)
    )

    try:
        await top_level_ref.set(record)
        await subcol_ref.set(record)
        logger.info(
            "notification_record_written",
            notification_id=notification_id,
            case_id=case_id,
            channel=channel,
            status=status,
            template_id=template_id,
        )
    except Exception as exc:
        logger.error(
            "notification_record_write_failed",
            notification_id=notification_id,
            case_id=case_id,
            error=str(exc),
        )


async def update_notification_status(
    *,
    notification_id: str,
    case_id: str,
    status: str,
    delivered_at: Optional[str] = None,
    error_message: Optional[str] = None,
    error_code: Optional[int] = None,
    provider_status: Optional[str] = None,
    db: Optional[AsyncClient] = None,
) -> None:
    """
    Update status on an existing notification record (called from webhooks).

    Updates both the top-level collection and the case subcollection.
    """
    if db is None:
        return

    settings = get_settings()
    updates: dict = {
        "status":    status,
        "updatedAt": _fs.SERVER_TIMESTAMP,
    }
    if delivered_at:
        updates["deliveredAt"] = delivered_at
    if error_message:
        updates["errorMessage"] = error_message
    if error_code is not None:
        updates["errorCode"] = error_code
    if provider_status:
        updates["twilioStatus"] = provider_status

    top_level_ref = db.collection(NOTIFICATIONS_COLLECTION).document(notification_id)
    subcol_ref    = (
        db.collection(settings.cases_collection)
        .document(case_id)
        .collection(NOTIFICATIONS_COLLECTION)
        .document(notification_id)
    )

    try:
        await top_level_ref.update(updates)
        await subcol_ref.update(updates)
        logger.info(
            "notification_status_updated",
            notification_id=notification_id,
            case_id=case_id,
            status=status,
        )
    except Exception as exc:
        logger.error(
            "notification_status_update_failed",
            notification_id=notification_id,
            case_id=case_id,
            error=str(exc),
        )


async def get_notifications_for_case(
    case_id: str,
    *,
    channel: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    db: Optional[AsyncClient] = None,
) -> list[dict]:
    """
    Fetch notification history for a case from the subcollection.

    Uses the subcollection path for efficient per-case reads without
    requiring a composite index on the top-level collection.
    """
    if db is None:
        return []

    settings = get_settings()
    query = (
        db.collection(settings.cases_collection)
        .document(case_id)
        .collection(NOTIFICATIONS_COLLECTION)
        .order_by("createdAt", direction=_fs.Query.DESCENDING)
    )

    if channel:
        query = query.where("channel", "==", channel)
    if status:
        query = query.where("status", "==", status)

    query = query.limit(limit)

    try:
        docs = query.stream()
        results = []
        async for doc in docs:
            results.append(doc.to_dict())
        return results
    except Exception as exc:
        logger.error(
            "get_notifications_for_case_failed",
            case_id=case_id,
            error=str(exc),
        )
        return []
