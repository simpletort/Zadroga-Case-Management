"""
tests/test_app.py — FastAPI endpoint tests for app.py

Uses Starlette's TestClient (synchronous wrapper) so no async test runner
config is needed for HTTP-level tests.

Covered endpoints
-----------------
POST /tasks/sms
  - Valid payload → 200 with delivery result
  - Missing required field → 422 Unprocessable Entity
  - send_sms raises unexpectedly → 500 (retryable by Cloud Tasks)
  - Returns 200 even when SMS fails (opted_out / failed) — Cloud Tasks must
    NOT retry successful delivery-record writes

POST /webhooks/twilio/inbound
  - STOP keyword → record_opt_out called
  - START keyword → clear_opt_out called
  - Unknown keyword → neither called
  - Returns TwiML <Response/>

GET /health
  - Returns 200 {"status": "healthy"}
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


# ── App fixture (APP_ENV=development bypasses OIDC/Twilio sig checks) ─────────

@pytest.fixture(scope="module")
def client():
    """TestClient with Firestore and send_sms patched at module level."""
    fake_db = AsyncMock()
    fake_db.collection = MagicMock()

    with patch("app.get_db", return_value=fake_db):
        # Import after patching to avoid real Firebase init
        from app import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c, fake_db


# ── POST /tasks/sms ───────────────────────────────────────────────────────────

class TestSmsTaskEndpoint:

    def test_valid_payload_returns_200(self, client):
        http_client, _ = client
        from services.sms_service import SmsDispatchResult

        mock_result = SmsDispatchResult(
            success=True,
            delivery_id="delivery-uuid-001",
            status="sent",
            message_sid="SM_test_001",
            segment_count=1,
        )

        with patch("app.send_sms", new=AsyncMock(return_value=mock_result)):
            response = http_client.post("/tasks/sms", json={
                "to": "+12125551234",
                "templateId": "welcome_sms",
                "variables": {"first_name": "Jane", "case_id": "ZAD-2025-03-0001"},
                "caseId": "ZAD-2025-03-0001",
                "requestId": "req-test-001",
            })

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["status"] == "sent"
        assert body["deliveryId"] == "delivery-uuid-001"
        assert body["messageSid"] == "SM_test_001"

    def test_missing_required_field_returns_422(self, client):
        """'to' is required; omitting it must return 422 (no retry from Cloud Tasks)."""
        http_client, _ = client
        response = http_client.post("/tasks/sms", json={
            "templateId": "welcome_sms",
            # 'to' omitted
        })
        assert response.status_code == 422

    def test_opted_out_returns_200_not_500(self, client):
        """
        When the recipient is opted out the handler should still return 200.
        Returning 500 would cause Cloud Tasks to retry, which we don't want.
        """
        http_client, _ = client
        from services.sms_service import SmsDispatchResult

        opted_out_result = SmsDispatchResult(
            success=False,
            delivery_id="delivery-uuid-002",
            status="opted_out",
        )

        with patch("app.send_sms", new=AsyncMock(return_value=opted_out_result)):
            response = http_client.post("/tasks/sms", json={
                "to": "+12125550000",
                "templateId": "welcome_sms",
                "variables": {},
            })

        assert response.status_code == 200
        assert response.json()["status"] == "opted_out"

    def test_twilio_failure_still_returns_200(self, client):
        """Twilio API failure → delivery record written → 200 so Cloud Tasks doesn't retry."""
        http_client, _ = client
        from services.sms_service import SmsDispatchResult

        failed_result = SmsDispatchResult(
            success=False,
            delivery_id="delivery-uuid-003",
            status="failed",
            error_code=21211,
            error_message="Invalid To",
        )

        with patch("app.send_sms", new=AsyncMock(return_value=failed_result)):
            response = http_client.post("/tasks/sms", json={
                "to": "+10000000000",
                "templateId": "welcome_sms",
                "variables": {},
            })

        assert response.status_code == 200
        assert response.json()["status"] == "failed"

    def test_unhandled_exception_from_send_sms_returns_500(self, client):
        """If send_sms itself raises (shouldn't happen), Cloud Tasks should retry → 500."""
        http_client, _ = client

        with patch("app.send_sms", new=AsyncMock(side_effect=RuntimeError("boom"))):
            response = http_client.post("/tasks/sms", json={
                "to": "+12125551234",
                "templateId": "welcome_sms",
                "variables": {},
            })

        assert response.status_code == 500

    def test_send_sms_called_with_correct_args(self, client):
        http_client, _ = client
        from services.sms_service import SmsDispatchResult

        mock_result = SmsDispatchResult(
            success=True, delivery_id="d1", status="sent", segment_count=1
        )

        with patch("app.send_sms", new=AsyncMock(return_value=mock_result)) as mock_fn:
            http_client.post("/tasks/sms", json={
                "to": "+12125551234",
                "templateId": "welcome_sms",
                "variables": {"first_name": "Alice"},
                "caseId": "ZAD-2025-03-0099",
                "requestId": "req-xyz",
            })

        mock_fn.assert_awaited_once()
        # app.py calls send_sms with all keyword arguments, so .args is empty.
        # Use .kwargs to inspect every parameter.
        call_kwargs = mock_fn.call_args.kwargs
        assert call_kwargs["to"] == "+12125551234"
        assert call_kwargs["template_id"] == "welcome_sms"
        assert call_kwargs["variables"] == {"first_name": "Alice"}
        assert call_kwargs["case_id"] == "ZAD-2025-03-0099"
        assert call_kwargs["request_id"] == "req-xyz"


# ── POST /webhooks/twilio/inbound ─────────────────────────────────────────────

class TestTwilioInboundWebhook:

    def _post_inbound(self, http_client, body_keyword: str, from_number: str = "+12125551234"):
        return http_client.post(
            "/webhooks/twilio/inbound",
            data={"From": from_number, "Body": body_keyword},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    def test_stop_keyword_records_opt_out(self, client):
        http_client, _ = client

        with patch("app.record_opt_out", new=AsyncMock()) as mock_opt_out:
            self._post_inbound(http_client, "STOP")

        mock_opt_out.assert_awaited_once()
        call_kwargs = mock_opt_out.call_args
        assert call_kwargs.kwargs["reason"] == "STOP"

    def test_start_keyword_clears_opt_out(self, client):
        http_client, _ = client

        with patch("app.clear_opt_out", new=AsyncMock()) as mock_clear:
            self._post_inbound(http_client, "START")

        mock_clear.assert_awaited_once()

    def test_unsubscribe_keyword_records_opt_out(self, client):
        http_client, _ = client

        with patch("app.record_opt_out", new=AsyncMock()) as mock_opt_out:
            self._post_inbound(http_client, "UNSUBSCRIBE")

        mock_opt_out.assert_awaited_once()
        assert mock_opt_out.call_args.kwargs["reason"] == "UNSUBSCRIBE"

    def test_unknown_keyword_calls_neither(self, client):
        http_client, _ = client

        with (
            patch("app.record_opt_out", new=AsyncMock()) as mock_opt_out,
            patch("app.clear_opt_out", new=AsyncMock()) as mock_clear,
        ):
            self._post_inbound(http_client, "HELLO")

        mock_opt_out.assert_not_awaited()
        mock_clear.assert_not_awaited()

    def test_returns_twiml_response(self, client):
        http_client, _ = client

        with patch("app.record_opt_out", new=AsyncMock()):
            response = self._post_inbound(http_client, "STOP")

        assert response.status_code == 200
        assert "<Response>" in response.text
        assert "text/xml" in response.headers["content-type"]

    def test_lowercase_stop_is_handled(self, client):
        """Body comparison should be case-insensitive (Body.strip().upper())."""
        http_client, _ = client

        with patch("app.record_opt_out", new=AsyncMock()) as mock_opt_out:
            self._post_inbound(http_client, "stop")

        mock_opt_out.assert_awaited_once()


# ── GET /health ───────────────────────────────────────────────────────────────

class TestHealthEndpoint:

    def test_health_returns_200(self, client):
        http_client, _ = client
        response = http_client.get("/health")
        assert response.status_code == 200

    def test_health_body(self, client):
        http_client, _ = client
        body = http_client.get("/health").json()
        assert body["status"] == "healthy"
        assert body["service"] == "notification"

    def test_root_returns_service_name(self, client):
        http_client, _ = client
        body = http_client.get("/").json()
        assert "notification" in body["service"].lower()
