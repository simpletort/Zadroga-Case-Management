"""
api/services/notification_service.py — SendGrid email + Twilio SMS welcome notifications.
"""
from __future__ import annotations
from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)


async def send_welcome_notifications(
    email: str,
    phone: str,
    first_name: str,
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
