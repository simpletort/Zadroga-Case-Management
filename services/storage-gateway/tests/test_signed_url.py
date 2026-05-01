"""
Tests for the signed URL route and GCS path construction logic.
"""

import datetime
from unittest.mock import MagicMock, patch

import pytest


# ── build_blob_path ────────────────────────────────────────────────────────

class TestBuildBlobPath:
    def test_case_scoped_category_builds_correct_path(self):
        from app.services.gcs_service import build_blob_path
        from app.models.storage import DocumentCategory

        path = build_blob_path(DocumentCategory.medical_records, "report.pdf", case_id="ZAD-2024-01-0001")
        assert path == "ZAD-2024-01-0001/medical-records/report.pdf"

    def test_temp_lead_attachments_has_no_case_id_prefix(self):
        from app.services.gcs_service import build_blob_path
        from app.models.storage import DocumentCategory

        path = build_blob_path(DocumentCategory.temp_lead_attachments, "intake.pdf")
        assert path == "temp-lead-attachments/intake.pdf"

    def test_all_case_scoped_categories(self):
        from app.services.gcs_service import build_blob_path
        from app.models.storage import DocumentCategory

        scoped = [
            DocumentCategory.medical_records,
            DocumentCategory.proof_of_presence,
            DocumentCategory.id_documents,
            DocumentCategory.legal_forms,
            DocumentCategory.vcf_documents,
            DocumentCategory.settlement_docs,
        ]
        for cat in scoped:
            path = build_blob_path(cat, "file.pdf", case_id="ZAD-2024-01-0001")
            assert path.startswith("ZAD-2024-01-0001/")
            assert path.endswith("/file.pdf")

    def test_missing_case_id_raises_value_error(self):
        from app.services.gcs_service import build_blob_path
        from app.models.storage import DocumentCategory

        with pytest.raises(ValueError, match="requires a caseId"):
            build_blob_path(DocumentCategory.medical_records, "record.pdf")

    def test_client_uploads_no_case_id_needed(self):
        from app.services.gcs_service import build_blob_path
        from app.models.storage import DocumentCategory

        path = build_blob_path(DocumentCategory.client_uploads, "upload.jpg")
        assert path == "client-uploads/upload.jpg"


# ── GET /api/v1/storage/signed-url ────────────────────────────────────────

class TestSignedUrlRoute:
    def test_read_signed_url_returns_200(self, client):
        mock_blob = MagicMock()
        mock_blob.generate_signed_url.return_value = "https://storage.googleapis.com/signed?token=abc"

        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob

        with patch("app.routes.signed_url.get_gcs_client") as mock_gcs:
            mock_gcs.return_value.bucket.return_value = mock_bucket

            resp = client.get(
                "/api/v1/storage/signed-url",
                params={
                    "category": "temp_lead_attachments",
                    "file_name": "intake.pdf",
                    "action": "read",
                },
                            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "read"
        assert "signed_url" in body
        assert "blob_path" in body
        assert body["blob_path"] == "temp-lead-attachments/intake.pdf"

    def test_write_without_content_type_returns_422(self, client):
        resp = client.get(
            "/api/v1/storage/signed-url",
            params={
                "category": "medical_records",
                "file_name": "records.pdf",
                "action": "write",
                "case_id": "ZAD-2024-01-0001",
            },
                    )
        assert resp.status_code == 422
        assert "content_type" in resp.json()["detail"]

    def test_case_scoped_category_without_case_id_returns_422(self, client):
        with patch("app.routes.signed_url.get_gcs_client"):
            resp = client.get(
                "/api/v1/storage/signed-url",
                params={
                    "category": "medical_records",
                    "file_name": "records.pdf",
                    "action": "read",
                    # case_id intentionally omitted
                },
                            )
        assert resp.status_code == 422

    def test_write_url_uses_15_min_expiry(self, client):
        mock_blob = MagicMock()
        mock_blob.generate_signed_url.return_value = "https://storage.googleapis.com/signed"

        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob

        with patch("app.routes.signed_url.get_gcs_client") as mock_gcs:
            mock_gcs.return_value.bucket.return_value = mock_bucket

            client.get(
                "/api/v1/storage/signed-url",
                params={
                    "category": "medical_records",
                    "file_name": "records.pdf",
                    "action": "write",
                    "case_id": "ZAD-2024-01-0001",
                    "content_type": "application/pdf",
                },
                            )

        call_kwargs = mock_blob.generate_signed_url.call_args.kwargs
        assert call_kwargs["expiration"] == datetime.timedelta(minutes=15)
        assert call_kwargs["method"] == "PUT"
