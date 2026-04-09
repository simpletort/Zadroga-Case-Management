"""
app.py — FastAPI application for the Notification Service.

Endpoints
---------
POST /tasks/sms
    Cloud Tasks HTTP handler.  Receives the task payload, validates the
    OIDC token injected by Cloud Tasks, and calls sms_service.send_sms().
    Must return 2xx for Cloud Tasks to consider the task done; returns 4xx
    for payload errors (no retry) and 5xx for transient failures (will retry).

POST /internal/reminders/schedule
    Schedule 48-hour and 7-day document reminder tasks for a case.
    Called by case-reminder-trigger Cloud Function (Firestore event-driven).

DELETE /internal/reminders/{case_id}
    Cancel pending document reminder tasks when a client uploads all documents.

POST /webhooks/twilio/status
    Twilio status callback.  Updates the delivery record with the final
    message status (delivered, failed, undelivered) from Twilio.

POST /webhooks/twilio/inbound
    Twilio inbound message webhook.  Handles STOP/START/HELP keywords to
    manage opt-out status.

GET  /health
    Cloud Run / load-balancer health probe (no auth).

Authentication
--------------
* /tasks/sms     — OIDC token from Cloud Tasks (verified via Google public certs)
* /webhooks/*    — Twilio request signature (X-Twilio-Signature header)
* /health        — none

OIDC verification uses google-auth rather than a full JWT library to stay
aligned with GCP's recommended pattern for authenticating Cloud Tasks callers.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from contextlib import asynccontextmanager
from typing import Optional

import google.auth.transport.requests
import google.oauth2.id_token
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from config import get_settings
from logging_config import get_logger, setup_logging
from services.firestore_client import get_db
from services.opt_out_service import clear_opt_out, record_opt_out
from services.email_service import EmailDispatchResult, send_email
from services.template_service import render_template, TemplateNotFoundError, TemplateDisabledError, MissingVariableError
from services.sms_service import SmsDispatchResult, send_sms
from services.tasks_service import cancel_document_reminders, enqueue_document_reminders, enqueue_email

logger = get_logger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    logger.info(
        "notification_service_starting",
        env=settings.app_env,
        project=settings.gcp_project_id,
    )
    # Eagerly init Firestore client so first-request latency is lower
    get_db()
    yield
    logger.info("notification_service_shutdown")


app = FastAPI(
    title="ZAD Notification Service",
    version="1.0.0",
    description="Twilio SMS dispatch, opt-out management, and delivery tracking",
    openapi_url="/openapi.json",
    docs_url="/docs",
    lifespan=lifespan,
)


# ── Request models ────────────────────────────────────────────────────────────

class SmsTaskPayload(BaseModel):
    """Payload sent by Cloud Tasks (and by lead-intake when enqueueing)."""
    to: str = Field(..., description="E.164 destination phone number")
    templateId: str = Field(..., description="Firestore SMS template document ID")
    variables: dict = Field(default_factory=dict)
    caseId: Optional[str] = Field(None)
    requestId: Optional[str] = Field(None)


class EmailTaskPayload(BaseModel):
    """Payload sent by Cloud Tasks for email dispatch."""
    to: str = Field(..., description="Recipient email address")
    templateId: str = Field(..., description="Firestore email template document ID")
    variables: dict = Field(default_factory=dict)
    caseId: Optional[str] = Field(None)
    requestId: Optional[str] = Field(None)


class ScheduleRemindersPayload(BaseModel):
    """
    Payload for POST /internal/reminders/schedule.
    Sent by intake-form-dispatcher when a case advances to "Pending Client Info".
    """
    caseId: str = Field(..., description="Firestore case ID, e.g. ZAD-2024-01-0001")
    phone: str = Field(..., description="E.164 client phone number")
    clientName: str = Field(..., description="Client full name for template substitution")
    missingDocsList: str = Field(
        ...,
        description=(
            "Newline-separated list of outstanding documents, "
            "e.g. '• Medical records\\n• Authorization form'"
        ),
    )
    portalUrl: str = Field(..., description="Client portal upload URL")
    deadlineLabel: str = Field(
        ...,
        description="Human-readable 48-hour deadline, e.g. 'April 5, 2026 at 5:00 PM'",
    )
    requestId: Optional[str] = Field(None)


# ── OIDC verification helper ──────────────────────────────────────────────────

_google_request = google.auth.transport.requests.Request()


def _verify_oidc_token(request: Request) -> None:
    """
    Verify the OIDC Bearer token injected by Cloud Tasks.

    Raises HTTP 401 if the token is missing or invalid.
    Skipped in non-production environments to ease local testing.
    """
    settings = get_settings()
    if not settings.is_production:
        return  # Skip in dev/staging — allow unauthenticated task calls

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing OIDC Bearer token",
        )
    token = auth_header[len("Bearer "):]

    try:
        google.oauth2.id_token.verify_firebase_token(
            token,
            _google_request,
            audience=settings.notification_service_url,
        )
    except Exception as exc:
        logger.warning("oidc_verification_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid OIDC token",
        )


# ── Twilio signature verification ─────────────────────────────────────────────

def _verify_twilio_signature(request: Request, body: bytes) -> None:
    """
    Validate the X-Twilio-Signature header to ensure the webhook came from
    Twilio and not an arbitrary caller.

    Uses HMAC-SHA1 as specified in the Twilio security docs.
    Skipped in non-production environments.
    """
    settings = get_settings()
    if not settings.is_production:
        return

    twilio_sig = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)
    auth_token = settings.twilio_auth_token.encode("utf-8")

    # Compute expected signature: HMAC-SHA1(auth_token, url + sorted POST params)
    # For JSON webhooks the body is included directly after the URL.
    mac = hmac.new(auth_token, (url + body.decode("utf-8")).encode("utf-8"), hashlib.sha1)
    import base64
    expected = base64.b64encode(mac.digest()).decode("utf-8")

    if not hmac.compare_digest(expected, twilio_sig):
        logger.warning("twilio_signature_invalid", url=url)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Twilio signature",
        )


# ── Task handler ──────────────────────────────────────────────────────────────

@app.post("/tasks/sms", status_code=status.HTTP_200_OK)
async def handle_sms_task(request: Request, payload: SmsTaskPayload):
    """
    Cloud Tasks HTTP handler — dispatch a single SMS.

    Cloud Tasks will retry on any non-2xx response, so:
    * 400 Bad Request  → payload error; no retry (Cloud Tasks respects this).
    * 500 Internal     → transient error; Cloud Tasks will retry with backoff.
    * 200 OK           → task complete (even if SMS failed — we record it).
    """
    _verify_oidc_token(request)

    logger.info(
        "sms_task_received",
        template_id=payload.templateId,
        case_id=payload.caseId,
        request_id=payload.requestId,
        to_masked="[REDACTED]",
    )

    db = get_db()

    result: SmsDispatchResult = await send_sms(
        to=payload.to,
        template_id=payload.templateId,
        variables=payload.variables,
        db=db,
        case_id=payload.caseId,
        request_id=payload.requestId,
    )

    # Return 200 whether or not Twilio succeeded — we've recorded the outcome.
    # A 5xx here would cause Cloud Tasks to retry, potentially double-sending.
    return {
        "deliveryId": result.delivery_id,
        "status": result.status,
        "success": result.success,
        "messageSid": result.message_sid,
        "segmentCount": result.segment_count,
    }


# ── Email task handler ────────────────────────────────────────────────────────

@app.post("/tasks/email", status_code=status.HTTP_200_OK)
async def handle_email_task(request: Request, payload: EmailTaskPayload):
    """
    Cloud Tasks HTTP handler — dispatch a single email.

    Returns 200 whether or not SendGrid succeeded — the outcome is recorded
    in the delivery record.  A 5xx would cause Cloud Tasks to retry and
    potentially double-send.
    """
    _verify_oidc_token(request)

    logger.info(
        "email_task_received",
        template_id=payload.templateId,
        case_id=payload.caseId,
        request_id=payload.requestId,
        to_masked="[REDACTED]",
    )

    db = get_db()

    result: EmailDispatchResult = await send_email(
        to=payload.to,
        template_id=payload.templateId,
        variables=payload.variables,
        db=db,
        case_id=payload.caseId,
        request_id=payload.requestId,
    )

    return {
        "deliveryId": result.delivery_id,
        "status": result.status,
        "success": result.success,
        "messageId": result.message_id,
    }


# ── Direct email dispatch (internal / testing) ────────────────────────────────

class EmailSendPayload(BaseModel):
    """Payload for POST /internal/email/send — direct dispatch without Cloud Tasks."""
    to: str = Field(..., description="Recipient email address")
    templateId: str = Field(..., description="Firestore email template document ID")
    variables: dict = Field(default_factory=dict)
    caseId: Optional[str] = Field(None)
    requestId: Optional[str] = Field(None)


class EmailEnqueuePayload(BaseModel):
    """Payload for POST /internal/email/enqueue — async via Cloud Tasks."""
    to: str = Field(..., description="Recipient email address")
    templateId: str = Field(..., description="Firestore email template document ID")
    variables: dict = Field(default_factory=dict)
    caseId: Optional[str] = Field(None)
    requestId: Optional[str] = Field(None)
    delaySeconds: int = Field(0, description="Schedule delay in seconds (0 = immediate)")


class EmailPreviewPayload(BaseModel):
    """Payload for POST /internal/email/preview — renders template, no sending."""
    templateId: str = Field(..., description="Firestore email template document ID")
    variables: dict = Field(default_factory=dict)
    caseId: Optional[str] = Field(None)


@app.post("/internal/email/preview", status_code=status.HTTP_200_OK)
async def preview_email(request: Request, payload: EmailPreviewPayload):
    """
    Render an email template and return the full output — no email is sent.

    Use this to verify:
    * Template exists in Firestore
    * Variables are substituted correctly
    * Subject and HTML body look right

    Returns the rendered subject, plain-text body, and HTML body.
    """
    _verify_oidc_token(request)

    logger.info(
        "email_preview_requested",
        template_id=payload.templateId,
        case_id=payload.caseId,
    )

    try:
        rendered = await render_template(payload.templateId, payload.variables, get_db())
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except TemplateDisabledError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except MissingVariableError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    settings = get_settings()
    return {
        "templateId": payload.templateId,
        "from": f"{settings.sendgrid_from_name} <{settings.sendgrid_from_email}>",
        "subject": rendered.subject,
        "htmlBody": rendered.html_body,
        "smsSafe": rendered.sms_safe,
        "charCount": len(rendered.sms_safe),
    }


@app.post("/internal/email/send", status_code=status.HTTP_200_OK)
async def send_email_direct(request: Request, payload: EmailSendPayload):
    """
    Send an email directly (synchronous — waits for SendGrid response).

    Use this endpoint for:
    * Testing / verification without Cloud Tasks
    * Internal services that need immediate confirmation

    For production high-volume dispatch use ``POST /internal/email/enqueue``
    which queues via Cloud Tasks and returns instantly.

    Authentication: OIDC Bearer token (skipped in dev).
    """
    _verify_oidc_token(request)

    logger.info(
        "email_send_direct_requested",
        template_id=payload.templateId,
        case_id=payload.caseId,
        request_id=payload.requestId,
        to_masked="[REDACTED]",
    )

    result: EmailDispatchResult = await send_email(
        to=payload.to,
        template_id=payload.templateId,
        variables=payload.variables,
        db=get_db(),
        case_id=payload.caseId,
        request_id=payload.requestId,
    )

    return {
        "deliveryId": result.delivery_id,
        "status": result.status,
        "success": result.success,
        "messageId": result.message_id,
        "statusCode": result.status_code,
        "errorMessage": result.error_message,
    }


@app.post("/internal/email/enqueue", status_code=status.HTTP_200_OK)
async def enqueue_email_task(request: Request, payload: EmailEnqueuePayload):
    """
    Enqueue an email via Cloud Tasks (async — returns immediately).

    Cloud Tasks will call ``POST /tasks/email`` with the payload.
    Retries automatically on failure (up to queue max-attempts).

    Authentication: OIDC Bearer token (skipped in dev).
    """
    _verify_oidc_token(request)

    logger.info(
        "email_enqueue_requested",
        template_id=payload.templateId,
        case_id=payload.caseId,
        request_id=payload.requestId,
        delay_seconds=payload.delaySeconds,
        to_masked="[REDACTED]",
    )

    try:
        task_name = enqueue_email(
            to=payload.to,
            template_id=payload.templateId,
            variables=payload.variables,
            case_id=payload.caseId,
            request_id=payload.requestId,
            delay_seconds=payload.delaySeconds,
        )
    except Exception as exc:
        logger.error(
            "email_enqueue_failed",
            template_id=payload.templateId,
            case_id=payload.caseId,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enqueue email: {exc}",
        )

    return {
        "queued": True,
        "taskName": task_name,
        "caseId": payload.caseId,
        "templateId": payload.templateId,
    }


# ── Twilio status callback ────────────────────────────────────────────────────

@app.post("/webhooks/twilio/status", status_code=status.HTTP_204_NO_CONTENT)
async def twilio_status_callback(request: Request):
    """
    Receive Twilio message status updates (queued → sent → delivered / failed).

    Updates the corresponding delivery record's ``twilioStatus`` field.
    Returns 204 No Content (Twilio ignores the response body).
    """
    body = await request.body()
    _verify_twilio_signature(request, body)

    form = await request.form()
    message_sid = form.get("MessageSid")
    message_status = form.get("MessageStatus")
    error_code = form.get("ErrorCode")

    logger.info(
        "twilio_status_callback",
        sid=message_sid,
        twilio_status=message_status,
        error_code=error_code,
    )

    if message_sid and message_status:
        from google.cloud import firestore as _fs
        db = get_db()
        settings = get_settings()
        # Find delivery record by Twilio SID (requires a composite index on
        # twilioMessageSid in the delivery_records collection)
        query = (
            db.collection(settings.delivery_records_collection)
            .where("twilioMessageSid", "==", message_sid)
            .limit(1)
        )
        async for doc in query.stream():
            await doc.reference.update({
                "twilioStatus": message_status,
                "errorCode": int(error_code) if error_code else None,
                "updatedAt": _fs.SERVER_TIMESTAMP,
            })
            logger.info(
                "delivery_record_status_updated",
                delivery_id=doc.id,
                twilio_status=message_status,
            )
            break

    return PlainTextResponse("", status_code=204)


# ── Twilio inbound message (STOP / START / HELP) ──────────────────────────────

@app.post("/webhooks/twilio/inbound", status_code=status.HTTP_200_OK)
async def twilio_inbound(request: Request):
    """
    Handle inbound SMS messages from Twilio for opt-out management.

    STOP / UNSUBSCRIBE → record opt-out
    START / UNSTOP     → clear opt-out
    HELP               → no-op (Twilio handles HELP automatically)

    Returns TwiML (empty <Response>) so Twilio doesn't send an auto-reply.
    """
    body = await request.body()
    _verify_twilio_signature(request, body)

    form = await request.form()
    from_number: str = form.get("From", "")
    message_body: str = form.get("Body", "").strip().upper()

    logger.info(
        "twilio_inbound_received",
        keyword=message_body,
        from_masked="[REDACTED]",
    )

    db = get_db()

    if message_body in {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}:
        await record_opt_out(from_number, reason=message_body, db=db)
    elif message_body in {"START", "UNSTOP", "YES"}:
        await clear_opt_out(from_number, db=db)

    # Return minimal TwiML — no reply message (Twilio handles STOP/START itself)
    return PlainTextResponse(
        '<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="text/xml",
    )


# ── Document reminder scheduling ──────────────────────────────────────────────

@app.post("/internal/reminders/schedule", status_code=status.HTTP_200_OK)
async def schedule_document_reminders(
    request: Request,
    payload: ScheduleRemindersPayload,
):
    """
    Schedule 48-hour and 7-day document reminder SMS tasks for a case.

    Called by the ``case-reminder-trigger`` Cloud Function (Firestore event-driven)
    when a case advances to the "Pending Client Info" status.  Creates two named
    Cloud Tasks:

    * ``doc-reminder-{caseId}-48hr``  — fires 48 hours from now
    * ``doc-reminder-{caseId}-7day``  — fires 7 days from now

    Both tasks are idempotent — re-scheduling an already-pending case is safe
    (the existing task is preserved and its name is returned).

    Authentication: OIDC Bearer token (Cloud Tasks or internal callers).
    """
    _verify_oidc_token(request)

    logger.info(
        "reminder_schedule_requested",
        case_id=payload.caseId,
        request_id=payload.requestId,
        to_masked="[REDACTED]",
    )

    try:
        result = await enqueue_document_reminders(
            case_id=payload.caseId,
            phone=payload.phone,
            client_name=payload.clientName,
            missing_docs_list=payload.missingDocsList,
            portal_url=payload.portalUrl,
            deadline_label=payload.deadlineLabel,
            request_id=payload.requestId,
            db=get_db(),
        )
    except Exception as exc:
        logger.error(
            "reminder_schedule_failed",
            case_id=payload.caseId,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to schedule reminders: {exc}",
        )

    logger.info(
        "reminders_scheduled",
        case_id=payload.caseId,
        task_48hr=result.get("task_48hr"),
        task_7day=result.get("task_7day"),
    )

    return {
        "caseId": payload.caseId,
        "scheduled": True,
        "task48hr": result.get("task_48hr"),
        "task7day": result.get("task_7day"),
    }


@app.delete("/internal/reminders/{case_id}", status_code=status.HTTP_200_OK)
async def cancel_document_reminder_tasks(case_id: str, request: Request):
    """
    Cancel pending 48-hour and 7-day document reminder tasks for a case.

    Should be called when the client uploads all required documents so they
    do not receive reminders after compliance.  Safe to call even if one or
    both tasks have already fired — missing tasks are silently ignored.

    Authentication: OIDC Bearer token.
    """
    _verify_oidc_token(request)

    logger.info("reminder_cancel_requested", case_id=case_id)

    result = await cancel_document_reminders(case_id=case_id, db=get_db())

    logger.info(
        "reminders_cancel_complete",
        case_id=case_id,
        cancelled_48hr=result["cancelled_48hr"],
        cancelled_7day=result["cancelled_7day"],
    )

    return {
        "caseId": case_id,
        "cancelled48hr": result["cancelled_48hr"],
        "cancelled7day": result["cancelled_7day"],
    }


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "healthy", "service": "notification", "version": "1.0.0"}


@app.get("/", include_in_schema=False)
async def root():
    return {"service": "ZAD Notification Service", "version": "1.0.0"}


# ── Local dev entrypoint ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True, log_level="debug")
