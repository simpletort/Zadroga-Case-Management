"""
Tests for the upload registration and status routes.
"""

import datetime
from unittest.mock import MagicMock, patch

import pytest


# ── POST /api/v1/storage/upload/register ──────────────────────────────────

class TestRegisterUpload:
    def test_register_returns_201_with_signed_url(self, client):
        with patch("app.routes.upload.register_upload") as mock_register:
            mock_register.return_value = {
                "file_id": "uuid-001",
                "staging_path": "staging/uuid-001/records.pdf",
                "signed_url": "https://storage.googleapis.com/staged?token=xyz",
                "expires_at": datetime.datetime(2024, 1, 15, 13, 0, 0),
                "bucket": "zadroga-case-files-simpletort-prod",
            }

            resp = client.post(
                "/api/v1/storage/upload/register",
                json={
                    "file_name": "records.pdf",
                    "folder_path": "medical-records/2024",
                    "content_type": "application/pdf",
                    "case_id": "ZAD-2024-01-0001",
                },
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["file_id"] == "uuid-001"
        assert body["staging_path"] == "staging/uuid-001/records.pdf"
        assert "signed_url" in body
        assert body["bucket"] == "zadroga-case-files-simpletort-prod"

    def test_register_missing_content_type_returns_422(self, client):
        resp = client.post(
            "/api/v1/storage/upload/register",
            json={
                "file_name": "records.pdf",
                "folder_path": "medical-records",
                "case_id": "ZAD-2024-01-0001",
                # content_type intentionally omitted
            },
        )
        assert resp.status_code == 422

    def test_register_missing_case_id_returns_422(self, client):
        resp = client.post(
            "/api/v1/storage/upload/register",
            json={
                "file_name": "records.pdf",
                "folder_path": "medical-records",
                "content_type": "application/pdf",
                # case_id intentionally omitted — now always required
            },
        )
        assert resp.status_code == 422

    def test_register_missing_folder_path_returns_422(self, client):
        resp = client.post(
            "/api/v1/storage/upload/register",
            json={
                "file_name": "records.pdf",
                "content_type": "application/pdf",
                "case_id": "ZAD-2024-01-0001",
                # folder_path intentionally omitted
            },
        )
        assert resp.status_code == 422

    def test_register_path_traversal_returns_422(self, client):
        with patch("app.routes.upload.register_upload") as mock_register:
            from fastapi import HTTPException
            mock_register.side_effect = HTTPException(
                status_code=422,
                detail="Invalid folder_path: must not escape the case directory.",
            )

            resp = client.post(
                "/api/v1/storage/upload/register",
                json={
                    "file_name": "records.pdf",
                    "folder_path": "../other-case/secrets",
                    "content_type": "application/pdf",
                    "case_id": "ZAD-2024-01-0001",
                },
            )
        assert resp.status_code == 422

    def test_register_passes_folder_path_to_service(self, client):
        with patch("app.routes.upload.register_upload") as mock_register:
            mock_register.return_value = {
                "file_id": "uuid-003",
                "staging_path": "staging/uuid-003/report.pdf",
                "signed_url": "https://storage.googleapis.com/staged?token=abc",
                "expires_at": datetime.datetime(2024, 1, 15, 13, 0, 0),
                "bucket": "zadroga-case-files-simpletort-prod",
            }

            client.post(
                "/api/v1/storage/upload/register",
                json={
                    "file_name": "report.pdf",
                    "folder_path": "legal-forms/2024/contracts",
                    "content_type": "application/pdf",
                    "case_id": "ZAD-2024-01-0001",
                },
            )

        mock_register.assert_called_once()
        call_kwargs = mock_register.call_args.kwargs
        assert call_kwargs["folder_path"] == "legal-forms/2024/contracts"
        assert call_kwargs["case_id"] == "ZAD-2024-01-0001"


# ── GET /api/v1/storage/upload/{fileId}/status ────────────────────────────

class TestUploadStatus:
    def test_status_returns_pending_for_new_upload(self, client):
        with patch("app.routes.upload.get_upload_status") as mock_status:
            from app.models.storage import ScanStatus, UploadStatusResponse
            mock_status.return_value = UploadStatusResponse(
                file_id="uuid-001",
                case_id="ZAD-2024-01-0001",
                file_name="records.pdf",
                folder_path="medical-records/2024",
                scan_status=ScanStatus.pending,
                staging_path="staging/uuid-001/records.pdf",
                registered_at=datetime.datetime(2024, 1, 15, 12, 0, 0),
            )

            resp = client.get("/api/v1/storage/upload/uuid-001/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["scan_status"] == "pending"
        assert body["file_id"] == "uuid-001"
        assert body["folder_path"] == "medical-records/2024"
        assert body["is_quarantined"] is False
        assert body["final_path"] is None

    def test_status_clean_includes_final_path(self, client):
        with patch("app.routes.upload.get_upload_status") as mock_status:
            from app.models.storage import ScanStatus, UploadStatusResponse
            mock_status.return_value = UploadStatusResponse(
                file_id="uuid-002",
                case_id="ZAD-2024-01-0001",
                file_name="records.pdf",
                folder_path="medical-records",
                scan_status=ScanStatus.clean,
                staging_path="staging/uuid-002/records.pdf",
                final_path="ZAD-2024-01-0001/medical-records/records.pdf",
                registered_at=datetime.datetime(2024, 1, 15, 12, 0, 0),
                scan_completed_at=datetime.datetime(2024, 1, 15, 12, 0, 30),
            )

            resp = client.get("/api/v1/storage/upload/uuid-002/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["scan_status"] == "clean"
        assert body["final_path"] == "ZAD-2024-01-0001/medical-records/records.pdf"

    def test_status_infected_includes_quarantine_info(self, client):
        with patch("app.routes.upload.get_upload_status") as mock_status:
            from app.models.storage import ScanStatus, UploadStatusResponse
            mock_status.return_value = UploadStatusResponse(
                file_id="uuid-003",
                case_id="ZAD-2024-01-0001",
                file_name="malware.pdf",
                folder_path="medical-records",
                scan_status=ScanStatus.infected,
                staging_path="staging/uuid-003/malware.pdf",
                is_quarantined=True,
                quarantine_path="quarantine/20240115T120045/uuid-003/malware.pdf",
                registered_at=datetime.datetime(2024, 1, 15, 12, 0, 0),
                scan_completed_at=datetime.datetime(2024, 1, 15, 12, 0, 45),
            )

            resp = client.get("/api/v1/storage/upload/uuid-003/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["scan_status"] == "infected"
        assert body["is_quarantined"] is True
        assert "quarantine" in body["quarantine_path"]
        assert body["final_path"] is None

    def test_status_not_found_returns_404(self, client):
        with patch("app.routes.upload.get_upload_status") as mock_status:
            from fastapi import HTTPException
            mock_status.side_effect = HTTPException(status_code=404, detail="Upload 'bad-id' not found.")

            resp = client.get("/api/v1/storage/upload/bad-id/status")

        assert resp.status_code == 404


# ── upload_service unit tests ─────────────────────────────────────────────

class TestUploadServiceStagingPath:
    def test_staging_path_format(self):
        from app.services.upload_service import _staging_path
        path = _staging_path("uuid-abc", "records.pdf")
        assert path == "staging/uuid-abc/records.pdf"

    def test_staging_path_preserves_filename(self):
        from app.services.upload_service import _staging_path
        path = _staging_path("uuid-xyz", "2024 MRI Report.pdf")
        assert path.startswith("staging/uuid-xyz/")
        assert path.endswith("2024 MRI Report.pdf")


class TestRegisterUploadService:
    def _mock_db(self):
        mock_db = MagicMock()
        mock_db.collection.return_value.document.return_value.set.return_value = None
        mock_db.collection.return_value.document.return_value \
            .collection.return_value.document.return_value.set.return_value = None
        return mock_db

    def test_final_path_uses_case_id_and_folder_path(self):
        from app.services.upload_service import register_upload

        mock_db = self._mock_db()

        with patch("app.services.upload_service.get_firestore_client", return_value=mock_db), \
             patch("app.services.upload_service.generate_signed_url") as mock_url:
            mock_url.return_value = ("https://storage.googleapis.com/signed", datetime.datetime(2024, 1, 15, 13, 0))

            result = register_upload(
                file_name="report.pdf",
                folder_path="legal-forms/2024",
                content_type="application/pdf",
                uploaded_by="uid-001",
                case_id="ZAD-2024-01-0001",
            )

        # final_path stored in Firestore should be case_id/folder_path/file_name
        file_uploads_call = mock_db.collection.return_value.document.return_value.set.call_args[0][0]
        assert file_uploads_call["finalPath"] == "ZAD-2024-01-0001/legal-forms/2024/report.pdf"
        assert file_uploads_call["folderPath"] == "legal-forms/2024"
        assert file_uploads_call["caseId"] == "ZAD-2024-01-0001"

    def test_path_traversal_raises_422(self):
        from app.services.upload_service import register_upload
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            register_upload(
                file_name="report.pdf",
                folder_path="../other-case",
                content_type="application/pdf",
                uploaded_by="uid-001",
                case_id="ZAD-2024-01-0001",
            )
        assert exc_info.value.status_code == 422

    def test_absolute_folder_path_raises_422(self):
        from app.services.upload_service import register_upload
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            register_upload(
                file_name="report.pdf",
                folder_path="/absolute/path",
                content_type="application/pdf",
                uploaded_by="uid-001",
                case_id="ZAD-2024-01-0001",
            )
        assert exc_info.value.status_code == 422

    def test_nested_folder_path_builds_correct_final_path(self):
        from app.services.upload_service import register_upload

        mock_db = self._mock_db()

        with patch("app.services.upload_service.get_firestore_client", return_value=mock_db), \
             patch("app.services.upload_service.generate_signed_url") as mock_url:
            mock_url.return_value = ("https://storage.googleapis.com/signed", datetime.datetime(2024, 1, 15, 13, 0))

            register_upload(
                file_name="contract.pdf",
                folder_path="legal-forms/2024/contracts",
                content_type="application/pdf",
                uploaded_by="uid-001",
                case_id="ZAD-TEST-01",
            )

        written = mock_db.collection.return_value.document.return_value.set.call_args[0][0]
        assert written["finalPath"] == "ZAD-TEST-01/legal-forms/2024/contracts/contract.pdf"
