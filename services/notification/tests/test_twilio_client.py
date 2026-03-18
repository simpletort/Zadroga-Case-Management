"""
tests/test_twilio_client.py — Unit tests for services/twilio_client.py

Covers
------
- GSM-7 character counting (_gsm7_length)
- Segment estimation (_estimate_segments)
- Single-segment happy path (≤ 160 chars)
- Multi-segment warning path (161–1600 chars)
- Hard cap rejection (> 1600 chars)
- TwilioRestException mapped to SmsResult(success=False)
- Unexpected exception mapped to SmsResult(success=False)
- Twilio client singleton initialisation
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call
from twilio.base.exceptions import TwilioRestException

import services.twilio_client as tc
from services.twilio_client import (
    SmsResult,
    _estimate_segments,
    _gsm7_length,
    send_sms_via_twilio,
)


# ── GSM-7 character counting ──────────────────────────────────────────────────

class TestGsm7Length:
    def test_plain_ascii_is_one_to_one(self):
        assert _gsm7_length("Hello, World!") == 13

    def test_extended_chars_count_as_two(self):
        # € is an extended GSM-7 char → counts as 2
        assert _gsm7_length("€") == 2
        assert _gsm7_length("{}") == 4       # { and } each count as 2
        assert _gsm7_length("[~]") == 6      # [ ~ ] each count as 2

    def test_mixed_content(self):
        # "Hi€" → H(1) + i(1) + €(2) = 4
        assert _gsm7_length("Hi€") == 4

    def test_empty_string(self):
        assert _gsm7_length("") == 0

    def test_exactly_160_plain_ascii(self):
        msg = "A" * 160
        assert _gsm7_length(msg) == 160

    def test_160_with_one_extended_is_actually_161(self):
        # 159 regular + 1 extended = 160 regular + 2 extended chars = 161 GSM units
        msg = "A" * 159 + "€"
        assert _gsm7_length(msg) == 161


# ── Segment estimation ────────────────────────────────────────────────────────

class TestEstimateSegments:
    def test_exactly_160_is_one_segment(self):
        assert _estimate_segments(160) == 1

    def test_zero_is_one_segment(self):
        assert _estimate_segments(0) == 1

    def test_161_is_two_segments(self):
        # 161 > 160, so concatenated: ceil(161/153) = 2
        assert _estimate_segments(161) == 2

    def test_306_is_two_segments(self):
        # 153 * 2 = 306
        assert _estimate_segments(306) == 2

    def test_307_is_three_segments(self):
        assert _estimate_segments(307) == 3

    def test_1600_chars_segment_count(self):
        import math
        assert _estimate_segments(1600) == math.ceil(1600 / 153)


# ── send_sms_via_twilio — happy paths ─────────────────────────────────────────

class TestSendSmsViaTwilio:

    def test_single_segment_success(self, mock_twilio_client, mock_twilio_msg):
        """160-char message → success, 1 segment, correct SID."""
        body = "A" * 160
        result = send_sms_via_twilio("+12125551234", body)

        assert result.success is True
        assert result.message_sid == mock_twilio_msg.sid
        assert result.status == mock_twilio_msg.status
        assert result.char_count == 160
        assert result.segment_count == 1
        assert result.error_code is None
        assert result.error_message is None

    def test_twilio_create_called_with_correct_args(self, mock_twilio_client):
        """Verify the Twilio API is called with to/from/body."""
        body = "Test message"
        send_sms_via_twilio("+12125551234", body)

        mock_twilio_client.messages.create.assert_called_once_with(
            to="+12125551234",
            from_="+15005550006",   # from conftest env
            body=body,
        )

    def test_multi_segment_still_succeeds(self, mock_twilio_client):
        """Message over 160 chars is still sent; segment_count > 1."""
        body = "B" * 320   # 320 chars → 3 segments
        result = send_sms_via_twilio("+12125551234", body)

        assert result.success is True
        assert result.char_count == 320
        assert result.segment_count == 3   # ceil(320/153) = 3

    def test_to_dict_shape(self, mock_twilio_client):
        """SmsResult.to_dict() returns all expected keys."""
        result = send_sms_via_twilio("+12125551234", "Hi")
        d = result.to_dict()
        assert set(d.keys()) == {
            "success", "messageSid", "status",
            "errorCode", "errorMessage", "charCount", "segmentCount",
        }


# ── send_sms_via_twilio — hard cap ────────────────────────────────────────────

class TestHardCap:

    def test_over_1600_chars_rejected_without_api_call(self, mock_twilio_client):
        """Messages over 1600 GSM-7 chars must be rejected before Twilio is called."""
        body = "X" * 1601
        result = send_sms_via_twilio("+12125551234", body)

        assert result.success is False
        assert result.error_message is not None
        assert "too long" in result.error_message.lower()
        mock_twilio_client.messages.create.assert_not_called()

    def test_exactly_1600_chars_is_allowed(self, mock_twilio_client):
        """1600-char message is at the limit and should be sent."""
        body = "Y" * 1600
        result = send_sms_via_twilio("+12125551234", body)
        assert result.success is True
        mock_twilio_client.messages.create.assert_called_once()


# ── send_sms_via_twilio — error handling ─────────────────────────────────────

class TestErrorHandling:

    def test_twilio_rest_exception_returns_failure(self, mock_twilio_client):
        """TwilioRestException → SmsResult(success=False) with error code."""
        mock_twilio_client.messages.create.side_effect = TwilioRestException(
            status=400,
            uri="/Messages",
            msg="The 'To' number is not a valid phone number",
            code=21211,
            method="POST",
        )
        result = send_sms_via_twilio("+10000000000", "Hi")

        assert result.success is False
        assert result.error_code == 21211
        assert result.message_sid is None

    def test_unexpected_exception_returns_failure(self, mock_twilio_client):
        """Any unexpected exception → SmsResult(success=False)."""
        mock_twilio_client.messages.create.side_effect = ConnectionError("network down")
        result = send_sms_via_twilio("+12125551234", "Hi")

        assert result.success is False
        assert result.error_message == "network down"
        assert result.message_sid is None

    def test_error_result_has_no_sid(self, mock_twilio_client):
        """Failed results must not have a message SID."""
        mock_twilio_client.messages.create.side_effect = Exception("boom")
        result = send_sms_via_twilio("+12125551234", "Hi")
        assert result.message_sid is None


# ── Singleton behaviour ───────────────────────────────────────────────────────

class TestClientSingleton:

    def test_client_reused_across_calls(self, mock_twilio_client):
        """The Twilio client is not re-instantiated between calls."""
        send_sms_via_twilio("+12125551234", "First")
        send_sms_via_twilio("+12125551234", "Second")
        # _get_client() returns the same object; messages.create called twice
        assert mock_twilio_client.messages.create.call_count == 2
