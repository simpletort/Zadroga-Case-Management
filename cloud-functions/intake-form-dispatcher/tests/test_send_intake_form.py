"""
Tests for intake-form-dispatcher — send_intake_form HTTP Cloud Function.
"""
import pytest
from unittest.mock import MagicMock, patch
from flask import Flask

import main
from tests.conftest import FORM_CONFIG, CASE_DATA


# ── Helpers ────────────────────────────────────────────────────────────────────

@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def mock_db():
    with patch("main._get_db") as mock_get_db:
        db = MagicMock()
        mock_get_db.return_value = db
        yield db


@pytest.fixture()
def mock_form_config():
    with patch("main._get_form_config", return_value=FORM_CONFIG):
        yield FORM_CONFIG


@pytest.fixture()
def mock_sendgrid():
    with patch("main.sendgrid") as mock_sg:
        sg_instance = MagicMock()
        sg_instance.send.return_value = MagicMock(status_code=202)
        mock_sg.SendGridAPIClient.return_value = sg_instance
        yield sg_instance


def _make_case_snap(data=None, exists=True):
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = data or CASE_DATA.copy()
    return snap


def _post(app, body, headers=None):
    with app.test_request_context(
        "/send",
        method="POST",
        json=body,
        headers=headers or {"X-Staff-UID": "staff-123"},
    ):
        from flask import request
        return main.send_intake_form(request)


def _setup_happy_db(mock_db):
    case_snap = _make_case_snap()
    token_ref = MagicMock()

    cases_col = MagicMock()
    cases_col.document.return_value.get.return_value = case_snap
    cases_col.document.return_value.update = MagicMock()

    tokens_col = MagicMock()
    tokens_col.document.return_value = token_ref

    def collection_side_effect(name):
        if name == "cases":
            return cases_col
        if name == "intake_tokens":
            return tokens_col
        return MagicMock()

    mock_db.collection.side_effect = collection_side_effect
    return token_ref, cases_col


# ── Validation ─────────────────────────────────────────────────────────────────

class TestValidation:
    def test_missing_case_id_returns_400(self, app, mock_form_config):
        resp = _post(app, {})
        assert resp.status_code == 400

    def test_invalid_case_id_format_returns_400(self, app, mock_form_config):
        resp = _post(app, {"caseId": "INVALID-123"})
        assert resp.status_code == 400

    def test_get_method_returns_405(self, app):
        with app.test_request_context("/send", method="GET"):
            from flask import request
            resp = main.send_intake_form(request)
        assert resp.status_code == 405

    def test_options_returns_204(self, app):
        with app.test_request_context("/send", method="OPTIONS"):
            from flask import request
            resp = main.send_intake_form(request)
        assert resp.status_code == 204

    def test_case_not_found_returns_404(self, app, mock_db, mock_form_config):
        mock_db.collection.return_value.document.return_value.get.return_value = \
            _make_case_snap(exists=False)
        resp = _post(app, {"caseId": "ZAD-2026-03-0001"})
        assert resp.status_code == 404

    def test_wrong_case_status_returns_409(self, app, mock_db, mock_form_config):
        mock_db.collection.return_value.document.return_value.get.return_value = \
            _make_case_snap(data={**CASE_DATA, "status": "Pending Paralegal Review"})
        resp = _post(app, {"caseId": "ZAD-2026-03-0001"})
        assert resp.status_code == 409

    def test_missing_email_returns_422(self, app, mock_db, mock_form_config):
        no_email = {**CASE_DATA, "leadData": {**CASE_DATA["leadData"], "email": ""}}
        mock_db.collection.return_value.document.return_value.get.return_value = \
            _make_case_snap(data=no_email)
        resp = _post(app, {"caseId": "ZAD-2026-03-0001"})
        assert resp.status_code == 422

    def test_form_config_missing_returns_500(self, app, mock_db):
        mock_db.collection.return_value.document.return_value.get.return_value = \
            _make_case_snap()
        with patch("main._get_form_config", side_effect=RuntimeError("config/intake_form not found")):
            resp = _post(app, {"caseId": "ZAD-2026-03-0001"})
        assert resp.status_code == 500


# ── Happy path ─────────────────────────────────────────────────────────────────

class TestHappyPath:
    def test_returns_200_with_token_and_url(self, app, mock_db, mock_form_config, mock_sendgrid):
        _setup_happy_db(mock_db)
        resp = _post(app, {"caseId": "ZAD-2026-03-0001"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "tokenId" in data
        assert "previewUrl" in data
        assert "emailSent" in data

    def test_prefill_url_contains_entry_ids(self, app, mock_db, mock_form_config, mock_sendgrid):
        _setup_happy_db(mock_db)
        resp = _post(app, {"caseId": "ZAD-2026-03-0001"})
        url = resp.get_json()["previewUrl"]
        assert "entry.111=John" in url
        assert "entry.222=Smith" in url
        assert "entry.333=" in url
        assert "entry.444=" in url
        assert "entry.555=" in url

    def test_prefill_url_uses_form_base_url(self, app, mock_db, mock_form_config, mock_sendgrid):
        _setup_happy_db(mock_db)
        resp = _post(app, {"caseId": "ZAD-2026-03-0001"})
        url = resp.get_json()["previewUrl"]
        assert url.startswith("https://docs.google.com/forms/d/TEST_FORM_ID/viewform")

    def test_token_written_to_firestore(self, app, mock_db, mock_form_config, mock_sendgrid):
        token_ref, _ = _setup_happy_db(mock_db)
        _post(app, {"caseId": "ZAD-2026-03-0001"})
        token_ref.set.assert_called_once()
        call_args = token_ref.set.call_args[0][0]
        assert call_args["caseId"] == "ZAD-2026-03-0001"
        assert call_args["used"] is False
        assert call_args["clientEmail"] == "john.smith@example.com"

    def test_case_status_advanced_from_new_lead(self, app, mock_db, mock_form_config, mock_sendgrid):
        _, cases_col = _setup_happy_db(mock_db)
        _post(app, {"caseId": "ZAD-2026-03-0001"})
        cases_col.document.return_value.update.assert_called()
        update_payload = cases_col.document.return_value.update.call_args[0][0]
        assert update_payload["status"] == "Pending Client Info"

    def test_email_sent_true_when_sendgrid_succeeds(self, app, mock_db, mock_form_config, mock_sendgrid):
        _setup_happy_db(mock_db)
        resp = _post(app, {"caseId": "ZAD-2026-03-0001"})
        assert resp.get_json()["emailSent"] is True

    def test_email_sent_false_when_sendgrid_fails(self, app, mock_db, mock_form_config):
        _setup_happy_db(mock_db)
        with patch("main.sendgrid") as mock_sg:
            mock_sg.SendGridAPIClient.return_value.send.side_effect = Exception("SendGrid down")
            resp = _post(app, {"caseId": "ZAD-2026-03-0001"})
        assert resp.status_code == 200
        assert resp.get_json()["emailSent"] is False

    def test_pending_client_info_not_re_advanced(self, app, mock_db, mock_form_config, mock_sendgrid):
        _, cases_col = _setup_happy_db(mock_db)
        cases_col.document.return_value.get.return_value = \
            _make_case_snap(data={**CASE_DATA, "status": "Pending Client Info"})
        resp = _post(app, {"caseId": "ZAD-2026-03-0001"})
        assert resp.status_code == 200
        cases_col.document.return_value.update.assert_not_called()


# ── Pre-fill URL builder ───────────────────────────────────────────────────────

class TestBuildPrefillUrl:
    def test_all_fields_mapped(self):
        url = main._build_prefill_url(
            form_config=FORM_CONFIG,
            first_name="Jane", last_name="Doe",
            email="jane@test.com", phone="+1999", token_id="tok-abc",
        )
        assert "entry.111=Jane" in url
        assert "entry.222=Doe" in url
        assert "entry.555=tok-abc" in url

    def test_missing_mapping_key_skipped(self):
        config = {
            "formBaseUrl": "https://forms.example.com",
            "fieldMappings": {"firstName": "entry.111"},
        }
        url = main._build_prefill_url(
            form_config=config,
            first_name="Jane", last_name="Doe",
            email="jane@test.com", phone="+1999", token_id="tok-abc",
        )
        assert "entry.111=Jane" in url
        assert "entry.222" not in url
        assert "entry.555" not in url

    def test_empty_value_skipped(self):
        url = main._build_prefill_url(
            form_config=FORM_CONFIG,
            first_name="Jane", last_name="",
            email="jane@test.com", phone="+1999", token_id="tok-abc",
        )
        assert "entry.222" not in url
