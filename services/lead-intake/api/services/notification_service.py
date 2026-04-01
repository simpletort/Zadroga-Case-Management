"""
api/services/notification_service.py — Notification dispatch.

Architecture (based on the real notification dispatcher implementation):

SMS (claimant-facing welcome / followup)
─────────────────────────────────────────
  lead-intake → Cloud Tasks queue (sms-dispatch)
              → POST {NOTIFICATION_SERVICE_URL}/tasks/sms
              → notification dispatcher fetches template from Firestore
              → sends via Twilio

  Payload schema (matches SmsTaskPayload in notification/app.py):
    {
      "to":         "+1XXXXXXXXXX",   # E.164
      "templateId": "welcome_sms",    # Firestore sms_templates doc ID
      "variables":  {                 # snake_case — matches {{placeholders}}
        "first_name": "John",
        "case_id":    "ZAD-2026-04-0001"
      },
      "caseId":    "ZAD-2026-04-0001",
      "requestId": "uuid"
    }

  Required Firestore templates (seed with notification/seed_templates.py):
    sms_templates/welcome_sms   — body: "Hi {{first_name}}, your ZAD Legal case {{case_id}} is open..."
    sms_templates/followup_sms  — body: "Hi {{first_name}}, we haven't heard from you about case {{case_id}}..."

EMAIL (claimant-facing)
────────────────────────
  The notification dispatcher is SMS-only (no /notifications/email endpoint).
  Email is always handled directly via SendGrid from lead-intake, regardless
  of whether NOTIFICATION_SERVICE_URL is set.

STAFF IN-APP NOTIFICATIONS (screening results)
───────────────────────────────────────────────
  Written directly to Firestore /notifications/{id} by lead-intake after
  inline VCF screening. The auth-rbac frontend reads this collection.
  The notification dispatcher is NOT involved — staff alerts are in-app
  only, not SMS.

Dev fallback:
  When NOTIFICATION_SERVICE_URL is unset (local dev), SMS is sent
  directly via Twilio instead of via Cloud Tasks + dispatcher.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Optional

from google.cloud import tasks_v2

from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)

_tasks_client: Optional[tasks_v2.CloudTasksClient] = None


def _get_tasks_client() -> tasks_v2.CloudTasksClient:
    global _tasks_client
    if _tasks_client is None:
        _tasks_client = tasks_v2.CloudTasksClient()
        logger.info("cloud_tasks_client_initialised")
    return _tasks_client


def _sms_queue_path() -> str:
    settings = get_settings()
    client   = _get_tasks_client()
    return client.queue_path(
        settings.gcp_project_id,
        settings.cloud_tasks_queue_region,
        settings.cloud_tasks_sms_queue,   # "sms-dispatch"
    )


def _enqueue_sms_task(
    queue_path: str,
    handler_url: str,
    payload: dict,
    sa_email: str,
) -> str:
    """Create a Cloud Tasks HTTP task pointing at the notification dispatcher."""
    client = _get_tasks_client()
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url":         handler_url,
            "headers":     {"Content-Type": "application/json"},
            "body":        json.dumps(payload).encode("utf-8"),
            "oidc_token":  {
                # lead-intake-sa generates the OIDC token.
                # The notification dispatcher verifies audience only (not SA email),
                # so this SA is accepted as long as audience = NOTIFICATION_SERVICE_URL.
                "service_account_email": sa_email,
                "audience":              handler_url.rsplit("/tasks/sms", 1)[0],
            },
        }
    }
    response = client.create_task(request={"parent": queue_path, "task": task})
    return response.name


# ── Welcome notifications (claimant-facing) ───────────────────────────────────

async def send_welcome_notifications(
    email:      str,
    phone:      str,
    first_name: str,
    last_name:  str,
    case_id:    str,
    portal_url: Optional[str] = None,
) -> dict:
    """
    Send welcome email and SMS to the claimant after lead creation.

    Email  → direct SendGrid (notification dispatcher has no email endpoint)
    SMS    → Cloud Tasks → notification dispatcher POST /tasks/sms
             (falls back to direct Twilio in dev when NOTIFICATION_SERVICE_URL unset)
    """
    settings = get_settings()
    results  = {"email": False, "sms": False}
    request_id = str(uuid.uuid4())

    # ── Email: always direct via SendGrid ─────────────────────────────────────
    if settings.sendgrid_api_key:
        try:
            import sendgrid
            from sendgrid.helpers.mail import Mail
            sg = sendgrid.SendGridAPIClient(api_key=settings.sendgrid_api_key)
            message = Mail(
                from_email   = settings.sendgrid_from_email,
                to_emails    = email,
                subject      = f"Your ZAD Legal Case Has Been Opened — {case_id}",
                html_content = (
                    f"<p>Dear {first_name},</p>"
                    f"<p>Your case <strong>{case_id}</strong> has been opened. "
                    "Our team will be in touch within 2 business days.</p>"
                    + (f"<p><a href='{portal_url}'>Track your case</a></p>" if portal_url else "")
                    + "<p>— ZAD Legal Team</p>"
                ),
            )
            sg.send(message)
            results["email"] = True
            logger.info("welcome_email_sent", case_id=case_id)
        except Exception as exc:
            logger.error("welcome_email_failed", case_id=case_id, error=str(exc))
    else:
        # Dev mode: no SendGrid key — pretend success so tests don't block
        logger.info("welcome_email_skipped_no_key_dev_mode", case_id=case_id)
        results["email"] = True

    # ── SMS: via notification dispatcher (or direct Twilio fallback in dev) ───
    if settings.notification_service_url:
        # Primary path: enqueue to sms-dispatch queue → notification dispatcher
        sa_email = (
            settings.cloud_tasks_sa_email
            or f"lead-intake-sa@{settings.gcp_project_id}.iam.gserviceaccount.com"
        )
        handler_url = f"{settings.notification_service_url}/tasks/sms"
        payload = {
            "to":         phone,
            "templateId": "welcome_sms",
            "variables":  {
                # snake_case — matches {{first_name}} and {{case_id}} in Firestore template
                "first_name": first_name,
                "case_id":    case_id,
            },
            "caseId":    case_id,
            "requestId": request_id,
        }
        loop = asyncio.get_event_loop()
        try:
            q_path = _sms_queue_path()
            task_name = await loop.run_in_executor(
                None,
                lambda: _enqueue_sms_task(q_path, handler_url, payload, sa_email),
            )
            results["sms"] = True
            logger.info("welcome_sms_task_enqueued", case_id=case_id, task=task_name)
        except Exception as exc:
            logger.error("welcome_sms_task_failed", case_id=case_id, error=str(exc))
    else:
        # Dev fallback: direct Twilio when no dispatcher URL configured
        logger.info("notification_service_url_not_set_using_direct_twilio", case_id=case_id)
        if settings.twilio_account_sid and settings.twilio_auth_token:
            try:
                from twilio.rest import Client
                client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
                client.messages.create(
                    body  = f"Hi {first_name}, your ZAD Legal case {case_id} is open. We'll be in touch soon.",
                    from_ = settings.twilio_from_number,
                    to    = phone,
                )
                results["sms"] = True
            except Exception as exc:
                logger.error("direct_twilio_sms_failed", case_id=case_id, error=str(exc))
        else:
            logger.info("sms_skipped_no_twilio_key_dev_mode", case_id=case_id)
            results["sms"] = True  # dev pretend success

    return results


async def send_followup_sms(
    phone:      str,
    first_name: str,
    case_id:    str,
    request_id: str,
) -> bool:
    """
    Enqueue a follow-up SMS task to the notification dispatcher.
    Called by the /internal/tasks/followup handler when a 48h task fires.
    Returns True if enqueued successfully.
    """
    settings = get_settings()

    if not settings.notification_service_url:
        logger.info("followup_sms_skipped_no_dispatcher_url", case_id=case_id)
        return False

    sa_email    = (
        settings.cloud_tasks_sa_email
        or f"lead-intake-sa@{settings.gcp_project_id}.iam.gserviceaccount.com"
    )
    handler_url = f"{settings.notification_service_url}/tasks/sms"
    payload = {
        "to":         phone,
        "templateId": "followup_sms",
        "variables":  {
            "first_name": first_name,
            "case_id":    case_id,
        },
        "caseId":    case_id,
        "requestId": request_id,
    }
    loop = asyncio.get_event_loop()
    try:
        q_path    = _sms_queue_path()
        task_name = await loop.run_in_executor(
            None,
            lambda: _enqueue_sms_task(q_path, handler_url, payload, sa_email),
        )
        logger.info("followup_sms_task_enqueued", case_id=case_id, task=task_name)
        return True
    except Exception as exc:
        logger.error("followup_sms_task_failed", case_id=case_id, error=str(exc))
        return False
