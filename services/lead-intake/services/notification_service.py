"""
services/notification_service.py — Welcome notification dispatcher.

Called by routers/leads.py after a new case is created.  Enqueues Cloud Tasks
for each notification channel so the lead-intake HTTP response is not blocked
by downstream API calls.

send_welcome_notifications() dispatches:
  - SMS    : enqueued to the sms-dispatch Cloud Tasks queue (Twilio handler)
  - Email  : enqueued to the email-dispatch Cloud Tasks queue (SendGrid handler)

Both enqueue to the Notification Service Cloud Run instance which handles the
actual Twilio/SendGrid API calls, 160-char enforcement, opt-out checking, and
delivery record writing.

Return value
------------
    {"email": True/False, "sms": True/False}

True means the task was successfully enqueued (not that the notification was
delivered).  Failures are logged but do not raise so the 201 lead-created
response is not blocked.

Environment variables (set via Cloud Run / Secret Manager)
-----------------------------------------------------------
    NOTIFICATION_SERVICE_URL     — base URL of the notification Cloud Run service
    CLOUD_TASKS_SMS_QUEUE        — Cloud Tasks queue name for SMS (default: sms-dispatch)
    CLOUD_TASKS_EMAIL_QUEUE      — Cloud Tasks queue name for email (default: email-dispatch)
    CLOUD_TASKS_QUEUE_REGION     — GCP region of the Cloud Tasks queues (default: us-east1)
    CLOUD_TASKS_SA_EMAIL         — OIDC service account for Cloud Tasks
    GCP_PROJECT_ID               — GCP project ID
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Optional

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import tasks_v2

import logging

logger = logging.getLogger(__name__)

_tasks_client: Optional[tasks_v2.CloudTasksClient] = None

# ── Environment-based configuration ──────────────────────────────────────────

def _cfg(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _get_client() -> tasks_v2.CloudTasksClient:
    global _tasks_client
    if _tasks_client is None:
        _tasks_client = tasks_v2.CloudTasksClient()
    return _tasks_client


def _queue_path(queue_name: str) -> str:
    client = _get_client()
    return client.queue_path(
        _cfg("GCP_PROJECT_ID", "simpletort-prod"),
        _cfg("CLOUD_TASKS_QUEUE_REGION", "us-east1"),
        queue_name,
    )


def _enqueue_http_task(queue_path: str, handler_url: str, payload: dict) -> str:
    """
    Create a Cloud Tasks HTTP task with OIDC authentication.
    Returns the task resource name.  Raises GoogleAPICallError on failure.
    """
    sa_email = _cfg(
        "CLOUD_TASKS_SA_EMAIL",
        f"lead-intake-sa@{_cfg('GCP_PROJECT_ID', 'simpletort-prod')}.iam.gserviceaccount.com",
    )
    notification_url = _cfg("NOTIFICATION_SERVICE_URL", "")

    client = _get_client()
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": handler_url,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload).encode("utf-8"),
            "oidc_token": {
                "service_account_email": sa_email,
                "audience": notification_url,
            },
        }
    }
    response = client.create_task(request={"parent": queue_path, "task": task})
    return response.name


async def send_welcome_notifications(
    email: str,
    phone: str,
    first_name: str,
    case_id: str,
) -> dict[str, bool]:
    """
    Enqueue welcome notifications (SMS + email) for a newly created case.

    Parameters
    ----------
    email:
        Claimant email address (lowercase normalised).
    phone:
        Claimant E.164 phone number.
    first_name:
        Claimant first name for personalisation.
    case_id:
        New case ID (e.g. ZAD-2025-03-0001).

    Returns
    -------
    dict
        ``{"email": bool, "sms": bool}`` — True means task enqueued successfully.
    """
    request_id = str(uuid.uuid4())
    results: dict[str, bool] = {"email": False, "sms": False}
    notification_url = _cfg("NOTIFICATION_SERVICE_URL", "")

    if not notification_url:
        logger.warning(
            "notification_service_url_not_configured; skipping welcome notifications",
            extra={"case_id": case_id},
        )
        return results

    # ── SMS ───────────────────────────────────────────────────────────────
    try:
        sms_queue = _queue_path(_cfg("CLOUD_TASKS_SMS_QUEUE", "sms-dispatch"))
        sms_payload = {
            "to": phone,
            "templateId": "welcome_sms",
            "variables": {"first_name": first_name, "case_id": case_id},
            "caseId": case_id,
            "requestId": request_id,
        }
        task_name = _enqueue_http_task(
            queue_path=sms_queue,
            handler_url=f"{notification_url}/tasks/sms",
            payload=sms_payload,
        )
        logger.info(
            "welcome_sms_task_enqueued",
            extra={"case_id": case_id, "task_name": task_name},
        )
        results["sms"] = True

    except GoogleAPICallError as exc:
        logger.error(
            "welcome_sms_enqueue_failed",
            extra={"case_id": case_id, "error": str(exc)},
        )
    except Exception as exc:
        logger.error(
            "welcome_sms_unexpected_error",
            extra={"case_id": case_id, "error": str(exc)},
        )

    # ── Email ─────────────────────────────────────────────────────────────
    try:
        email_queue = _queue_path(_cfg("CLOUD_TASKS_EMAIL_QUEUE", "email-dispatch"))
        email_payload = {
            "to": email,
            "templateId": "welcome_email",
            "variables": {"first_name": first_name, "case_id": case_id},
            "caseId": case_id,
            "requestId": request_id,
        }
        task_name = _enqueue_http_task(
            queue_path=email_queue,
            handler_url=f"{notification_url}/tasks/email",
            payload=email_payload,
        )
        logger.info(
            "welcome_email_task_enqueued",
            extra={"case_id": case_id, "task_name": task_name},
        )
        results["email"] = True

    except GoogleAPICallError as exc:
        logger.error(
            "welcome_email_enqueue_failed",
            extra={"case_id": case_id, "error": str(exc)},
        )
    except Exception as exc:
        logger.error(
            "welcome_email_unexpected_error",
            extra={"case_id": case_id, "error": str(exc)},
        )

    return results
