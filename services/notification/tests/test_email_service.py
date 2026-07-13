"""
tests/test_email_service.py — Unit tests for services/email_service.py

Covers
------
Firm settings injection
  - firmName from firmSettings/notifications.fromName injected into variables
  - from_name passed to send_email_via_sendgrid
  - Graceful fallback when firmSettings/notifications document is absent
  - Caller-supplied firmName overrides firm default

Practice-area template override
  - Practice-area override used when available
  - Falls back to base template when no override exists

Happy path
  - Template rendered with merged variables (firm defaults + caller vars)
  - Delivery record written on success

Error paths
  - TemplateNotFoundError → status "template_error", no SendGrid call
  - TemplateDisabledError → status "template_error"
  - MissingVariableError  → status "template_error"
  - SendGrid failure      → status "failed", delivery record written

Delivery record
  - Written on success
  - Written on failure (never skipped)
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.email_service import EmailDispatchResult, send_email, _load_firm_notification_settings
from services.sendgrid_client import EmailResult
from services.template_service import (
    MissingVariableError,
    RenderedTemplate,
    TemplateDisabledError,
    TemplateNotFoundError,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_doc(exists: bool, data: dict | None = None) -> MagicMock:
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = data or {}
    return snap


def _make_db(firm_notifications: dict | None = None) -> AsyncMock:
    """
    Return a minimal async Firestore stub pre-wired with firmSettings/notifications.
    Pass firm_notifications=None to simulate a missing document.
    """
    db = AsyncMock()

    firm_doc = _make_doc(
        exists=firm_notifications is not None,
        data=firm_notifications or {},
    )

    def _collection(name: str):
        col = MagicMock()

        def _document(doc_id: str):
            doc_mock = AsyncMock()
            if name == "firmSettings" and doc_id == "notifications":
                doc_mock.get = AsyncMock(return_value=firm_doc)
            else:
                doc_mock.get = AsyncMock(return_value=_make_doc(exists=False))
                doc_mock.set = AsyncMock()
                # Support sub-collections (delivery_records, notifications)
                sub_col = MagicMock()
                sub_doc = AsyncMock()
                sub_doc.get = AsyncMock(return_value=_make_doc(exists=False))
                sub_doc.set = AsyncMock()
                sub_col.document = MagicMock(return_value=sub_doc)
                doc_mock.collection = MagicMock(return_value=sub_col)
            return doc_mock

        col.document = MagicMock(side_effect=_document)
        return col

    db.collection = MagicMock(side_effect=_collection)
    return db


def _rendered(subject: str = "Test Subject", body: str = "Test body.") -> RenderedTemplate:
    return RenderedTemplate(subject=subject, html_body=f"<p>{body}</p>", sms_safe=body)


def _success_result() -> EmailResult:
    return EmailResult(
        success=True,
        message_id="msg-001",
        status_code=202,
    )


def _failure_result(msg: str = "API error") -> EmailResult:
    return EmailResult(
        success=False,
        status_code=403,
        error_message=msg,
    )


FIRM_NOTIFICATIONS = {
    "fromName": "SimpleTort Legal",
    "replyTo":  "support@simpletort.com",
    "logoUrl":  "https://cdn.simpletort.com/logo.png",
}

TO = "client@example.com"
TEMPLATE_ID = "welcome_email"
VARIABLES = {"clientName": "Jane Doe", "caseId": "ZAD-2026-001"}
CASE_ID = "ZAD-2026-001"


# ── _load_firm_notification_settings ─────────────────────────────────────────

class TestLoadFirmNotificationSettings:

    @pytest.mark.asyncio
    async def test_returns_from_name_as_firm_name(self):
        db = _make_db(firm_notifications=FIRM_NOTIFICATIONS)
        settings = await _load_firm_notification_settings(db)
        assert settings["firmName"] == "SimpleTort Legal"

    @pytest.mark.asyncio
    async def test_returns_reply_to(self):
        db = _make_db(firm_notifications=FIRM_NOTIFICATIONS)
        settings = await _load_firm_notification_settings(db)
        assert settings["firmReplyTo"] == "support@simpletort.com"

    @pytest.mark.asyncio
    async def test_returns_logo_url(self):
        db = _make_db(firm_notifications=FIRM_NOTIFICATIONS)
        settings = await _load_firm_notification_settings(db)
        assert settings["firmLogoUrl"] == "https://cdn.simpletort.com/logo.png"

    @pytest.mark.asyncio
    async def test_missing_document_returns_empty_strings(self):
        """firmSettings/notifications absent → empty strings, no exception."""
        db = _make_db(firm_notifications=None)
        settings = await _load_firm_notification_settings(db)
        assert settings["firmName"] == ""
        assert settings["firmReplyTo"] == ""
        assert settings["firmLogoUrl"] == ""

    @pytest.mark.asyncio
    async def test_firestore_error_returns_empty_strings(self):
        """Firestore error → empty strings, no exception propagated."""
        db = AsyncMock()
        db.collection = MagicMock(side_effect=RuntimeError("connection failed"))
        settings = await _load_firm_notification_settings(db)
        assert settings["firmName"] == ""

    @pytest.mark.asyncio
    async def test_partial_document_fills_missing_fields(self):
        """Only fromName present → replyTo and logoUrl are empty strings."""
        db = _make_db(firm_notifications={"fromName": "Acme Law"})
        settings = await _load_firm_notification_settings(db)
        assert settings["firmName"] == "Acme Law"
        assert settings["firmReplyTo"] == ""
        assert settings["firmLogoUrl"] == ""


# ── send_email — firm settings injection ─────────────────────────────────────

class TestSendEmailFirmSettingsInjection:

    @pytest.mark.asyncio
    @patch("services.email_service._write_delivery_record", new_callable=AsyncMock)
    @patch("services.email_service.write_notification_record", new_callable=AsyncMock)
    async def test_firm_name_injected_into_render_variables(
        self, _write_notif, _write_delivery
    ):
        """firmName from firmSettings/notifications.fromName is in merged_variables."""
        db = _make_db(firm_notifications={"fromName": "SimpleTort Legal"})
        captured: list[dict] = []

        async def mock_render(template_id, variables, db_arg, *, template_data=None):
            captured.append(dict(variables))
            return _rendered()

        with (
            patch("services.email_service.load_notification_template",
                  new=AsyncMock(return_value={"body": "", "subject": "", "isActive": True})),
            patch("services.email_service.render_template", side_effect=mock_render),
            patch("services.email_service.send_email_via_sendgrid",
                  return_value=_success_result()),
        ):
            await send_email(TO, TEMPLATE_ID, VARIABLES, db, case_id=CASE_ID)

        assert captured, "render_template was never called"
        assert captured[0]["firmName"] == "SimpleTort Legal"

    @pytest.mark.asyncio
    @patch("services.email_service._write_delivery_record", new_callable=AsyncMock)
    @patch("services.email_service.write_notification_record", new_callable=AsyncMock)
    async def test_caller_variable_overrides_firm_default(
        self, _write_notif, _write_delivery
    ):
        """Caller-supplied firmName takes precedence over the firm settings value."""
        db = _make_db(firm_notifications={"fromName": "SimpleTort Legal"})
        captured: list[dict] = []

        async def mock_render(template_id, variables, db_arg, *, template_data=None):
            captured.append(dict(variables))
            return _rendered()

        with (
            patch("services.email_service.load_notification_template",
                  new=AsyncMock(return_value={"body": "", "subject": "", "isActive": True})),
            patch("services.email_service.render_template", side_effect=mock_render),
            patch("services.email_service.send_email_via_sendgrid",
                  return_value=_success_result()),
        ):
            await send_email(
                TO, TEMPLATE_ID,
                {**VARIABLES, "firmName": "Override Name"},
                db, case_id=CASE_ID,
            )

        assert captured[0]["firmName"] == "Override Name"

    @pytest.mark.asyncio
    @patch("services.email_service._write_delivery_record", new_callable=AsyncMock)
    @patch("services.email_service.write_notification_record", new_callable=AsyncMock)
    async def test_from_name_passed_to_sendgrid_client(
        self, _write_notif, _write_delivery
    ):
        """send_email_via_sendgrid is called with from_name from firmSettings."""
        db = _make_db(firm_notifications={"fromName": "SimpleTort Legal"})
        sendgrid_calls: list[dict] = []

        def mock_sendgrid(**kwargs):
            sendgrid_calls.append(kwargs)
            return _success_result()

        with (
            patch("services.email_service.load_notification_template",
                  new=AsyncMock(return_value={"body": "", "subject": "", "isActive": True})),
            patch("services.email_service.render_template",
                  new=AsyncMock(return_value=_rendered())),
            patch("services.email_service.send_email_via_sendgrid",
                  side_effect=mock_sendgrid),
        ):
            await send_email(TO, TEMPLATE_ID, VARIABLES, db, case_id=CASE_ID)

        assert sendgrid_calls, "send_email_via_sendgrid was never called"
        assert sendgrid_calls[0]["from_name"] == "SimpleTort Legal"

    @pytest.mark.asyncio
    @patch("services.email_service._write_delivery_record", new_callable=AsyncMock)
    @patch("services.email_service.write_notification_record", new_callable=AsyncMock)
    async def test_from_name_none_when_firm_name_empty(
        self, _write_notif, _write_delivery
    ):
        """Empty firmName → from_name=None so sendgrid_client falls back to config default."""
        db = _make_db(firm_notifications=None)  # no firmSettings doc
        sendgrid_calls: list[dict] = []

        def mock_sendgrid(**kwargs):
            sendgrid_calls.append(kwargs)
            return _success_result()

        with (
            patch("services.email_service.load_notification_template",
                  new=AsyncMock(return_value={"body": "", "subject": "", "isActive": True})),
            patch("services.email_service.render_template",
                  new=AsyncMock(return_value=_rendered())),
            patch("services.email_service.send_email_via_sendgrid",
                  side_effect=mock_sendgrid),
        ):
            await send_email(TO, TEMPLATE_ID, VARIABLES, db, case_id=CASE_ID)

        assert sendgrid_calls[0]["from_name"] is None

    @pytest.mark.asyncio
    @patch("services.email_service._write_delivery_record", new_callable=AsyncMock)
    @patch("services.email_service.write_notification_record", new_callable=AsyncMock)
    async def test_practice_area_forwarded_to_load_notification_template(
        self, _write_notif, _write_delivery
    ):
        """practice_area kwarg is passed through to load_notification_template."""
        db = _make_db(firm_notifications=FIRM_NOTIFICATIONS)
        captured_practice_areas: list = []

        async def mock_load(db_arg, tid, pa=None):
            captured_practice_areas.append(pa)
            return {"body": "", "subject": "", "isActive": True}

        with (
            patch("services.email_service.load_notification_template",
                  side_effect=mock_load),
            patch("services.email_service.render_template",
                  new=AsyncMock(return_value=_rendered())),
            patch("services.email_service.send_email_via_sendgrid",
                  return_value=_success_result()),
        ):
            await send_email(
                TO, TEMPLATE_ID, VARIABLES, db,
                case_id=CASE_ID, practice_area="mass_tort",
            )

        assert captured_practice_areas == ["mass_tort"]


# ── send_email — happy path ───────────────────────────────────────────────────

class TestSendEmailHappyPath:

    @pytest.mark.asyncio
    @patch("services.email_service._write_delivery_record", new_callable=AsyncMock)
    @patch("services.email_service.write_notification_record", new_callable=AsyncMock)
    async def test_returns_success_result(self, _write_notif, _write_delivery):
        db = _make_db(firm_notifications=FIRM_NOTIFICATIONS)
        with (
            patch("services.email_service.load_notification_template",
                  new=AsyncMock(return_value={"body": "", "subject": "", "isActive": True})),
            patch("services.email_service.render_template",
                  new=AsyncMock(return_value=_rendered())),
            patch("services.email_service.send_email_via_sendgrid",
                  return_value=_success_result()),
        ):
            result = await send_email(TO, TEMPLATE_ID, VARIABLES, db, case_id=CASE_ID)

        assert isinstance(result, EmailDispatchResult)
        assert result.success is True
        assert result.status == "sent"

    @pytest.mark.asyncio
    @patch("services.email_service._write_delivery_record", new_callable=AsyncMock)
    @patch("services.email_service.write_notification_record", new_callable=AsyncMock)
    async def test_delivery_record_written_on_success(
        self, _write_notif, write_delivery
    ):
        db = _make_db(firm_notifications=FIRM_NOTIFICATIONS)
        with (
            patch("services.email_service.load_notification_template",
                  new=AsyncMock(return_value={"body": "", "subject": "", "isActive": True})),
            patch("services.email_service.render_template",
                  new=AsyncMock(return_value=_rendered())),
            patch("services.email_service.send_email_via_sendgrid",
                  return_value=_success_result()),
        ):
            await send_email(TO, TEMPLATE_ID, VARIABLES, db, case_id=CASE_ID)

        write_delivery.assert_awaited_once()


# ── send_email — template error paths ────────────────────────────────────────

class TestSendEmailTemplateErrors:

    @pytest.mark.asyncio
    async def test_template_not_found_returns_template_error(self):
        db = _make_db(firm_notifications=FIRM_NOTIFICATIONS)
        with patch("services.email_service.load_notification_template",
                   new=AsyncMock(side_effect=TemplateNotFoundError("not found"))):
            result = await send_email(TO, TEMPLATE_ID, VARIABLES, db)

        assert result.status == "template_error"
        assert result.success is False

    @pytest.mark.asyncio
    async def test_template_disabled_returns_template_error(self):
        db = _make_db(firm_notifications=FIRM_NOTIFICATIONS)
        with patch("services.email_service.load_notification_template",
                   new=AsyncMock(side_effect=TemplateDisabledError("disabled"))):
            result = await send_email(TO, TEMPLATE_ID, VARIABLES, db)

        assert result.status == "template_error"

    @pytest.mark.asyncio
    async def test_missing_variable_returns_template_error(self):
        db = _make_db(firm_notifications=FIRM_NOTIFICATIONS)
        with (
            patch("services.email_service.load_notification_template",
                  new=AsyncMock(return_value={"body": "", "subject": "", "isActive": True})),
            patch("services.email_service.render_template",
                  new=AsyncMock(side_effect=MissingVariableError(
                      TEMPLATE_ID, ["firmName"]
                  ))),
        ):
            result = await send_email(TO, TEMPLATE_ID, {}, db)

        assert result.status == "template_error"


# ── send_email — SendGrid failure ─────────────────────────────────────────────

class TestSendEmailSendGridFailure:

    @pytest.mark.asyncio
    @patch("services.email_service._write_delivery_record", new_callable=AsyncMock)
    @patch("services.email_service.write_notification_record", new_callable=AsyncMock)
    async def test_sendgrid_failure_returns_failed_status(
        self, _write_notif, _write_delivery
    ):
        db = _make_db(firm_notifications=FIRM_NOTIFICATIONS)
        with (
            patch("services.email_service.load_notification_template",
                  new=AsyncMock(return_value={"body": "", "subject": "", "isActive": True})),
            patch("services.email_service.render_template",
                  new=AsyncMock(return_value=_rendered())),
            patch("services.email_service.send_email_via_sendgrid",
                  return_value=_failure_result("401 Unauthorized")),
        ):
            result = await send_email(TO, TEMPLATE_ID, VARIABLES, db)

        assert result.success is False
        assert result.status == "failed"
        assert "401 Unauthorized" in result.error_message

    @pytest.mark.asyncio
    @patch("services.email_service._write_delivery_record", new_callable=AsyncMock)
    @patch("services.email_service.write_notification_record", new_callable=AsyncMock)
    async def test_delivery_record_written_on_sendgrid_failure(
        self, _write_notif, write_delivery
    ):
        """Delivery record must be written even when SendGrid fails."""
        db = _make_db(firm_notifications=FIRM_NOTIFICATIONS)
        with (
            patch("services.email_service.load_notification_template",
                  new=AsyncMock(return_value={"body": "", "subject": "", "isActive": True})),
            patch("services.email_service.render_template",
                  new=AsyncMock(return_value=_rendered())),
            patch("services.email_service.send_email_via_sendgrid",
                  return_value=_failure_result()),
        ):
            await send_email(TO, TEMPLATE_ID, VARIABLES, db, case_id=CASE_ID)

        write_delivery.assert_awaited_once()
