"""
api/services/notification_service.py — Welcome notification dispatch.

Enqueues Cloud Tasks for SMS and email rather than calling Twilio/SendGrid
directly in the request path. This keeps POST /leads fast and delegates
retries, opt-out checking, and delivery logging to the notification service.

If NOTIFICATION_SERVICE_URL is not set (local dev), falls back to direct
SendGrid/Twilio calls so the flow is testable without a second service.

Environment variables
---------------------
NOTIFICATION_SERVICE_URL   Base URL of the notification Cloud Run service.
                            When set, tasks are enqueued instead of direct calls.
CLOUD_TASKS_SMS_QUEUE      Cloud Tasks queue name for SMS  (default: sms-dispatch)
CLOUD_TASKS_EMAIL_QUEUE    Cloud Tasks queue name for email (default: email-dispatch)
CLOUD_TASKS_SA_EMAIL       OIDC service account for Cloud Tasks
GCP_PROJECT_ID             GCP project ID
CLOUD_TASKS_LOCATION       GCP region of the queues       (default: us-central1)
SENDGRID_API_KEY           Direct fallback — used only when NOTIFICATION_SERVICE_URL unset
SENDGRID_FROM_EMAIL        Sender address for direct fallback
TWILIO_ACCOUNT_SID         Direct fallback
TWILIO_AUTH_TOKEN          Direct fallback
TWILIO_FROM_NUMBER         Direct fallback
"""
from __future__ import annotations

import asyncio
import json
import uuid

from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)


async def send_welcome_notifications(
    email: str,
    phone: str,
    first_name: str,
    case_id: str,
) -> dict[str, bool]:
    """
    Dispatch welcome SMS + email for a newly created case.

    Returns {"email": bool, "sms": bool} — True means dispatched successfully
    (either enqueued to Cloud Tasks or sent directly). Failures are logged but
    never raised so the 201 lead-created response is not blocked.
    """
    settings = get_settings()
    results: dict[str, bool] = {"email": False, "sms": False}

    if settings.notification_service_url:
        # Production path: enqueue to Cloud Tasks → notification service handles
        # retries, opt-outs, delivery logging, 160-char enforcement.
        results["sms"] = await _enqueue_task(
            queue_name=settings.cloud_tasks_sms_queue,
            handler_path="/tasks/sms",
            payload={
                "to": phone,
                "templateId": "welcome_sms",
                "variables": {"first_name": first_name, "case_id": case_id},
                "caseId": case_id,
                "requestId": str(uuid.uuid4()),
            },
            case_id=case_id,
            channel="sms",
        )
        results["email"] = await _enqueue_task(
            queue_name=settings.cloud_tasks_email_queue,
            handler_path="/tasks/email",
            payload={
                "to": email,
                "templateId": "welcome_email",
                "variables": {"first_name": first_name, "case_id": case_id},
                "caseId": case_id,
                "requestId": str(uuid.uuid4()),
            },
            case_id=case_id,
            channel="email",
        )
    else:
        # Dev/test fallback: call SendGrid + Twilio directly.
        results["email"] = await _send_email_direct(email, first_name, case_id)
        results["sms"] = await _send_sms_direct(phone, first_name, case_id)

    return results


# ── Cloud Tasks enqueue ───────────────────────────────────────────────────────

async def _enqueue_task(
    queue_name: str,
    handler_path: str,
    payload: dict,
    case_id: str,
    channel: str,
) -> bool:
    from google.cloud import tasks_v2

    settings = get_settings()
    handler_url = f"{settings.notification_service_url}{handler_path}"
    sa_email = (
        settings.cloud_tasks_sa_email
        or f"lead-intake-sa@{settings.gcp_project_id}.iam.gserviceaccount.com"
    )

    def _create():
        client = tasks_v2.CloudTasksClient()
        parent = client.queue_path(
            settings.gcp_project_id,
            settings.cloud_tasks_location,
            queue_name,
        )
        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": handler_url,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(payload).encode(),
                "oidc_token": {
                    "service_account_email": sa_email,
                    "audience": handler_url,
                },
            }
        }
        return client.create_task(request={"parent": parent, "task": task})

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, _create)
        logger.info(f"welcome_{channel}_task_enqueued", case_id=case_id, task_name=response.name)
        return True
    except Exception as exc:
        logger.error(f"welcome_{channel}_enqueue_failed", case_id=case_id, error=str(exc))
        return False


# ── Direct fallback (dev/test only) ──────────────────────────────────────────

async def _send_email_direct(email: str, first_name: str, case_id: str) -> bool:
    settings = get_settings()
    if not settings.sendgrid_api_key:
        if settings.is_production:
            logger.error("email_skipped_missing_key_in_production", case_id=case_id)
            return False
        logger.info("email_skipped_no_key_dev_mode", case_id=case_id)
        return True  # dev: pretend success

    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail

        sg = sendgrid.SendGridAPIClient(api_key=settings.sendgrid_api_key)
        message = Mail(
            from_email=settings.sendgrid_from_email,
            to_emails=email,
            subject=f"Your ZAD Legal Case Has Been Opened — {case_id}",
            html_content=(
                f"<p>Dear {first_name},</p>"
                f"<p>Your case <strong>{case_id}</strong> has been opened. Our team will review "
                f"your VCF eligibility information and be in touch within 2 business days.</p>"
                f"<p>Please log in to your portal to track your case status.</p>"
                f"<p>— ZAD Legal Team</p>"
            ),
        )
        sg.send(message)
        return True
    except Exception as exc:
        logger.error("email_send_failed", case_id=case_id, error=str(exc))
        return False


async def _send_sms_direct(phone: str, first_name: str, case_id: str) -> bool:
    settings = get_settings()
    if not (settings.twilio_account_sid and settings.twilio_auth_token):
        if settings.is_production:
            logger.error("sms_skipped_missing_key_in_production", case_id=case_id)
            return False
        logger.info("sms_skipped_no_key_dev_mode", case_id=case_id)
        return True

    try:
        from twilio.rest import Client

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.messages.create(
            body=f"Hi {first_name}, your ZAD Legal case {case_id} is open. Log in to track your status.",
            from_=settings.twilio_from_number,
            to=phone,
        )
        return True
    except Exception as exc:
        logger.error("sms_send_failed", case_id=case_id, error=str(exc))
        return False
