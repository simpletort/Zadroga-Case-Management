"""
services/email_service.py — Email dispatch orchestrator.

Public API
----------
    send_email(to, template_id, variables, db, *, case_id, request_id)
        → EmailDispatchResult

This is the single entry-point for all outbound email.  It coordinates:
    1. Template fetch  — pull subject + htmlBody from Firestore, raise if
                         missing/disabled
    2. Body render     — substitute variables into subject and HTML body
    3. SendGrid call   — delegate to sendgrid_client.send_email_via_sendgrid()
    4. Delivery record — write the attempt + outcome to Firestore

Delivery record document path
------------------------------
    /{email_delivery_records_collection}/{deliveryId}

Document schema
---------------
    deliveryId      : str           — UUID
    to              : str           — email address (PII — stored as-is for
                                       support lookup; never logged in plain)
    caseId          : str | null    — associated case (for case timeline)
    templateId      : str
    requestId       : str           — correlates with the originating request
    status          : "sent" | "failed" | "template_error"
    sendgridMessageId : str | null  — X-Message-Id from SendGrid response
    sendgridStatusCode : int | null — HTTP status code from SendGrid
    errorMessage    : str | null
    attemptedAt     : str (ISO-8601)
    sentAt          : str (ISO-8601) | null
    createdAt       : timestamp (SERVER_TIMESTAMP)

PHI note: ``to`` (email address) is PII.  It is stored in the delivery record
for support/audit purposes but is **never** included in log output.  All log
calls use ``to_masked="[REDACTED]"``.  Only ``caseId`` is forwarded to
SendGrid as a custom arg — no email address or client name is stored there.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from google.cloud import firestore
from google.cloud.firestore_v1.async_client import AsyncClient

from config import get_settings
from logging_config import get_logger
from services.sendgrid_client import EmailResult, send_email_via_sendgrid
from services.template_service import (
    MissingVariableError,
    RenderedTemplate,
    TemplateDisabledError,
    TemplateNotFoundError,
    render_template,
)
from services.delivery_tracking_service import (
    CHANNEL_EMAIL,
    write_notification_record,
)

logger = get_logger(__name__)


@dataclass
class EmailDispatchResult:
    """Return value of :func:`send_email`."""

    success: bool
    delivery_id: str
    status: str                         # "sent" | "failed" | "template_error"
    message_id: Optional[str] = None
    status_code: Optional[int] = None
    error_message: Optional[str] = None
    extra: dict = field(default_factory=dict)


async def _write_delivery_record(
    *,
    delivery_id: str,
    to: str,
    case_id: Optional[str],
    template_id: str,
    request_id: str,
    status: str,
    email_result: Optional[EmailResult],
    attempted_at: datetime,
    db: AsyncClient,
) -> None:
    """
    Write the email delivery record to Firestore.

    Fire-and-forget from the caller's perspective; failures are logged
    but do not affect the HTTP response.
    """
    settings = get_settings()
    sent_at = datetime.utcnow().isoformat() + "Z" if status == "sent" else None

    record: dict = {
        "deliveryId": delivery_id,
        "to": to,                           # PII: kept for audit
        "caseId": case_id,
        "templateId": template_id,
        "requestId": request_id,
        "status": status,
        "sendgridMessageId": email_result.message_id if email_result else None,
        "sendgridStatusCode": email_result.status_code if email_result else None,
        "errorMessage": email_result.error_message if email_result else None,
        "attemptedAt": attempted_at.isoformat() + "Z",
        "sentAt": sent_at,
        "createdAt": firestore.SERVER_TIMESTAMP,
    }

    doc_ref = (
        db.collection(settings.email_delivery_records_collection).document(delivery_id)
    )
    try:
        await doc_ref.set(record)
        logger.info(
            "email_delivery_record_written",
            delivery_id=delivery_id,
            status=status,
            case_id=case_id,
        )
    except Exception as exc:
        logger.error(
            "email_delivery_record_write_failed",
            delivery_id=delivery_id,
            error=str(exc),
        )


async def send_email(
    to: str,
    template_id: str,
    variables: dict,
    db: AsyncClient,
    *,
    case_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> EmailDispatchResult:
    """
    Dispatch an email message.

    Parameters
    ----------
    to:
        Recipient email address.
    template_id:
        Firestore template document ID (e.g. ``"welcome_email"``).
    variables:
        Template substitution dict (e.g. ``{"clientName": "Jane"}``)
    db:
        Async Firestore client.
    case_id:
        Optional associated case ID — written to the delivery record and
        passed to SendGrid as a custom arg (no other PII sent to SendGrid).
    request_id:
        Upstream trace/request ID — written to the delivery record.

    Returns
    -------
    EmailDispatchResult
        Always returns; never raises.
    """
    delivery_id = str(uuid.uuid4())
    attempted_at = datetime.utcnow()
    request_id = request_id or delivery_id

    logger.info(
        "email_dispatch_started",
        delivery_id=delivery_id,
        template_id=template_id,
        case_id=case_id,
        request_id=request_id,
        to_masked="[REDACTED]",
    )

    # ── Step 1: Fetch template and render subject + HTML body ─────────────
    rendered_subject: Optional[str] = None
    rendered_html: Optional[str] = None
    try:
        rendered: RenderedTemplate = await render_template(template_id, variables, db)
        rendered_subject = rendered.subject
        rendered_html = rendered.html_body
    except (TemplateNotFoundError, TemplateDisabledError, MissingVariableError) as exc:
        logger.error(
            "email_template_error",
            delivery_id=delivery_id,
            template_id=template_id,
            error=str(exc),
        )
        result = EmailDispatchResult(
            success=False,
            delivery_id=delivery_id,
            status="template_error",
            error_message=str(exc),
        )
        await _write_delivery_record(
            delivery_id=delivery_id,
            to=to,
            case_id=case_id,
            template_id=template_id,
            request_id=request_id,
            status="template_error",
            email_result=None,
            attempted_at=attempted_at,
            db=db,
        )
        return result
    except Exception as exc:
        logger.error(
            "email_template_render_error",
            delivery_id=delivery_id,
            template_id=template_id,
            error=str(exc),
        )
        result = EmailDispatchResult(
            success=False,
            delivery_id=delivery_id,
            status="failed",
            error_message=f"Template render error: {exc}",
        )
        await _write_delivery_record(
            delivery_id=delivery_id,
            to=to,
            case_id=case_id,
            template_id=template_id,
            request_id=request_id,
            status="failed",
            email_result=None,
            attempted_at=attempted_at,
            db=db,
        )
        return result

    # ── Step 2: Send via SendGrid ─────────────────────────────────────────
    # sendgrid_client never raises; always returns an EmailResult.
    email_result: EmailResult = send_email_via_sendgrid(
        to=to,
        subject=rendered_subject,
        html_body=rendered_html,
        case_id=case_id,
    )

    status = "sent" if email_result.success else "failed"

    logger.info(
        "email_dispatch_complete",
        delivery_id=delivery_id,
        status=status,
        template_id=template_id,
        case_id=case_id,
        status_code=email_result.status_code,
        message_id=email_result.message_id,
        error_message=email_result.error_message,
    )

    # ── Step 3: Write delivery record ─────────────────────────────────────
    try:
        await _write_delivery_record(
            delivery_id=delivery_id,
            to=to,
            case_id=case_id,
            template_id=template_id,
            request_id=request_id,
            status=status,
            email_result=email_result,
            attempted_at=attempted_at,
            db=db,
        )
    except Exception as exc:
        logger.error(
            "email_delivery_record_outer_write_failed",
            delivery_id=delivery_id,
            error=str(exc),
        )

    # ── Step 4: Write to unified notifications schema ─────────────────────
    # Writes to cases/{caseId}/notifications/{notificationId} + notifications/{id}
    if case_id:
        try:
            await write_notification_record(
                notification_id=delivery_id,
                case_id=case_id,
                client_id=variables.get("clientName", ""),
                channel=CHANNEL_EMAIL,
                template_id=template_id,
                status=status,
                request_id=request_id,
                sent_at=attempted_at.isoformat() + "Z",
                error_message=email_result.error_message if email_result else None,
                error_code=None,
                retry_count=0,
                provider_message_id=email_result.message_id if email_result else None,
                email_subject=variables.get("subject", ""),
                sendgrid_status_code=email_result.status_code if email_result else None,
                db=db,
            )
        except Exception as exc:
            logger.error(
                "notification_tracking_write_failed",
                delivery_id=delivery_id,
                error=str(exc),
            )

    return EmailDispatchResult(
        success=email_result.success,
        delivery_id=delivery_id,
        status=status,
        message_id=email_result.message_id,
        status_code=email_result.status_code,
        error_message=email_result.error_message,
    )
