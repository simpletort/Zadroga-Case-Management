"""
services/sendgrid_client.py — SendGrid Email API wrapper.

Responsibilities
----------------
* Build and return the SendGrid API client singleton (lazy-init).
* Call the SendGrid Mail Send API with pre-rendered subject and HTML body.
* Never raise on SendGrid API errors — return error details in EmailResult so
  the caller (email_service) can write the failure to the delivery record and
  decide whether to retry.

PHI / data-minimisation note
-----------------------------
No PHI is stored in SendGrid.  The email address (``to``) is used only in the
API call's recipient field and is never included in any SendGrid template,
custom arg, or tracking metadata.  Only ``caseId`` is passed as a custom arg
so delivery events can be correlated back to the Firestore case without
exposing any client PII to SendGrid's servers.
"""
from __future__ import annotations

from typing import Optional

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    CustomArg,
    From,
    HtmlContent,
    Mail,
    Subject,
    To,
)

from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)

_client: Optional[SendGridAPIClient] = None


def _get_client() -> SendGridAPIClient:
    """Return the process-level SendGrid client (lazy init)."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = SendGridAPIClient(api_key=settings.sendgrid_api_key)
        logger.info("sendgrid_client_initialised")
    return _client


class EmailResult:
    """Value object returned by :func:`send_email_via_sendgrid`."""

    __slots__ = (
        "success",
        "message_id",
        "status_code",
        "error_message",
    )

    def __init__(
        self,
        *,
        success: bool,
        message_id: Optional[str] = None,
        status_code: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        self.success = success
        self.message_id = message_id
        self.status_code = status_code
        self.error_message = error_message

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "messageId": self.message_id,
            "statusCode": self.status_code,
            "errorMessage": self.error_message,
        }


def send_email_via_sendgrid(
    to: str,
    subject: str,
    html_body: str,
    *,
    case_id: Optional[str] = None,
    from_name: Optional[str] = None,
) -> EmailResult:
    """
    Send a pre-rendered HTML email via the SendGrid Mail Send API.

    Parameters
    ----------
    to:
        Recipient email address.  Used only as the API recipient field;
        never stored in SendGrid templates or metadata.
    subject:
        Rendered email subject line.
    html_body:
        Rendered HTML email body.
    case_id:
        Optional case ID passed as a SendGrid custom arg for delivery-event
        correlation.  This is the only reference to the case stored at
        SendGrid — no PII is included.
    from_name:
        Optional sender display name.  When provided it overrides the
        ``SENDGRID_FROM_NAME`` setting.  Pass the value loaded from
        ``firmSettings/notifications.fromName`` so multi-tenant deployments
        can display their own firm name without a redeploy.

    Returns
    -------
    EmailResult
        Always returns; never raises.  Check ``.success`` to determine outcome.
    """
    settings = get_settings()
    client = _get_client()

    effective_from_name = from_name or settings.sendgrid_from_name
    message = Mail(
        from_email=From(settings.sendgrid_from_email, effective_from_name),
        to_emails=To(to),
        subject=Subject(subject),
        html_content=HtmlContent(html_body),
    )

    # Attach caseId as a custom arg for SendGrid event webhook correlation.
    # No other PII or PHI is passed to SendGrid.
    if case_id:
        message.custom_arg = CustomArg("caseId", case_id)

    try:
        response = client.send(message)
        message_id = response.headers.get("X-Message-Id")
        logger.info(
            "sendgrid_email_sent",
            status_code=response.status_code,
            message_id=message_id,
            case_id=case_id,
            to_masked="[REDACTED]",
        )
        return EmailResult(
            success=True,
            message_id=message_id,
            status_code=response.status_code,
        )

    except Exception as exc:
        # SendGrid SDK raises on non-2xx responses; catch everything so the
        # caller can write the failure record without re-raising.
        error_message = str(exc)
        status_code: Optional[int] = None
        if hasattr(exc, "status_code"):
            status_code = exc.status_code
        elif hasattr(exc, "body"):
            # sendgrid.exceptions.UnauthorizedError etc.
            error_message = str(exc.body or exc)

        logger.error(
            "sendgrid_api_error",
            error=error_message,
            status_code=status_code,
            case_id=case_id,
            to_masked="[REDACTED]",
        )
        return EmailResult(
            success=False,
            status_code=status_code,
            error_message=error_message,
        )
