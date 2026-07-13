"""
Tests for the signed URL route.
"""

import datetime
from unittest.mock import MagicMock, call, patch

import pytest

from app.services.gcs_service import MAX_SIGNED_URL_EXPIRY_MINUTES


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

    def test_inline_true_sets_response_disposition(self, client):
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
                    "inline": "true",
                },
            )

        assert resp.status_code == 200
        call_kwargs = mock_blob.generate_signed_url.call_args.kwargs
        assert call_kwargs.get("response_disposition") == "inline"

    def test_inline_false_by_default_no_response_disposition(self, client):
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
        call_kwargs = mock_blob.generate_signed_url.call_args.kwargs
        assert "response_disposition" not in call_kwargs

    # ── TTL cap tests ─────────────────────────────────────────────────────────

    def test_ttl_capped_when_caller_requests_over_15_min(self, client):
        """Caller-supplied TTL > 15 min must be silently capped to 15 min."""
        mock_blob = MagicMock()
        mock_blob.generate_signed_url.return_value = "https://storage.googleapis.com/signed"
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
                    "expiry_minutes": 60,
                },
            )

        assert resp.status_code == 200
        call_kwargs = mock_blob.generate_signed_url.call_args.kwargs
        assert call_kwargs["expiration"] == datetime.timedelta(minutes=MAX_SIGNED_URL_EXPIRY_MINUTES)

    def test_ttl_override_audit_event_fired_when_capped(self, client, mock_cloud_logger):
        """Capping a TTL must emit a signed_url_ttl_override audit event."""
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
                    "folder_path": "legal-forms",
                    "file_name": "intake.pdf",
                    "action": "read",
                    "expiry_minutes": 120,
                },
            )

        logged_actions = [
            c.args[0]["action"]
            for c in mock_cloud_logger.log_struct.call_args_list
        ]
        assert "signed_url_ttl_override" in logged_actions

    def test_no_ttl_override_audit_event_when_within_cap(self, client, mock_cloud_logger):
        """No override audit event when the requested TTL is within the cap."""
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
                    "folder_path": "legal-forms",
                    "file_name": "intake.pdf",
                    "action": "read",
                    "expiry_minutes": 10,
                },
            )

        logged_actions = [
            c.args[0]["action"]
            for c in mock_cloud_logger.log_struct.call_args_list
        ]
        assert "signed_url_ttl_override" not in logged_actions

    def test_default_read_ttl_capped_without_explicit_param(self, client, mock_cloud_logger):
        """Default read TTL (60 min from config) is also capped and fires the override event."""
        mock_blob = MagicMock()
        mock_blob.generate_signed_url.return_value = "https://storage.googleapis.com/signed"
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
        call_kwargs = mock_blob.generate_signed_url.call_args.kwargs
        assert call_kwargs["expiration"] == datetime.timedelta(minutes=MAX_SIGNED_URL_EXPIRY_MINUTES)
        logged_actions = [
            c.args[0]["action"]
            for c in mock_cloud_logger.log_struct.call_args_list
        ]
        assert "signed_url_ttl_override" in logged_actions
