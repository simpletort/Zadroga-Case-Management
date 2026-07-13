"""
Tests for HIPAA-compliant audit logging.

Coverage:
  - get_client_ip()        — IP extraction from various request shapes
  - log_audit_event()      — dual-write to Cloud Logging + Firestore,
                             failure isolation, field correctness
  - Route wiring           — every audited endpoint calls log_audit_event
                             with the correct AuditAction value
"""

import datetime
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mock_request(xff=None, client_host="10.0.0.1", user_agent="TestAgent/1.0"):
    """Build a minimal mock FastAPI Request for unit testing."""
    req = MagicMock()
    hdrs = {}
    if xff is not None:
        hdrs["x-forwarded-for"] = xff
    if user_agent is not None:
        hdrs["user-agent"] = user_agent
    req.headers = hdrs
    req.client = MagicMock()
    req.client.host = client_host
    return req


def _make_file_metadata_response(**overrides):
    from app.models.storage import (
        DocumentCategory,
        FileMetadataResponse,
        ProcessingStatus,
        ScanStatus,
        VerificationStatus,
    )

    defaults = dict(
        file_id="doc-001",
        case_id="ZAD-2024-01-0001",
        file_name="records.pdf",
        category=DocumentCategory.medical_records,
        processing_status=ProcessingStatus.pending,
        verification_status=VerificationStatus.unverified,
        scan_status=ScanStatus.clean,
    )
    defaults.update(overrides)
    return FileMetadataResponse(**defaults)


# ── TestGetClientIp ───────────────────────────────────────────────────────────


class TestGetClientIp:
    """Unit tests for the IP-extraction helper."""

    def test_xff_single_ip(self):
        from app.utils.audit import get_client_ip

        req = _mock_request(xff="203.0.113.5")
        assert get_client_ip(req) == "203.0.113.5"

    def test_xff_returns_first_ip_from_chain(self):
        """X-Forwarded-For may contain a proxy chain; first entry is the client."""
        from app.utils.audit import get_client_ip

        req = _mock_request(xff="203.0.113.5, 10.0.0.1, 192.168.1.1")
        assert get_client_ip(req) == "203.0.113.5"

    def test_falls_back_to_client_host_when_no_xff(self):
        from app.utils.audit import get_client_ip

        req = _mock_request(xff=None, client_host="198.51.100.42")
        assert get_client_ip(req) == "198.51.100.42"

    def test_returns_unknown_when_no_xff_and_no_client(self):
        from app.utils.audit import get_client_ip

        req = _mock_request(xff=None)
        req.client = None
        assert get_client_ip(req) == "unknown"


# ── TestLogAuditEvent ─────────────────────────────────────────────────────────


class TestLogAuditEvent:
    """Unit tests for the core log_audit_event() function."""

    def _invoke(self, mock_cloud_logger, mock_fs_db=None, **kwargs):
        from app.utils.audit import AuditAction, log_audit_event

        defaults = dict(
            action=AuditAction.view_metadata,
            request=_mock_request(),
        )
        defaults.update(kwargs)
        log_audit_event(**defaults)

    # ── Cloud Logging ─────────────────────────────────────────────────────────

    def test_writes_to_cloud_logging(self, mock_cloud_logger):
        with patch("app.utils.audit.get_firestore_client") as mock_fs:
            mock_fs.return_value = MagicMock()
            self._invoke(mock_cloud_logger)
        mock_cloud_logger.log_struct.assert_called_once()

    def test_cloud_logging_severity_is_notice(self, mock_cloud_logger):
        with patch("app.utils.audit.get_firestore_client") as mock_fs:
            mock_fs.return_value = MagicMock()
            self._invoke(mock_cloud_logger)
        kwargs = mock_cloud_logger.log_struct.call_args.kwargs
        assert kwargs.get("severity") == "NOTICE"

    def test_cloud_logging_payload_has_required_hipaa_fields(self, mock_cloud_logger):
        with patch("app.utils.audit.get_firestore_client") as mock_fs:
            mock_fs.return_value = MagicMock()
            self._invoke(
                mock_cloud_logger,
                document_id="doc-001",
                case_id="ZAD-2024-01-0001",
            )
        payload = mock_cloud_logger.log_struct.call_args[0][0]
        assert payload["action"] == "view_metadata"
        assert payload["documentId"] == "doc-001"
        assert payload["caseId"] == "ZAD-2024-01-0001"
        assert "timestamp" in payload
        assert "ipAddress" in payload
        assert "userAgent" in payload

    def test_service_name_included_in_event(self, mock_cloud_logger):
        with patch("app.utils.audit.get_firestore_client") as mock_fs:
            mock_fs.return_value = MagicMock()
            self._invoke(mock_cloud_logger)
        payload = mock_cloud_logger.log_struct.call_args[0][0]
        assert "service" in payload
        assert payload["service"] == "storage-gateway"

    def test_cloud_logging_failure_does_not_propagate(self, mock_cloud_logger):
        """Audit failures must never surface to the API caller."""
        mock_cloud_logger.log_struct.side_effect = Exception("GCP unavailable")
        with patch("app.utils.audit.get_firestore_client") as mock_fs:
            mock_fs.return_value = MagicMock()
            self._invoke(mock_cloud_logger)  # must not raise

    # ── Firestore ─────────────────────────────────────────────────────────────

    def test_writes_to_firestore_audit_logs_collection(self, mock_cloud_logger):
        with patch("app.utils.audit.get_firestore_client") as mock_fs:
            mock_db = MagicMock()
            mock_fs.return_value = mock_db
            self._invoke(mock_cloud_logger)
        mock_db.collection.assert_called_with("audit_logs")
        mock_db.collection.return_value.add.assert_called_once()

    def test_firestore_event_timestamp_is_datetime_not_string(self, mock_cloud_logger):
        """Firestore stores a native datetime for range queries; Cloud Logging gets ISO string."""
        with patch("app.utils.audit.get_firestore_client") as mock_fs:
            mock_db = MagicMock()
            mock_fs.return_value = mock_db
            self._invoke(mock_cloud_logger)
        firestore_payload = mock_db.collection.return_value.add.call_args[0][0]
        assert isinstance(firestore_payload["timestamp"], datetime.datetime)

    def test_firestore_failure_does_not_propagate(self, mock_cloud_logger):
        """Audit failures must never surface to the API caller."""
        with patch("app.utils.audit.get_firestore_client") as mock_fs:
            mock_db = MagicMock()
            mock_db.collection.return_value.add.side_effect = Exception("Firestore down")
            mock_fs.return_value = mock_db
            self._invoke(mock_cloud_logger)  # must not raise


# ── TestUploadRegisterAudit ───────────────────────────────────────────────────


class TestUploadRegisterAudit:
    """Verify POST /upload/register emits an upload_register audit event."""

    def _do_register(self, client):
        with patch("app.routes.upload.register_upload") as mock_reg, \
             patch("app.routes.upload.log_audit_event") as mock_audit:
            mock_reg.return_value = {
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
                    "folder_path": "medical-records",
                    "content_type": "application/pdf",
                    "case_id": "ZAD-2024-01-0001",
                },
            )
            return resp, mock_audit

    def test_audit_called_with_upload_register_action(self, client):
        resp, mock_audit = self._do_register(client)
        assert resp.status_code == 201
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["action"].value == "upload_register"

    def test_audit_includes_document_id_and_case_id(self, client):
        _resp, mock_audit = self._do_register(client)
        kwargs = mock_audit.call_args.kwargs
        assert kwargs["document_id"] == "uuid-001"
        assert kwargs["case_id"] == "ZAD-2024-01-0001"


# ── TestSignedUrlAudit ────────────────────────────────────────────────────────


class TestSignedUrlAudit:
    """Verify GET /signed-url emits signed_url_read / signed_url_write events."""

    def _do_signed_url(self, client, action: str = "read"):
        with patch("app.routes.signed_url.generate_signed_url") as mock_gs, \
             patch("app.routes.signed_url.get_gcs_client"), \
             patch("app.routes.signed_url.log_audit_event") as mock_audit:
            mock_gs.return_value = (
                "https://storage.googleapis.com/signed?token=abc",
                datetime.datetime(2024, 1, 15, 13, 0, 0),
                False,
            )
            params = {
                "case_id": "ZAD-2024-01-0001",
                "folder_path": "medical-records",
                "file_name": "records.pdf",
                "action": action,
            }
            if action == "write":
                params["content_type"] = "application/pdf"
            resp = client.get(
                "/api/v1/storage/signed-url",
                params=params,
            )
            return resp, mock_audit

    def test_read_action_emits_signed_url_read(self, client):
        resp, mock_audit = self._do_signed_url(client, action="read")
        assert resp.status_code == 200
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["action"].value == "signed_url_read"

    def test_write_action_emits_signed_url_write(self, client):
        resp, mock_audit = self._do_signed_url(client, action="write")
        assert resp.status_code == 200
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["action"].value == "signed_url_write"


# ── TestMetadataAudit ─────────────────────────────────────────────────────────


class TestMetadataAudit:
    """Verify GET /{fileId}/metadata emits a view_metadata audit event."""

    def _do_get_metadata(self, client):
        with patch("app.routes.metadata.get_file_metadata") as mock_meta, \
             patch("app.routes.metadata.log_audit_event") as mock_audit:
            mock_meta.return_value = _make_file_metadata_response()
            resp = client.get(
                "/api/v1/storage/doc-001/metadata",
                params={"case_id": "ZAD-2024-01-0001"},
            )
            return resp, mock_audit

    def test_audit_called_with_view_metadata_action(self, client):
        resp, mock_audit = self._do_get_metadata(client)
        assert resp.status_code == 200
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["action"].value == "view_metadata"

    def test_audit_includes_document_id_and_case_id(self, client):
        _resp, mock_audit = self._do_get_metadata(client)
        kwargs = mock_audit.call_args.kwargs
        assert kwargs["document_id"] == "doc-001"
        assert kwargs["case_id"] == "ZAD-2024-01-0001"


# ── TestDocumentsListAudit ────────────────────────────────────────────────────


class TestDocumentsListAudit:
    """Verify GET /cases/{caseId}/documents emits a list_documents audit event."""

    def _do_list(self, client):
        from app.models.storage import DocumentListResponse

        with patch("app.routes.documents.query_case_documents") as mock_q, \
             patch("app.routes.documents.log_audit_event") as mock_audit:
            mock_q.return_value = DocumentListResponse(
                case_id="ZAD-2024-01-0001",
                documents=[],
                page_size=20,
                next_page_token=None,
                has_more=False,
            )
            resp = client.get(
                "/api/v1/storage/cases/ZAD-2024-01-0001/documents",
            )
            return resp, mock_audit

    def test_audit_called_with_list_documents_action(self, client):
        resp, mock_audit = self._do_list(client)
        assert resp.status_code == 200
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["action"].value == "list_documents"

    def test_audit_includes_case_id(self, client):
        _resp, mock_audit = self._do_list(client)
        assert mock_audit.call_args.kwargs["case_id"] == "ZAD-2024-01-0001"


# ── TestDocumentsPatchAudit ───────────────────────────────────────────────────


class TestDocumentsPatchAudit:
    """Verify PATCH /cases/{caseId}/documents/{fileId} emits update_metadata."""

    def _do_patch(self, client):
        with patch("app.routes.documents.update_document_metadata") as mock_upd, \
             patch("app.routes.documents.log_audit_event") as mock_audit:
            from app.models.storage import ProcessingStatus

            mock_upd.return_value = _make_file_metadata_response(
                processing_status=ProcessingStatus.completed
            )
            resp = client.patch(
                "/api/v1/storage/cases/ZAD-2024-01-0001/documents/doc-001",
                json={"processing_status": "Completed"},
            )
            return resp, mock_audit

    def test_audit_called_with_update_metadata_action(self, client):
        resp, mock_audit = self._do_patch(client)
        assert resp.status_code == 200
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["action"].value == "update_metadata"

    def test_audit_includes_document_id_and_case_id(self, client):
        _resp, mock_audit = self._do_patch(client)
        kwargs = mock_audit.call_args.kwargs
        assert kwargs["document_id"] == "doc-001"
        assert kwargs["case_id"] == "ZAD-2024-01-0001"


# ── TestCaseHoldAudit ─────────────────────────────────────────────────────────


class TestCaseHoldAudit:
    """Verify PUT /cases/{caseId}/hold emits hold_set / hold_release events."""

    def _do_hold(self, client, hold: bool):
        with patch("app.routes.lifecycle.set_case_documents_hold") as mock_hold, \
             patch("app.routes.lifecycle.log_audit_event") as mock_audit:
            mock_hold.return_value = 3
            resp = client.put(
                "/api/v1/storage/cases/ZAD-2024-01-0001/hold",
                json={"hold": hold},
            )
            return resp, mock_audit

    def test_hold_true_emits_hold_set(self, client, mock_gcs_client):
        resp, mock_audit = self._do_hold(client, hold=True)
        assert resp.status_code == 200
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["action"].value == "hold_set"

    def test_hold_false_emits_hold_release(self, client, mock_gcs_client):
        resp, mock_audit = self._do_hold(client, hold=False)
        assert resp.status_code == 200
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["action"].value == "hold_release"
