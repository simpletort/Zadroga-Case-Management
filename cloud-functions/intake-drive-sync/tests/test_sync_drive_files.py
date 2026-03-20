"""
Tests for intake-drive-sync — sync_drive_files HTTP Cloud Function.
"""
import os
import pytest
from unittest.mock import MagicMock, patch, call
from flask import Flask

import main
from tests.conftest import VALID_TOKEN_DOC, FILE_PDF, FILE_JPEG, FILE_BAD_MIME


CASE_ID  = "ZAD-2026-03-0001"
TOKEN_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


# ── Flask test client ──────────────────────────────────────────────────────────

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
def mock_gcs():
    with patch("main._get_gcs") as mock_get_gcs:
        gcs = MagicMock()
        mock_get_gcs.return_value = gcs
        yield gcs


@pytest.fixture()
def mock_drive():
    with patch("main._get_drive_service") as mock_svc:
        svc = MagicMock()
        mock_svc.return_value = svc
        yield svc


def _make_token_snap(exists=True, data=None):
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = data or VALID_TOKEN_DOC.copy()
    return snap


def _post(app, body, secret="test-secret"):
    with app.test_request_context(
        "/sync",
        method="POST",
        json=body,
        headers={"Authorization": f"Bearer {secret}"},
    ):
        from flask import request
        return main.sync_drive_files(request)


def _setup_download(mock_drive, mock_gcs, file_size=1024):
    """Make Drive download write a small file and GCS upload succeed."""
    def fake_download(drive_service, drive_file_id, dest_path):
        with open(dest_path, "wb") as f:
            f.write(b"x" * file_size)

    with patch("main._download_drive_file", side_effect=fake_download), \
         patch("main._upload_to_staging"):
        yield


# ── Auth ───────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_wrong_secret_returns_401(self, app, mock_db):
        mock_db.collection.return_value.document.return_value.get.return_value = \
            _make_token_snap()
        resp = _post(app, {"caseId": CASE_ID, "tokenId": TOKEN_ID, "files": []},
                     secret="wrong-secret")
        assert resp.status_code == 401

    def test_correct_secret_passes(self, app, mock_db):
        mock_db.collection.return_value.document.return_value.get.return_value = \
            _make_token_snap()
        resp = _post(app, {"caseId": CASE_ID, "tokenId": TOKEN_ID, "files": []})
        assert resp.status_code == 200

    def test_options_returns_204(self, app):
        with app.test_request_context("/sync", method="OPTIONS"):
            from flask import request
            resp = main.sync_drive_files(request)
        assert resp.status_code == 204

    def test_get_returns_405(self, app):
        with app.test_request_context("/sync", method="GET",
                                      headers={"Authorization": "Bearer test-secret"}):
            from flask import request
            resp = main.sync_drive_files(request)
        assert resp.status_code == 405


# ── Validation ─────────────────────────────────────────────────────────────────

class TestValidation:
    def test_missing_case_id_returns_400(self, app, mock_db):
        resp = _post(app, {"tokenId": TOKEN_ID, "files": []})
        assert resp.status_code == 400

    def test_missing_token_id_returns_400(self, app, mock_db):
        resp = _post(app, {"caseId": CASE_ID, "files": []})
        assert resp.status_code == 400

    def test_invalid_token_returns_403(self, app, mock_db):
        mock_db.collection.return_value.document.return_value.get.return_value = \
            _make_token_snap(exists=False)
        resp = _post(app, {"caseId": CASE_ID, "tokenId": TOKEN_ID,
                           "files": [FILE_PDF]})
        assert resp.status_code == 403

    def test_token_case_mismatch_returns_403(self, app, mock_db):
        mock_db.collection.return_value.document.return_value.get.return_value = \
            _make_token_snap(data={"caseId": "ZAD-2026-03-XXXX"})  # wrong case
        resp = _post(app, {"caseId": CASE_ID, "tokenId": TOKEN_ID,
                           "files": [FILE_PDF]})
        assert resp.status_code == 403

    def test_empty_files_returns_200(self, app, mock_db):
        mock_db.collection.return_value.document.return_value.get.return_value = \
            _make_token_snap()
        resp = _post(app, {"caseId": CASE_ID, "tokenId": TOKEN_ID, "files": []})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {"synced": [], "errors": []}


# ── MIME type validation ───────────────────────────────────────────────────────

class TestMimeValidation:
    def test_unsupported_mime_type_rejected(self, app, mock_db):
        mock_db.collection.return_value.document.return_value.get.return_value = \
            _make_token_snap()
        resp = _post(app, {
            "caseId": CASE_ID, "tokenId": TOKEN_ID,
            "files": [FILE_BAD_MIME],
        })
        data = resp.get_json()
        assert len(data["errors"]) == 1
        assert "Unsupported file type" in data["errors"][0]["error"]
        assert len(data["synced"]) == 0
        assert resp.status_code == 500

    def test_supported_mime_types_accepted(self):
        for mime in ("application/pdf", "image/jpeg", "image/png",
                     "application/vnd.openxmlformats-officedocument.wordprocessingml.document"):
            assert mime in main.ALLOWED_MIME_TYPES

    def test_mixed_valid_invalid_returns_207(self, app, mock_db):
        mock_db.collection.return_value.document.return_value.get.return_value = \
            _make_token_snap()

        def fake_download(drive_service, drive_file_id, dest_path):
            with open(dest_path, "wb") as f:
                f.write(b"x" * 100)

        with patch("main._download_drive_file", side_effect=fake_download), \
             patch("main._upload_to_staging"), \
             patch("main._get_drive_service", return_value=MagicMock()):
            resp = _post(app, {
                "caseId": CASE_ID, "tokenId": TOKEN_ID,
                "files": [FILE_PDF, FILE_BAD_MIME],
            })
        assert resp.status_code == 207
        data = resp.get_json()
        assert len(data["synced"]) == 1
        assert len(data["errors"]) == 1


# ── File size validation ───────────────────────────────────────────────────────

class TestFileSizeValidation:
    def test_oversized_file_rejected(self, app, mock_db):
        mock_db.collection.return_value.document.return_value.get.return_value = \
            _make_token_snap()
        oversized = 26 * 1024 * 1024  # 26 MB > 25 MB limit

        def fake_download(drive_service, drive_file_id, dest_path):
            with open(dest_path, "wb") as f:
                f.write(b"x" * oversized)

        with patch("main._download_drive_file", side_effect=fake_download), \
             patch("main._upload_to_staging"), \
             patch("main._get_drive_service", return_value=MagicMock()):
            resp = _post(app, {
                "caseId": CASE_ID, "tokenId": TOKEN_ID,
                "files": [FILE_PDF],
            })
        data = resp.get_json()
        assert len(data["errors"]) == 1
        assert "exceeds maximum" in data["errors"][0]["error"]

    def test_file_at_limit_accepted(self, app, mock_db):
        mock_db.collection.return_value.document.return_value.get.return_value = \
            _make_token_snap()
        at_limit = 25 * 1024 * 1024  # exactly 25 MB

        def fake_download(drive_service, drive_file_id, dest_path):
            with open(dest_path, "wb") as f:
                f.write(b"x" * at_limit)

        with patch("main._download_drive_file", side_effect=fake_download), \
             patch("main._upload_to_staging"), \
             patch("main._get_drive_service", return_value=MagicMock()):
            resp = _post(app, {
                "caseId": CASE_ID, "tokenId": TOKEN_ID,
                "files": [FILE_PDF],
            })
        assert resp.get_json()["synced"][0]["status"] == "pending_scan"


# ── Happy path ─────────────────────────────────────────────────────────────────

class TestHappyPath:
    def _post_with_files(self, app, mock_db, files):
        mock_db.collection.return_value.document.return_value.get.return_value = \
            _make_token_snap()

        def fake_download(drive_service, drive_file_id, dest_path):
            with open(dest_path, "wb") as f:
                f.write(b"x" * 1024)

        with patch("main._download_drive_file", side_effect=fake_download), \
             patch("main._upload_to_staging"), \
             patch("main._get_drive_service", return_value=MagicMock()):
            return _post(app, {"caseId": CASE_ID, "tokenId": TOKEN_ID, "files": files})

    def test_single_file_returns_200(self, app, mock_db):
        resp = self._post_with_files(app, mock_db, [FILE_PDF])
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["synced"]) == 1
        assert data["synced"][0]["status"] == "pending_scan"
        assert data["synced"][0]["category"] == "medical_records"
        assert data["synced"][0]["stagingPath"].startswith("staging/")

    def test_staging_path_format(self, app, mock_db):
        resp = self._post_with_files(app, mock_db, [FILE_PDF])
        staging_path = resp.get_json()["synced"][0]["stagingPath"]
        # Must be staging/{uuid}/filename — never a permanent path
        parts = staging_path.split("/")
        assert parts[0] == "staging"
        assert parts[2] == "medical_record.pdf"

    def test_unknown_category_falls_back_to_client_uploads(self, app, mock_db):
        file_unknown_cat = {**FILE_PDF, "category": "nonexistent_category"}
        resp = self._post_with_files(app, mock_db, [file_unknown_cat])
        assert resp.get_json()["synced"][0]["category"] == "client_uploads"

    def test_two_files_both_synced(self, app, mock_db):
        resp = self._post_with_files(app, mock_db, [FILE_PDF, FILE_JPEG])
        assert resp.status_code == 200
        assert len(resp.get_json()["synced"]) == 2

    def test_firestore_doc_created_per_file(self, app, mock_db):
        mock_db.collection.return_value.document.return_value.get.return_value = \
            _make_token_snap()
        doc_ref = MagicMock()

        def fake_download(drive_service, drive_file_id, dest_path):
            with open(dest_path, "wb") as f:
                f.write(b"x" * 512)

        with patch("main._download_drive_file", side_effect=fake_download), \
             patch("main._upload_to_staging"), \
             patch("main._get_drive_service", return_value=MagicMock()):
            _post(app, {"caseId": CASE_ID, "tokenId": TOKEN_ID, "files": [FILE_PDF]})

        # Firestore .set() must have been called (creates document record)
        mock_db.collection.return_value.document.return_value \
               .collection.return_value.document.return_value.set.assert_called_once()

    def test_drive_download_failure_marks_transfer_failed(self, app, mock_db):
        mock_db.collection.return_value.document.return_value.get.return_value = \
            _make_token_snap()

        with patch("main._download_drive_file", side_effect=Exception("Drive 403")), \
             patch("main._get_drive_service", return_value=MagicMock()):
            resp = _post(app, {
                "caseId": CASE_ID, "tokenId": TOKEN_ID, "files": [FILE_PDF],
            })

        assert resp.status_code == 500
        assert len(resp.get_json()["errors"]) == 1

    def test_max_file_size_constant(self):
        assert main.MAX_FILE_SIZE_BYTES == 25 * 1024 * 1024
