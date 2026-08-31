"""
Tests for the case-less "system upload" routes — used by callers (e.g.
lead-intake's bulk lead import) that need a file virus-scanned before any
case exists. Same staging/scan pipeline as /upload/register, but no case_id
and no cases/{caseId}/documents/{fileId} write.
"""

import datetime
from unittest.mock import MagicMock, patch

import pytest


# ── POST /api/v1/storage/system-upload/register ────────────────────────────

class TestRegisterSystemUpload:
    def test_register_returns_201_with_signed_url(self, client):
        with patch("app.routes.system_upload.register_system_upload") as mock_register:
            mock_register.return_value = {
                "file_id": "uuid-sys-001",
                "staging_path": "staging/uuid-sys-001/leads.xlsx",
                "signed_url": "https://storage.googleapis.com/staged?token=xyz",
                "expires_at": datetime.datetime(2024, 1, 15, 13, 0, 0),
                "bucket": "zadroga-case-files-simpletort-prod",
            }

            resp = client.post(
                "/api/v1/storage/system-upload/register",
                json={
                    "file_name": "leads.xlsx",
                    "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "context": "bulk_lead_import",
                },
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["file_id"] == "uuid-sys-001"
        assert body["staging_path"] == "staging/uuid-sys-001/leads.xlsx"
        assert "signed_url" in body

    def test_register_does_not_require_case_id(self, client):
        """The whole point of this endpoint — no case_id field exists on the request model."""
        with patch("app.routes.system_upload.register_system_upload") as mock_register:
            mock_register.return_value = {
                "file_id": "uuid-sys-002",
                "staging_path": "staging/uuid-sys-002/leads.xlsx",
                "signed_url": "https://storage.googleapis.com/signed",
                "expires_at": datetime.datetime(2024, 1, 15, 13, 0, 0),
                "bucket": "zadroga-case-files-test",
            }
            resp = client.post(
                "/api/v1/storage/system-upload/register",
                json={
                    "file_name": "leads.xlsx",
                    "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                },
            )
        assert resp.status_code == 201

    def test_register_missing_content_type_returns_422(self, client):
        resp = client.post(
            "/api/v1/storage/system-upload/register",
            json={"file_name": "leads.xlsx"},
        )
        assert resp.status_code == 422

    def test_register_defaults_context_to_bulk_lead_import(self, client):
        with patch("app.routes.system_upload.register_system_upload") as mock_register:
            mock_register.return_value = {
                "file_id": "uuid-sys-003",
                "staging_path": "staging/uuid-sys-003/leads.xlsx",
                "signed_url": "https://storage.googleapis.com/signed",
                "expires_at": datetime.datetime(2024, 1, 15, 13, 0, 0),
                "bucket": "zadroga-case-files-test",
            }
            client.post(
                "/api/v1/storage/system-upload/register",
                json={
                    "file_name": "leads.xlsx",
                    "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                },
            )
        call_kwargs = mock_register.call_args.kwargs
        assert call_kwargs["context"] == "bulk_lead_import"


# ── GET /api/v1/storage/system-upload/{fileId}/read-url ────────────────────

class TestSystemUploadReadUrl:
    def test_read_url_returns_signed_url_when_clean(self, client):
        with patch("app.routes.system_upload.get_system_file_read_url") as mock_read:
            mock_read.return_value = {
                "signed_url": "https://storage.googleapis.com/read?token=abc",
                "blob_path": "system-uploads/bulk_lead_import/uuid-sys-001/leads.xlsx",
                "bucket": "zadroga-case-files-test",
                "expires_at": datetime.datetime(2024, 1, 15, 13, 0, 0),
            }
            resp = client.get("/api/v1/storage/system-upload/uuid-sys-001/read-url")

        assert resp.status_code == 200
        body = resp.json()
        assert body["blob_path"] == "system-uploads/bulk_lead_import/uuid-sys-001/leads.xlsx"

    def test_read_url_409_when_not_clean(self, client):
        with patch("app.routes.system_upload.get_system_file_read_url") as mock_read:
            from fastapi import HTTPException
            mock_read.side_effect = HTTPException(
                status_code=409, detail="File 'uuid-sys-001' is not ready for read — scanStatus is 'scanning'.",
            )
            resp = client.get("/api/v1/storage/system-upload/uuid-sys-001/read-url")
        assert resp.status_code == 409

    def test_read_url_404_when_missing(self, client):
        with patch("app.routes.system_upload.get_system_file_read_url") as mock_read:
            from fastapi import HTTPException
            mock_read.side_effect = HTTPException(status_code=404, detail="Upload 'bad-id' not found.")
            resp = client.get("/api/v1/storage/system-upload/bad-id/read-url")
        assert resp.status_code == 404


# ── upload_service unit tests ───────────────────────────────────────────────

class TestRegisterSystemUploadService:
    def _mock_db(self):
        mock_db = MagicMock()
        mock_db.collection.return_value.document.return_value.set.return_value = None
        return mock_db

    def test_writes_file_uploads_with_null_case_id(self):
        from app.services.upload_service import register_system_upload

        mock_db = self._mock_db()
        with patch("app.services.upload_service.get_firestore_client", return_value=mock_db), \
             patch("app.services.upload_service.generate_signed_url") as mock_url:
            mock_url.return_value = ("https://storage.googleapis.com/signed", datetime.datetime(2024, 1, 15, 13, 0), False)

            result = register_system_upload(
                file_name="leads.xlsx",
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                uploaded_by="uid-001",
                context="bulk_lead_import",
            )

        written = mock_db.collection.return_value.document.return_value.set.call_args[0][0]
        assert written["caseId"] is None
        assert written["context"] == "bulk_lead_import"
        assert written["finalPath"] == "system-uploads/bulk_lead_import/{}/leads.xlsx".format(result["file_id"])
        # Only ONE Firestore write happens (file_uploads) — no cases/{caseId}/documents write.
        assert mock_db.collection.call_count == 1
        assert mock_db.collection.call_args[0][0] == "file_uploads"

    def test_staging_path_reuses_shared_prefix_scheme(self):
        """The virus-scanner Cloud Function only keys off staging/{fileId}/{fileName} —
        it must not need to know this is a system (case-less) upload."""
        from app.services.upload_service import register_system_upload

        mock_db = self._mock_db()
        with patch("app.services.upload_service.get_firestore_client", return_value=mock_db), \
             patch("app.services.upload_service.generate_signed_url") as mock_url:
            mock_url.return_value = ("https://storage.googleapis.com/signed", datetime.datetime(2024, 1, 15, 13, 0), False)

            result = register_system_upload(
                file_name="leads.xlsx",
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                uploaded_by="uid-001",
                context="bulk_lead_import",
            )

        assert result["staging_path"] == "staging/{}/leads.xlsx".format(result["file_id"])

    def test_invalid_extension_raises_415(self):
        from app.services.upload_service import register_system_upload
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            register_system_upload(
                file_name="malware.exe",
                content_type="application/octet-stream",
                uploaded_by="uid-001",
                context="bulk_lead_import",
            )
        assert exc_info.value.status_code == 415

    def test_invalid_context_raises_422(self):
        from app.services.upload_service import register_system_upload
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            register_system_upload(
                file_name="leads.xlsx",
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                uploaded_by="uid-001",
                context="../escape",
            )
        assert exc_info.value.status_code == 422


class TestGetSystemFileReadUrlService:
    def test_returns_signed_url_when_clean(self):
        from app.services.upload_service import get_system_file_read_url

        mock_snap = MagicMock()
        mock_snap.exists = True
        mock_snap.to_dict.return_value = {
            "scanStatus": "clean",
            "finalPath": "system-uploads/bulk_lead_import/uuid-sys-001/leads.xlsx",
        }
        mock_db = MagicMock()
        mock_db.collection.return_value.document.return_value.get.return_value = mock_snap

        with patch("app.services.upload_service.get_firestore_client", return_value=mock_db), \
             patch("app.services.upload_service.generate_signed_url") as mock_url:
            mock_url.return_value = ("https://storage.googleapis.com/read", datetime.datetime(2024, 1, 15, 13, 0), False)

            result = get_system_file_read_url("uuid-sys-001")

        assert result["blob_path"] == "system-uploads/bulk_lead_import/uuid-sys-001/leads.xlsx"
        assert result["signed_url"] == "https://storage.googleapis.com/read"

    def test_raises_409_when_not_clean(self):
        from app.services.upload_service import get_system_file_read_url
        from fastapi import HTTPException

        mock_snap = MagicMock()
        mock_snap.exists = True
        mock_snap.to_dict.return_value = {"scanStatus": "scanning", "finalPath": None}
        mock_db = MagicMock()
        mock_db.collection.return_value.document.return_value.get.return_value = mock_snap

        with patch("app.services.upload_service.get_firestore_client", return_value=mock_db):
            with pytest.raises(HTTPException) as exc_info:
                get_system_file_read_url("uuid-sys-001")
        assert exc_info.value.status_code == 409

    def test_raises_404_when_missing(self):
        from app.services.upload_service import get_system_file_read_url
        from fastapi import HTTPException

        mock_snap = MagicMock()
        mock_snap.exists = False
        mock_db = MagicMock()
        mock_db.collection.return_value.document.return_value.get.return_value = mock_snap

        with patch("app.services.upload_service.get_firestore_client", return_value=mock_db):
            with pytest.raises(HTTPException) as exc_info:
                get_system_file_read_url("bad-id")
        assert exc_info.value.status_code == 404


class TestUploadStatusToleratesNullCaseId:
    def test_get_upload_status_handles_null_case_id(self):
        """A system upload's file_uploads doc has caseId=None — the shared
        status endpoint (reused for both flows) must not choke on that."""
        from app.services.upload_service import get_upload_status

        mock_snap = MagicMock()
        mock_snap.exists = True
        mock_snap.to_dict.return_value = {
            "caseId": None,
            "fileName": "leads.xlsx",
            "folderPath": "",
            "scanStatus": "pending",
            "stagingPath": "staging/uuid-sys-001/leads.xlsx",
            "isQuarantined": False,
            "registeredAt": datetime.datetime(2024, 1, 15, 12, 0, 0),
        }
        mock_db = MagicMock()
        mock_db.collection.return_value.document.return_value.get.return_value = mock_snap

        with patch("app.services.upload_service.get_firestore_client", return_value=mock_db):
            result = get_upload_status("uuid-sys-001")

        assert result.case_id == ""
