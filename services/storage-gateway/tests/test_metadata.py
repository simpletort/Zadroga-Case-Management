"""
Tests for the metadata route and metadata service.
"""

from unittest.mock import MagicMock, patch

import pytest


# ── GET /api/v1/storage/{fileId}/metadata ─────────────────────────────────

class TestMetadataRoute:
    def _mock_snap(self, exists=True, data=None):
        snap = MagicMock()
        snap.exists = exists
        snap.to_dict.return_value = data or {
            "fileName": "records_2024.pdf",
            "category": "medical records",
            "gcsPath": "ZAD-2024-01-0001/medical-records/records_2024.pdf",
            "mimeType": "application/pdf",
            "sizeBytes": 204800,
            "uploadedAt": None,
            "processingStatus": "Completed",
            "verificationStatus": "AI Verified",
            "documentAiResults": None,
            "medicalAiResults": None,
        }
        return snap

    def test_returns_metadata_for_existing_file(self, client):
        snap = self._mock_snap()

        with patch("app.services.metadata_service.get_firestore_client") as mock_db:
            mock_db.return_value \
                .collection.return_value \
                .document.return_value \
                .collection.return_value \
                .document.return_value \
                .get.return_value = snap

            resp = client.get(
                "/api/v1/storage/doc-abc123/metadata",
                params={"case_id": "ZAD-2024-01-0001"},
                            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["file_id"] == "doc-abc123"
        assert body["case_id"] == "ZAD-2024-01-0001"
        assert body["file_name"] == "records_2024.pdf"
        assert body["category"] == "medical records"
        assert body["processing_status"] == "Completed"
        assert body["verification_status"] == "AI Verified"

    def test_returns_404_for_missing_file(self, client):
        snap = self._mock_snap(exists=False)

        with patch("app.services.metadata_service.get_firestore_client") as mock_db:
            mock_db.return_value \
                .collection.return_value \
                .document.return_value \
                .collection.return_value \
                .document.return_value \
                .get.return_value = snap

            resp = client.get(
                "/api/v1/storage/nonexistent-id/metadata",
                params={"case_id": "ZAD-2024-01-0001"},
                            )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_missing_case_id_query_param_returns_422(self, client):
        resp = client.get(
            "/api/v1/storage/doc-abc123/metadata",
            # case_id intentionally omitted
                    )
        assert resp.status_code == 422


# ── metadata_service unit tests ────────────────────────────────────────────

class TestCreateFileMetadata:
    def test_creates_document_with_correct_fields(self):
        from app.services.metadata_service import create_file_metadata
        from app.models.storage import DocumentCategory

        mock_ref = MagicMock()
        with patch("app.services.metadata_service.get_firestore_client") as mock_db:
            mock_db.return_value \
                .collection.return_value \
                .document.return_value \
                .collection.return_value \
                .document.return_value = mock_ref

            create_file_metadata(
                case_id="ZAD-2024-01-0001",
                file_id="doc-new-001",
                file_name="medical_report.pdf",
                category=DocumentCategory.medical_records,
                gcs_path="ZAD-2024-01-0001/medical-records/medical_report.pdf",
                uploaded_by="uid-admin-001",
                mime_type="application/pdf",
                size_bytes=512000,
            )

        mock_ref.set.assert_called_once()
        written = mock_ref.set.call_args[0][0]
        assert written["fileName"] == "medical_report.pdf"
        assert written["category"] == "medical records"
        assert written["processingStatus"] == "Pending"
        assert written["verificationStatus"] == "Unverified"
