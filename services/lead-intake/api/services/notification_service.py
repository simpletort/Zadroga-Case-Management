"""
api/services/notification_service.py — SendGrid email + Twilio SMS welcome notifications.
"""
from __future__ import annotations
from config import get_settings
from logging_config import get_logger
 
logger = get_logger(__name__)
 
_tasks_client: Optional[tasks_v2.CloudTasksClient] = None
 
 
def _get_client() -> tasks_v2.CloudTasksClient:
    global _tasks_client
    if _tasks_client is None:
        _tasks_client = tasks_v2.CloudTasksClient()
        logger.info("cloud_tasks_client_initialised")
    return _tasks_client
 
 
def _queue_path(queue_name: str) -> str:
    settings = get_settings()
    client = _get_client()
    return client.queue_path(
        settings.gcp_project_id,
        settings.cloud_tasks_queue_region,
        queue_name,
    )
 
 
def _enqueue_http_task(
    queue_path: str,
    handler_url: str,
    payload: dict,
    audience: str,
    sa_email: str,
) -> str:
    """Create a Cloud Tasks HTTP task with OIDC auth. Returns task resource name."""
    client = _get_client()
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": handler_url,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload).encode("utf-8"),
            "oidc_token": {
                "service_account_email": sa_email,
                "audience": audience,
            },
        }
    }
    response = client.create_task(request={"parent": queue_path, "task": task})
    return response.name
 
 
async def send_welcome_notifications(
    email: str,
    phone: str,
    first_name: str,
    last_name: str,
    case_id: str,
) -> dict:
    """Send welcome email and SMS. Returns dict with success flags."""
    settings = get_settings()
    results = {"email": False, "sms": False}
 
    # Email via SendGrid
    if settings.sendgrid_api_key:
        try:
            import sendgrid
            from sendgrid.helpers.mail import Mail
            sg = sendgrid.SendGridAPIClient(api_key=settings.sendgrid_api_key)
            message = Mail(
                from_email=settings.sendgrid_from_email,
                to_emails=email,
                subject=f"Your ZAD Legal Case Has Been Opened — {case_id}",
                html_content=f"""
                <p>Dear {first_name},</p>
                <p>Your case <strong>{case_id}</strong> has been opened. Our team will review your
                VCF eligibility information and be in touch within 2 business days.</p>
                <p>Please log in to your portal to track your case status.</p>
                <p>— ZAD Legal Team</p>
                """,
            )
            sg.send(message)
            results["email"] = True
        except Exception as exc:
            logger.error("email_send_failed", case_id=case_id, error=str(exc))
    else:
        logger.info("email_skipped_no_key", case_id=case_id)
        results["email"] = True  # Dev mode: pretend success
 
    # SMS via Twilio
    if settings.twilio_account_sid and settings.twilio_auth_token:
        try:
            from twilio.rest import Client
            client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            client.messages.create(
                body=f"Hi {first_name}, your ZAD Legal case {case_id} is open. Log in to track your status.",
                from_=settings.twilio_from_number,
                to=phone,
            )
            results["sms"] = True
        except Exception as exc:
            logger.error("sms_send_failed", case_id=case_id, error=str(exc))
    else:
        logger.info("sms_skipped_no_key", case_id=case_id)
        results["sms"] = True  # Dev mode
 
    return results