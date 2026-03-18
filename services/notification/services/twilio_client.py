"""
services/twilio_client.py — Twilio Messages API wrapper.

Responsibilities
----------------
* Build and return the Twilio REST client singleton (lazy-init).
* Enforce the 160-character GSM-7 single-segment limit:
    - Messages ≤ 160 chars → sent as a single SMS segment.
    - Messages 161–1600 chars → sent as concatenated multi-part SMS; Twilio
      handles segmentation automatically.  We log a warning and record the
      estimated segment count so billing/ops can monitor usage.
    - Messages > 1600 chars → rejected before any API call is made.
* Call the Twilio Messages.create() API and return a structured result dict.
* Never raise on Twilio API errors — return error details in the result so the
  caller (sms_service) can write the failure to the delivery record and decide
  whether to retry.

Twilio segment maths (GSM-7 encoding assumed for ASCII/Latin content)
----------------------------------------------------------------------
  Single message  : ≤ 160 chars → 1 segment
  Concatenated    : each part ≤ 153 chars (7 chars overhead per UDH header)
  Estimated parts : ceil((len - 160) / 153) + 1   for len > 160
"""
from __future__ import annotations

import math
from typing import Optional

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)

# GSM-7 characters that count as 2 chars in the encoding
_GSM7_EXTENDED = set("^{}\\[~]|€")

_client: Optional[Client] = None

# Segment boundaries for GSM-7
_SINGLE_LIMIT = 160
_CONCAT_PART_LIMIT = 153  # per-segment limit when UDH header is present


def _get_client() -> Client:
    """Return the process-level Twilio REST client (lazy init)."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        logger.info("twilio_client_initialised")
    return _client


def _gsm7_length(text: str) -> int:
    """
    Return the effective GSM-7 character count for *text*.

    Extended GSM-7 characters (e.g. €, {, }, [, ], \\, ^, ~, |) occupy two
    code units in the encoding, so they count as 2 towards the segment limit.
    Pure ASCII text that avoids these characters has a 1:1 ratio.
    """
    return sum(2 if ch in _GSM7_EXTENDED else 1 for ch in text)


def _estimate_segments(char_count: int) -> int:
    """
    Return the estimated number of SMS segments for *char_count* GSM-7 chars.
    """
    if char_count <= _SINGLE_LIMIT:
        return 1
    return math.ceil(char_count / _CONCAT_PART_LIMIT)


class SmsResult:
    """Value object returned by :func:`send_sms_via_twilio`."""

    __slots__ = (
        "success",
        "message_sid",
        "status",
        "error_code",
        "error_message",
        "char_count",
        "segment_count",
    )

    def __init__(
        self,
        *,
        success: bool,
        message_sid: Optional[str] = None,
        status: Optional[str] = None,
        error_code: Optional[int] = None,
        error_message: Optional[str] = None,
        char_count: int = 0,
        segment_count: int = 0,
    ) -> None:
        self.success = success
        self.message_sid = message_sid
        self.status = status
        self.error_code = error_code
        self.error_message = error_message
        self.char_count = char_count
        self.segment_count = segment_count

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "messageSid": self.message_sid,
            "status": self.status,
            "errorCode": self.error_code,
            "errorMessage": self.error_message,
            "charCount": self.char_count,
            "segmentCount": self.segment_count,
        }


def send_sms_via_twilio(to: str, body: str) -> SmsResult:
    """
    Send *body* to *to* (E.164 format) via the Twilio Messages API.

    Parameters
    ----------
    to:
        Destination phone number in E.164 format (e.g. ``+12125551234``).
    body:
        Rendered SMS body.  Must be ≤ 1600 characters (hard cap).

    Returns
    -------
    SmsResult
        Always returns; never raises.  Check ``.success`` to determine outcome.
    """
    settings = get_settings()
    char_count = _gsm7_length(body)
    segment_count = _estimate_segments(char_count)

    # ── Hard cap: reject before touching the API ──────────────────────────
    if char_count > settings.sms_max_chars:
        msg = (
            f"SMS body too long: {char_count} GSM-7 chars "
            f"(max {settings.sms_max_chars})"
        )
        logger.error("sms_body_too_long", char_count=char_count, to_masked="[REDACTED]")
        return SmsResult(
            success=False,
            error_code=None,
            error_message=msg,
            char_count=char_count,
            segment_count=segment_count,
        )

    # ── Warn on multi-segment (billing impact) ────────────────────────────
    if char_count > settings.sms_single_segment_chars:
        logger.warning(
            "sms_multi_segment",
            char_count=char_count,
            estimated_segments=segment_count,
            to_masked="[REDACTED]",
        )

    # ── Call Twilio Messages API ──────────────────────────────────────────
    client = _get_client()
    try:
        message = client.messages.create(
            to=to,
            from_=settings.twilio_from_number,
            body=body,
        )
        logger.info(
            "twilio_message_created",
            sid=message.sid,
            status=message.status,
            char_count=char_count,
            segment_count=segment_count,
            to_masked="[REDACTED]",
        )
        return SmsResult(
            success=True,
            message_sid=message.sid,
            status=message.status,
            char_count=char_count,
            segment_count=segment_count,
        )

    except TwilioRestException as exc:
        logger.error(
            "twilio_api_error",
            error_code=exc.code,
            error_message=exc.msg,
            http_status=exc.status,
            to_masked="[REDACTED]",
        )
        return SmsResult(
            success=False,
            error_code=exc.code,
            error_message=exc.msg,
            char_count=char_count,
            segment_count=segment_count,
        )

    except Exception as exc:
        logger.error(
            "twilio_unexpected_error",
            error=str(exc),
            to_masked="[REDACTED]",
        )
        return SmsResult(
            success=False,
            error_message=str(exc),
            char_count=char_count,
            segment_count=segment_count,
        )
