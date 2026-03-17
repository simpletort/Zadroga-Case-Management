"""
services/sms_service.py — SMS dispatch orchestrator.

Public API
----------
    send_sms(to, template_id, variables, db, *, case_id, request_id)
        → SmsDispatchResult

This is the single entry-point for all outbound SMS.  It coordinates:
    1. Opt-out check   — bail early if recipient has opted out
    2. Template fetch  — pull body from Firestore, raise if missing/disabled
    3. Body render     — substitute variables into the template
    4. Twilio call     — delegate to twilio_client.send_sms_via_twilio()
    5. Delivery record — write the attempt + outcome to Firestore

Delivery record document path
------------------------------
    /{delivery_records_collection}/{deliveryId}

Document schema
---------------
    deliveryId      : str           — UUID
    to              : str           — E.164 phone (PII — stored as-is for
                                       support lookup; never logged in plain)
    caseId          : str | null    — associated case (for case timeline)
    templateId      : str
    requestId       : str           — correlates with the originating request
    status          : "sent" | "failed" | "opted_out" | "template_error"
    twilioMessageSid: str | null
    twilioStatus    : str | null    — e.g. "queued", "sent", "delivered"
    errorCode       : int | null    — Twilio error code
    errorMessage    : str | null
    charCount       : int
    segmentCount    : int
    attemptedAt     : str (ISO-8601)
    sentAt          : str (ISO-8601) | null

PHI note: ``to`` (phone number) is PII.  It is stored in the delivery record
for support/audit purposes but is **never** included in log output.  All log
calls use ``to_masked="[REDACTED]"``.
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
from services.opt_out_service import is_opted_out
from services.template_service import (
    TemplateDisabledError,
    TemplateNotFoundError,
    fetch_and_render,
)
from services.twilio_client import SmsResult, send_sms_via_twilio

logger = get_logger(__name__)


@dataclass
class SmsDispatchResult:
    """Return value of :func:`send_sms`."""

    success: bool
    delivery_id: str
    status: str                         # "sent" | "failed" | "opted_out" | "template_error"
    message_sid: Optional[str] = None
    error_code: Optional[int] = None
    error_message: Optional[str] = None
    char_count: int = 0
    segment_count: int = 0
    extra: dict = field(default_factory=dict)


async def _write_delivery_record(
    *,
    delivery_id: str,
    to: str,
    case_id: Optional[str],
    template_id: str,
    request_id: str,
    rendered_body: Optional[str],
    status: str,
    twilio_result: Optional[SmsResult],
    attempted_at: datetime,
    db: AsyncClient,
) -> None:
    """
    Write (or overwrite) the SMS delivery record to Firestore.

    This is fire-and-forget from the caller's perspective; failures are logged
    but do not affect the HTTP response.
    """
    settings = get_settings()
    sent_at = datetime.utcnow().isoformat() + "Z" if status == "sent" else None

    record: dict = {
        "deliveryId": delivery_id,
        "to": to,                       # PII: kept for audit
        "caseId": case_id,
        "templateId": template_id,
        "requestId": request_id,
        "status": status,
        "twilioMessageSid": twilio_result.message_sid if twilio_result else None,
        "twilioStatus": twilio_result.status if twilio_result else None,
        "errorCode": twilio_result.error_code if twilio_result else None,
        "errorMessage": twilio_result.error_message if twilio_result else None,
        "charCount": twilio_result.char_count if twilio_result else 0,
        "segmentCount": twilio_result.segment_count if twilio_result else 0,
        "attemptedAt": attempted_at.isoformat() + "Z",
        "sentAt": sent_at,
        "createdAt": firestore.SERVER_TIMESTAMP,
    }

    doc_ref = (
        db.collection(settings.delivery_records_collection).document(delivery_id)
    )
    try:
        await doc_ref.set(record)
        logger.info(
            "delivery_record_written",
            delivery_id=delivery_id,
            status=status,
            case_id=case_id,
        )
    except Exception as exc:
        # Non-fatal: the SMS may already be delivered; don't surface this error.
        logger.error(
            "delivery_record_write_failed",
            delivery_id=delivery_id,
            error=str(exc),
        )


async def send_sms(
    to: str,
    template_id: str,
    variables: dict,
    db: AsyncClient,
    *,
    case_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> SmsDispatchResult:
    """
    Dispatch an SMS message.

    Parameters
    ----------
    to:
        Destination E.164 phone number (e.g. ``+12125551234``).
    template_id:
        Firestore template document ID (e.g. ``"welcome_sms"``).
    variables:
        Template substitution dict (e.g. ``{"first_name": "Jane"}``).
    db:
        Async Firestore client.
    case_id:
        Optional associated case ID — written to the delivery record.
    request_id:
        Upstream trace/request ID — written to the delivery record.

    Returns
    -------
    SmsDispatchResult
        Always returns; never raises.
    """
    delivery_id = str(uuid.uuid4())
    attempted_at = datetime.utcnow()
    request_id = request_id or delivery_id

    logger.info(
        "sms_dispatch_started",
        delivery_id=delivery_id,
        template_id=template_id,
        case_id=case_id,
        request_id=request_id,
        to_masked="[REDACTED]",
    )

    # ── Step 1: Opt-out check ─────────────────────────────────────────────
    try:
        opted_out = await is_opted_out(to, db)
    except Exception as exc:
        # Treat opt-out lookup failure as a hard stop to avoid sending to
        # someone who may have opted out.
        logger.error(
            "opt_out_check_failed",
            delivery_id=delivery_id,
            error=str(exc),
            to_masked="[REDACTED]",
        )
        result = SmsDispatchResult(
            success=False,
            delivery_id=delivery_id,
            status="failed",
            error_message=f"Opt-out check failed: {exc}",
        )
        await _write_delivery_record(
            delivery_id=delivery_id,
            to=to,
            case_id=case_id,
            template_id=template_id,
            request_id=request_id,
            rendered_body=None,
            status="failed",
            twilio_result=None,
            attempted_at=attempted_at,
            db=db,
        )
        return result

    if opted_out:
        logger.info(
            "sms_suppressed_opt_out",
            delivery_id=delivery_id,
            template_id=template_id,
            case_id=case_id,
            to_masked="[REDACTED]",
        )
        result = SmsDispatchResult(
            success=False,
            delivery_id=delivery_id,
            status="opted_out",
        )
        await _write_delivery_record(
            delivery_id=delivery_id,
            to=to,
            case_id=case_id,
            template_id=template_id,
            request_id=request_id,
            rendered_body=None,
            status="opted_out",
            twilio_result=None,
            attempted_at=attempted_at,
            db=db,
        )
        return result

    # ── Step 2: Fetch template and render body ────────────────────────────
    rendered_body: Optional[str] = None
    try:
        rendered_body = await fetch_and_render(template_id, variables, db)
    except (TemplateNotFoundError, TemplateDisabledError) as exc:
        logger.error(
            "sms_template_error",
            delivery_id=delivery_id,
            template_id=template_id,
            error=str(exc),
        )
        result = SmsDispatchResult(
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
            rendered_body=None,
            status="template_error",
            twilio_result=None,
            attempted_at=attempted_at,
            db=db,
        )
        return result
    except Exception as exc:
        logger.error(
            "sms_template_render_error",
            delivery_id=delivery_id,
            template_id=template_id,
            error=str(exc),
        )
        result = SmsDispatchResult(
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
            rendered_body=None,
            status="failed",
            twilio_result=None,
            attempted_at=attempted_at,
            db=db,
        )
        return result

    # ── Step 3: Send via Twilio ───────────────────────────────────────────
    # twilio_client never raises; always returns an SmsResult.
    twilio_result: SmsResult = send_sms_via_twilio(to=to, body=rendered_body)

    status = "sent" if twilio_result.success else "failed"

    logger.info(
        "sms_dispatch_complete",
        delivery_id=delivery_id,
        status=status,
        template_id=template_id,
        case_id=case_id,
        char_count=twilio_result.char_count,
        segment_count=twilio_result.segment_count,
        sid=twilio_result.message_sid,
        error_code=twilio_result.error_code,
    )

    # ── Step 4: Write delivery record ─────────────────────────────────────
    await _write_delivery_record(
        delivery_id=delivery_id,
        to=to,
        case_id=case_id,
        template_id=template_id,
        request_id=request_id,
        rendered_body=rendered_body,
        status=status,
        twilio_result=twilio_result,
        attempted_at=attempted_at,
        db=db,
    )

    return SmsDispatchResult(
        success=twilio_result.success,
        delivery_id=delivery_id,
        status=status,
        message_sid=twilio_result.message_sid,
        error_code=twilio_result.error_code,
        error_message=twilio_result.error_message,
        char_count=twilio_result.char_count,
        segment_count=twilio_result.segment_count,
    )
