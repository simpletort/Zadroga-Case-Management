"""
Tests for the signed URL route.
"""

import datetime
from unittest.mock import MagicMock, patch

import pytest


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
                    "case_id": "ZAD-2024-01-0001",
                    "folder_path": "legal-forms",
                    "file_name": "intake.pdf",
                    "action": "read",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "read"
        assert "signed_url" in body
        assert "blob_path" in body
        assert body["blob_path"] == "ZAD-2024-01-0001/legal-forms/intake.pdf"

    def test_write_without_content_type_returns_422(self, client):
        resp = client.get(
            "/api/v1/storage/signed-url",
            params={
                "case_id": "ZAD-2024-01-0001",
                "folder_path": "medical-records",
                "file_name": "records.pdf",
                "action": "write",
            },
        )
        assert resp.status_code == 422
        assert "content_type" in resp.json()["detail"]

    def test_path_traversal_returns_422(self, client):
        resp = client.get(
            "/api/v1/storage/signed-url",
            params={
                "case_id": "ZAD-2024-01-0001",
                "folder_path": "../other-case/secrets",
                "file_name": "records.pdf",
                "action": "read",
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
                    "case_id": "ZAD-2024-01-0001",
                    "folder_path": "medical-records/2024",
                    "file_name": "records.pdf",
                    "action": "write",
                    "content_type": "application/pdf",
                },
            )

        call_kwargs = mock_blob.generate_signed_url.call_args.kwargs
        assert call_kwargs["expiration"] == datetime.timedelta(minutes=15)
        assert call_kwargs["method"] == "PUT"
