"""
tests/test_sms_service.py — Unit tests for services/sms_service.py (send_sms)

This is the most important test file: it exercises the full orchestration
logic without touching Twilio, Firestore, or any real network resource.

Covered paths
-------------
Happy path
  [A] Opt-in recipient + valid template → SMS sent → delivery record "sent"

Opt-out paths
  [B] Recipient opted out → early return, status "opted_out", no Twilio call
  [C] Opt-out check raises → hard stop, status "failed", no Twilio call

Template error paths
  [D] Template not found    → status "template_error", no Twilio call
  [E] Template disabled     → status "template_error", no Twilio call
  [F] Missing variable      → status "template_error", no Twilio call
  [G] Template render raises unexpected error → status "failed"

Twilio failure path
  [H] Twilio returns success=False → status "failed", delivery record written

Delivery record paths
  [I] Delivery record is always written (even on opt-out / failure)
  [J] Delivery record write failure is non-fatal (does not raise)

Return value shape
  [K] SmsDispatchResult fields are set correctly on success
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from services.sms_service import SmsDispatchResult, send_sms
from services.template_service import (
    MissingVariableError,
    RenderedTemplate,
    TemplateDisabledError,
    TemplateNotFoundError,
)
from services.twilio_client import SmsResult

PHONE = "+12125551234"
TEMPLATE_ID = "welcome_sms"
VARIABLES = {"clientName": "Jane Doe", "caseId": "ZAD-2025-03-0001"}
CASE_ID = "ZAD-2025-03-0001"
REQUEST_ID = "req-abc-123"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rendered(sms_safe: str = "Hi Jane Doe, your case ZAD-2025-03-0001 received.") -> RenderedTemplate:
    """Return a minimal RenderedTemplate for mocking render_template."""
    return RenderedTemplate(subject="", html_body=sms_safe, sms_safe=sms_safe)


def _success_twilio_result() -> SmsResult:
    return SmsResult(
        success=True,
        message_sid="SM1234567890abcdef",
        status="queued",
        char_count=80,
        segment_count=1,
    )


def _failure_twilio_result() -> SmsResult:
    return SmsResult(
        success=False,
        error_code=21211,
        error_message="Invalid 'To' number",
        char_count=80,
        segment_count=1,
    )


# ── [A] Happy path ────────────────────────────────────────────────────────────

class TestHappyPath:

    @pytest.mark.asyncio
    async def test_returns_success_result(self, mock_db):
        with (
            patch("services.sms_service.is_opted_out", new=AsyncMock(return_value=False)),
            patch("services.sms_service.render_template", new=AsyncMock(return_value=_rendered())),
            patch("services.sms_service.send_sms_via_twilio", return_value=_success_twilio_result()),
            patch("services.sms_service._write_delivery_record", new=AsyncMock()),
        ):
            result = await send_sms(PHONE, TEMPLATE_ID, VARIABLES, mock_db,
                                    case_id=CASE_ID, request_id=REQUEST_ID)

        assert result.success is True
        assert result.status == "sent"
        assert result.message_sid == "SM1234567890abcdef"

    @pytest.mark.asyncio
    async def test_delivery_record_written_with_sent_status(self, mock_db):
        with (
            patch("services.sms_service.is_opted_out", new=AsyncMock(return_value=False)),
            patch("services.sms_service.render_template", new=AsyncMock(return_value=_rendered())),
            patch("services.sms_service.send_sms_via_twilio", return_value=_success_twilio_result()),
            patch("services.sms_service._write_delivery_record", new=AsyncMock()) as mock_write,
        ):
            await send_sms(PHONE, TEMPLATE_ID, VARIABLES, mock_db)

        mock_write.assert_awaited_once()
        kwargs = mock_write.call_args.kwargs
        assert kwargs["status"] == "sent"

    @pytest.mark.asyncio
    async def test_sms_safe_body_sent_to_twilio(self, mock_db):
        """render_template().sms_safe must be passed to send_sms_via_twilio."""
        sms_body = "Hi Jane, ZAD-2025-001 confirmed."
        with (
            patch("services.sms_service.is_opted_out", new=AsyncMock(return_value=False)),
            patch("services.sms_service.render_template",
                  new=AsyncMock(return_value=_rendered(sms_body))),
            patch("services.sms_service.send_sms_via_twilio",
                  return_value=_success_twilio_result()) as mock_twilio,
            patch("services.sms_service._write_delivery_record", new=AsyncMock()),
        ):
            await send_sms(PHONE, TEMPLATE_ID, VARIABLES, mock_db)

        mock_twilio.assert_called_once_with(to=PHONE, body=sms_body)

    @pytest.mark.asyncio
    async def test_result_has_correct_segment_count(self, mock_db):
        twilio_result = SmsResult(success=True, message_sid="SMx", status="queued",
                                  char_count=320, segment_count=3)
        with (
            patch("services.sms_service.is_opted_out", new=AsyncMock(return_value=False)),
            patch("services.sms_service.render_template",
                  new=AsyncMock(return_value=_rendered("X" * 320))),
            patch("services.sms_service.send_sms_via_twilio", return_value=twilio_result),
            patch("services.sms_service._write_delivery_record", new=AsyncMock()),
        ):
            result = await send_sms(PHONE, TEMPLATE_ID, VARIABLES, mock_db)

        assert result.segment_count == 3
        assert result.char_count == 320


# ── [B] Opted-out recipient ───────────────────────────────────────────────────

class TestOptOut:

    @pytest.mark.asyncio
    async def test_opted_out_returns_opted_out_status(self, mock_db):
        with (
            patch("services.sms_service.is_opted_out", new=AsyncMock(return_value=True)),
            patch("services.sms_service.send_sms_via_twilio") as mock_twilio,
            patch("services.sms_service._write_delivery_record", new=AsyncMock()),
        ):
            result = await send_sms(PHONE, TEMPLATE_ID, VARIABLES, mock_db)

        assert result.success is False
        assert result.status == "opted_out"
        mock_twilio.assert_not_called()

    @pytest.mark.asyncio
    async def test_opted_out_still_writes_delivery_record(self, mock_db):
        with (
            patch("services.sms_service.is_opted_out", new=AsyncMock(return_value=True)),
            patch("services.sms_service.send_sms_via_twilio"),
            patch("services.sms_service._write_delivery_record", new=AsyncMock()) as mock_write,
        ):
            await send_sms(PHONE, TEMPLATE_ID, VARIABLES, mock_db)

        mock_write.assert_awaited_once()
        assert mock_write.call_args.kwargs["status"] == "opted_out"


# ── [C] Opt-out check raises ──────────────────────────────────────────────────

class TestOptOutCheckError:

    @pytest.mark.asyncio
    async def test_opt_out_check_failure_returns_failed_status(self, mock_db):
        """Opt-out lookup failure → hard stop, status 'failed', no Twilio call."""
        with (
            patch("services.sms_service.is_opted_out",
                  new=AsyncMock(side_effect=Exception("Firestore unavailable"))),
            patch("services.sms_service.send_sms_via_twilio") as mock_twilio,
            patch("services.sms_service._write_delivery_record", new=AsyncMock()),
        ):
            result = await send_sms(PHONE, TEMPLATE_ID, VARIABLES, mock_db)

        assert result.success is False
        assert result.status == "failed"
        mock_twilio.assert_not_called()


# ── [D/E/F] Template errors ───────────────────────────────────────────────────

class TestTemplateErrors:

    @pytest.mark.asyncio
    async def test_template_not_found_returns_template_error(self, mock_db):
        with (
            patch("services.sms_service.is_opted_out", new=AsyncMock(return_value=False)),
            patch("services.sms_service.render_template",
                  new=AsyncMock(side_effect=TemplateNotFoundError("missing"))),
            patch("services.sms_service.send_sms_via_twilio") as mock_twilio,
            patch("services.sms_service._write_delivery_record", new=AsyncMock()),
        ):
            result = await send_sms(PHONE, TEMPLATE_ID, VARIABLES, mock_db)

        assert result.success is False
        assert result.status == "template_error"
        mock_twilio.assert_not_called()

    @pytest.mark.asyncio
    async def test_template_disabled_returns_template_error(self, mock_db):
        with (
            patch("services.sms_service.is_opted_out", new=AsyncMock(return_value=False)),
            patch("services.sms_service.render_template",
                  new=AsyncMock(side_effect=TemplateDisabledError("disabled"))),
            patch("services.sms_service.send_sms_via_twilio") as mock_twilio,
            patch("services.sms_service._write_delivery_record", new=AsyncMock()),
        ):
            result = await send_sms(PHONE, TEMPLATE_ID, VARIABLES, mock_db)

        assert result.success is False
        assert result.status == "template_error"
        mock_twilio.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_variable_returns_template_error(self, mock_db):
        """MissingVariableError must yield template_error status, not crash."""
        exc = MissingVariableError("welcome_sms", ["clientName", "caseId"])
        with (
            patch("services.sms_service.is_opted_out", new=AsyncMock(return_value=False)),
            patch("services.sms_service.render_template", new=AsyncMock(side_effect=exc)),
            patch("services.sms_service.send_sms_via_twilio") as mock_twilio,
            patch("services.sms_service._write_delivery_record", new=AsyncMock()),
        ):
            result = await send_sms(PHONE, TEMPLATE_ID, {}, mock_db)

        assert result.success is False
        assert result.status == "template_error"
        assert "clientName" in result.error_message or "caseId" in result.error_message
        mock_twilio.assert_not_called()

    @pytest.mark.asyncio
    async def test_template_errors_write_delivery_record(self, mock_db):
        with (
            patch("services.sms_service.is_opted_out", new=AsyncMock(return_value=False)),
            patch("services.sms_service.render_template",
                  new=AsyncMock(side_effect=TemplateNotFoundError("missing"))),
            patch("services.sms_service.send_sms_via_twilio"),
            patch("services.sms_service._write_delivery_record", new=AsyncMock()) as mock_write,
        ):
            await send_sms(PHONE, TEMPLATE_ID, VARIABLES, mock_db)

        mock_write.assert_awaited_once()
        assert mock_write.call_args.kwargs["status"] == "template_error"


# ── [G] Unexpected render error ───────────────────────────────────────────────

class TestUnexpectedRenderError:

    @pytest.mark.asyncio
    async def test_unexpected_render_error_returns_failed(self, mock_db):
        with (
            patch("services.sms_service.is_opted_out", new=AsyncMock(return_value=False)),
            patch("services.sms_service.render_template",
                  new=AsyncMock(side_effect=RuntimeError("unexpected"))),
            patch("services.sms_service.send_sms_via_twilio") as mock_twilio,
            patch("services.sms_service._write_delivery_record", new=AsyncMock()),
        ):
            result = await send_sms(PHONE, TEMPLATE_ID, VARIABLES, mock_db)

        assert result.success is False
        assert result.status == "failed"
        mock_twilio.assert_not_called()


# ── [H] Twilio failure ────────────────────────────────────────────────────────

class TestTwilioFailure:

    @pytest.mark.asyncio
    async def test_twilio_failure_returns_failed_status(self, mock_db):
        with (
            patch("services.sms_service.is_opted_out", new=AsyncMock(return_value=False)),
            patch("services.sms_service.render_template", new=AsyncMock(return_value=_rendered())),
            patch("services.sms_service.send_sms_via_twilio", return_value=_failure_twilio_result()),
            patch("services.sms_service._write_delivery_record", new=AsyncMock()),
        ):
            result = await send_sms(PHONE, TEMPLATE_ID, VARIABLES, mock_db)

        assert result.success is False
        assert result.status == "failed"
        assert result.error_code == 21211

    @pytest.mark.asyncio
    async def test_twilio_failure_still_writes_delivery_record(self, mock_db):
        with (
            patch("services.sms_service.is_opted_out", new=AsyncMock(return_value=False)),
            patch("services.sms_service.render_template", new=AsyncMock(return_value=_rendered())),
            patch("services.sms_service.send_sms_via_twilio", return_value=_failure_twilio_result()),
            patch("services.sms_service._write_delivery_record", new=AsyncMock()) as mock_write,
        ):
            await send_sms(PHONE, TEMPLATE_ID, VARIABLES, mock_db)

        mock_write.assert_awaited_once()
        assert mock_write.call_args.kwargs["status"] == "failed"


# ── [I/J] Delivery record robustness ─────────────────────────────────────────

class TestDeliveryRecordRobustness:

    @pytest.mark.asyncio
    async def test_delivery_record_write_failure_does_not_raise(self, mock_db):
        """
        A Firestore write failure for the delivery record must NEVER propagate
        to the caller — the SMS may already be in-flight.
        """
        with (
            patch("services.sms_service.is_opted_out", new=AsyncMock(return_value=False)),
            patch("services.sms_service.render_template", new=AsyncMock(return_value=_rendered())),
            patch("services.sms_service.send_sms_via_twilio", return_value=_success_twilio_result()),
            patch("services.sms_service._write_delivery_record",
                  new=AsyncMock(side_effect=Exception("Firestore write timeout"))),
        ):
            # Should NOT raise even though _write_delivery_record fails
            result = await send_sms(PHONE, TEMPLATE_ID, VARIABLES, mock_db)

        # The SMS was sent; the result should reflect success
        assert result.success is True

    @pytest.mark.asyncio
    async def test_delivery_id_is_a_uuid(self, mock_db):
        import re
        uuid_re = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        )
        with (
            patch("services.sms_service.is_opted_out", new=AsyncMock(return_value=False)),
            patch("services.sms_service.render_template", new=AsyncMock(return_value=_rendered())),
            patch("services.sms_service.send_sms_via_twilio", return_value=_success_twilio_result()),
            patch("services.sms_service._write_delivery_record", new=AsyncMock()),
        ):
            result = await send_sms(PHONE, TEMPLATE_ID, VARIABLES, mock_db)

        assert uuid_re.match(result.delivery_id)


# ── [K] Return value shape ────────────────────────────────────────────────────

class TestReturnValueShape:

    @pytest.mark.asyncio
    async def test_all_fields_present_on_success(self, mock_db):
        with (
            patch("services.sms_service.is_opted_out", new=AsyncMock(return_value=False)),
            patch("services.sms_service.render_template", new=AsyncMock(return_value=_rendered())),
            patch("services.sms_service.send_sms_via_twilio", return_value=_success_twilio_result()),
            patch("services.sms_service._write_delivery_record", new=AsyncMock()),
        ):
            result = await send_sms(PHONE, TEMPLATE_ID, VARIABLES, mock_db,
                                    case_id=CASE_ID, request_id=REQUEST_ID)

        assert isinstance(result, SmsDispatchResult)
        assert result.success is True
        assert result.status == "sent"
        assert result.message_sid is not None
        assert result.error_code is None
        assert result.error_message is None
        assert result.char_count == 80
        assert result.segment_count == 1
