"""
Tests for the upload registration and status routes.
"""

import datetime
from unittest.mock import MagicMock, patch

import pytest


# ── POST /api/v1/storage/upload/register ──────────────────────────────────

class TestRegisterUpload:
    def test_register_returns_201_with_signed_url(self, client):
        mock_blob = MagicMock()
        mock_blob.generate_signed_url.return_value = "https://storage.googleapis.com/staged?token=xyz"
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob

        mock_doc_ref = MagicMock()
        mock_doc_ref.set.return_value = None

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
                    "category": "medical_records",
                    "content_type": "application/pdf",
                    "case_id": "ZAD-2024-01-0001",
                },
                headers={"Authorization": "Bearer fake-token"},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["file_id"] == "uuid-001"
        assert body["staging_path"] == "staging/uuid-001/records.pdf"
        assert "signed_url" in body
        assert body["bucket"] == "zadroga-case-files-simpletort-prod"

    def test_register_requires_auth(self, client):
        resp = client.post(
            "/api/v1/storage/upload/register",
            json={
                "file_name": "records.pdf",
                "category": "medical_records",
                "content_type": "application/pdf",
                "case_id": "ZAD-2024-01-0001",
            },
        )
        assert resp.status_code in (401, 403)  # HTTPBearer returns 403 on missing header

    def test_register_missing_content_type_returns_422(self, client):
        resp = client.post(
            "/api/v1/storage/upload/register",
            json={
                "file_name": "records.pdf",
                "category": "medical_records",
                "case_id": "ZAD-2024-01-0001",
                # content_type intentionally omitted
            },
            headers={"Authorization": "Bearer fake-token"},
        )
        assert resp.status_code == 422

    def test_register_case_scoped_without_case_id_returns_422(self, client):
        with patch("app.routes.upload.register_upload") as mock_register:
            from fastapi import HTTPException
            mock_register.side_effect = HTTPException(
                status_code=422,
                detail="case_id is required for category 'medical_records'.",
            )

            resp = client.post(
                "/api/v1/storage/upload/register",
                json={
                    "file_name": "records.pdf",
                    "category": "medical_records",
                    "content_type": "application/pdf",
                    # case_id omitted
                },
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 422
        assert "case_id" in resp.json()["detail"]

    def test_register_non_case_scoped_category_succeeds_without_case_id(self, client):
        with patch("app.routes.upload.register_upload") as mock_register:
            mock_register.return_value = {
                "file_id": "uuid-002",
                "staging_path": "staging/uuid-002/intake.pdf",
                "signed_url": "https://storage.googleapis.com/staged?token=abc",
                "expires_at": datetime.datetime(2024, 1, 15, 13, 0, 0),
                "bucket": "zadroga-case-files-simpletort-prod",
            }

            resp = client.post(
                "/api/v1/storage/upload/register",
                json={
                    "file_name": "intake.pdf",
                    "category": "temp_lead_attachments",
                    "content_type": "application/pdf",
                },
                headers={"Authorization": "Bearer fake-token"},
            )

        assert resp.status_code == 201
        assert resp.json()["file_id"] == "uuid-002"


# ── GET /api/v1/storage/upload/{fileId}/status ────────────────────────────

class TestUploadStatus:
    def test_status_returns_pending_for_new_upload(self, client):
        with patch("app.routes.upload.get_upload_status") as mock_status:
            from app.models.storage import DocumentCategory, ScanStatus, UploadStatusResponse
            mock_status.return_value = UploadStatusResponse(
                file_id="uuid-001",
                case_id="ZAD-2024-01-0001",
                file_name="records.pdf",
                category=DocumentCategory.medical_records,
                scan_status=ScanStatus.pending,
                staging_path="staging/uuid-001/records.pdf",
                registered_at=datetime.datetime(2024, 1, 15, 12, 0, 0),
            )

            resp = client.get(
                "/api/v1/storage/upload/uuid-001/status",
                headers={"Authorization": "Bearer fake-token"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["scan_status"] == "pending"
        assert body["file_id"] == "uuid-001"
        assert body["is_quarantined"] is False
        assert body["final_path"] is None

    def test_status_clean_includes_final_path(self, client):
        with patch("app.routes.upload.get_upload_status") as mock_status:
            from app.models.storage import DocumentCategory, ScanStatus, UploadStatusResponse
            mock_status.return_value = UploadStatusResponse(
                file_id="uuid-002",
                case_id="ZAD-2024-01-0001",
                file_name="records.pdf",
                category=DocumentCategory.medical_records,
                scan_status=ScanStatus.clean,
                staging_path="staging/uuid-002/records.pdf",
                final_path="ZAD-2024-01-0001/medical-records/records.pdf",
                registered_at=datetime.datetime(2024, 1, 15, 12, 0, 0),
                scan_completed_at=datetime.datetime(2024, 1, 15, 12, 0, 30),
            )

            resp = client.get(
                "/api/v1/storage/upload/uuid-002/status",
                headers={"Authorization": "Bearer fake-token"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["scan_status"] == "clean"
        assert body["final_path"] == "ZAD-2024-01-0001/medical-records/records.pdf"

    def test_status_infected_includes_quarantine_info(self, client):
        with patch("app.routes.upload.get_upload_status") as mock_status:
            from app.models.storage import DocumentCategory, ScanStatus, UploadStatusResponse
            mock_status.return_value = UploadStatusResponse(
                file_id="uuid-003",
                case_id="ZAD-2024-01-0001",
                file_name="malware.pdf",
                category=DocumentCategory.medical_records,
                scan_status=ScanStatus.infected,
                staging_path="staging/uuid-003/malware.pdf",
                is_quarantined=True,
                quarantine_path="quarantine/20240115T120045/uuid-003/malware.pdf",
                registered_at=datetime.datetime(2024, 1, 15, 12, 0, 0),
                scan_completed_at=datetime.datetime(2024, 1, 15, 12, 0, 45),
            )

            resp = client.get(
                "/api/v1/storage/upload/uuid-003/status",
                headers={"Authorization": "Bearer fake-token"},
            )

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

            resp = client.get(
                "/api/v1/storage/upload/bad-id/status",
                headers={"Authorization": "Bearer fake-token"},
            )

        assert resp.status_code == 404

    def test_status_requires_auth(self, client):
        resp = client.get("/api/v1/storage/upload/uuid-001/status")
        assert resp.status_code in (401, 403)  # HTTPBearer returns 403 on missing header


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
