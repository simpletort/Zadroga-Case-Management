"""
Tests for the documents route (GET list / PATCH update) and the underlying
query_case_documents / update_document_metadata service functions.
"""

from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock, call, patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_doc(file_id: str, data: Optional[dict] = None):
    """Return a Firestore document snapshot mock."""
    doc = MagicMock()
    doc.id = file_id
    doc.exists = True
    doc.to_dict.return_value = data or {
        "fileName": "{}.pdf".format(file_id),
        "category": "medical_records",
        "gcsPath": "ZAD-2024-01-0001/medical-records/{}.pdf".format(file_id),
        "mimeType": "application/pdf",
        "sizeBytes": 204800,
        "uploadedBy": "paralegal@simpletort.com",
        "uploadedAt": datetime(2024, 6, 1, tzinfo=timezone.utc),
        "processingStatus": "Pending",
        "verificationStatus": "Unverified",
        "scanStatus": "clean",
        "extractedData": None,
        "documentAiResults": None,
        "medicalAiResults": None,
    }
    return doc


def _make_col_mock(docs: list, cursor_exists: bool = False):
    """
    Build a Firestore collection mock that supports the full query chain:
      col.order_by(...).where(...).limit(...).stream()
    and also col.document(page_token).get() for cursor pagination.
    """
    mock_query = MagicMock()
    mock_query.order_by.return_value = mock_query
    mock_query.where.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.start_after.return_value = mock_query
    mock_query.stream.return_value = iter(docs)

    cursor_snap = MagicMock()
    cursor_snap.exists = cursor_exists

    mock_col = MagicMock()
    mock_col.order_by.return_value = mock_query
    mock_col.document.return_value.get.return_value = cursor_snap

    return mock_col, mock_query


def _db_from_col(mock_col):
    """Wire a collection mock into a Firestore db mock."""
    mock_db = MagicMock()
    # cases/{caseId}/documents
    mock_db.collection.return_value.document.return_value.collection.return_value = mock_col
    return mock_db


# ── GET /api/v1/storage/cases/{case_id}/documents ────────────────────────────

class TestListCaseDocuments:
    CASE_ID = "ZAD-2024-01-0001"
    URL = "/api/v1/storage/cases/{}/documents".format(CASE_ID)
    AUTH = {"Authorization": "Bearer fake-token"}

    def test_returns_documents_for_case(self, client):
        docs = [_make_doc("file-001"), _make_doc("file-002")]
        mock_col, _ = _make_col_mock(docs)

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db_fn.return_value = _db_from_col(mock_col)
            resp = client.get(self.URL, headers=self.AUTH)

        assert resp.status_code == 200
        body = resp.json()
        assert body["case_id"] == self.CASE_ID
        assert len(body["documents"]) == 2
        assert body["documents"][0]["file_id"] == "file-001"
        assert body["documents"][1]["file_id"] == "file-002"
        assert body["has_more"] is False
        assert body["next_page_token"] is None

    def test_filters_by_category(self, client):
        docs = [_make_doc("file-med-001")]
        mock_col, mock_query = _make_col_mock(docs)

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db_fn.return_value = _db_from_col(mock_col)
            resp = client.get(
                self.URL, params={"category": "medical_records"}, headers=self.AUTH
            )

        assert resp.status_code == 200
        # where() was called with the category filter
        mock_query.where.assert_any_call("category", "==", "medical_records")

    def test_filters_by_processing_status(self, client):
        mock_col, mock_query = _make_col_mock([])

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db_fn.return_value = _db_from_col(mock_col)
            resp = client.get(
                self.URL, params={"processing_status": "Completed"}, headers=self.AUTH
            )

        assert resp.status_code == 200
        mock_query.where.assert_any_call("processingStatus", "==", "Completed")

    def test_filters_by_scan_status(self, client):
        mock_col, mock_query = _make_col_mock([])

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db_fn.return_value = _db_from_col(mock_col)
            resp = client.get(
                self.URL, params={"scan_status": "clean"}, headers=self.AUTH
            )

        assert resp.status_code == 200
        mock_query.where.assert_any_call("scanStatus", "==", "clean")

    def test_filters_by_verification_status(self, client):
        mock_col, mock_query = _make_col_mock([])

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db_fn.return_value = _db_from_col(mock_col)
            resp = client.get(
                self.URL, params={"verification_status": "AI Verified"}, headers=self.AUTH
            )

        assert resp.status_code == 200
        mock_query.where.assert_any_call("verificationStatus", "==", "AI Verified")

    def test_has_more_true_when_extra_document_returned(self, client):
        # 3 docs returned when page_size=2 → has_more=True, next_page_token set
        docs = [_make_doc("f-001"), _make_doc("f-002"), _make_doc("f-003")]
        mock_col, _ = _make_col_mock(docs)

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db_fn.return_value = _db_from_col(mock_col)
            resp = client.get(
                self.URL, params={"page_size": 2}, headers=self.AUTH
            )

        body = resp.json()
        assert body["has_more"] is True
        assert body["next_page_token"] == "f-002"   # last of the truncated page
        assert len(body["documents"]) == 2

    def test_has_more_false_on_last_page(self, client):
        docs = [_make_doc("f-001")]
        mock_col, _ = _make_col_mock(docs)

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db_fn.return_value = _db_from_col(mock_col)
            resp = client.get(
                self.URL, params={"page_size": 10}, headers=self.AUTH
            )

        body = resp.json()
        assert body["has_more"] is False
        assert body["next_page_token"] is None

    def test_empty_list_when_no_documents(self, client):
        mock_col, _ = _make_col_mock([])

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db_fn.return_value = _db_from_col(mock_col)
            resp = client.get(self.URL, headers=self.AUTH)

        body = resp.json()
        assert resp.status_code == 200
        assert body["documents"] == []
        assert body["has_more"] is False

    def test_pagination_cursor_passed_to_start_after(self, client):
        docs = [_make_doc("f-002")]
        mock_col, mock_query = _make_col_mock(docs, cursor_exists=True)

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db_fn.return_value = _db_from_col(mock_col)
            resp = client.get(
                self.URL, params={"page_token": "f-001"}, headers=self.AUTH
            )

        assert resp.status_code == 200
        # start_after should have been called with the cursor snapshot
        mock_query.start_after.assert_called_once()

    def test_page_size_too_large_returns_422(self, client):
        resp = client.get(
            self.URL, params={"page_size": 101}, headers=self.AUTH
        )
        assert resp.status_code == 422

    def test_page_size_zero_returns_422(self, client):
        resp = client.get(
            self.URL, params={"page_size": 0}, headers=self.AUTH
        )
        assert resp.status_code == 422

    def test_unauthenticated_returns_403(self, client):
        resp = client.get(self.URL)
        assert resp.status_code in (401, 403)

    def test_response_includes_scan_status_and_extracted_data(self, client):
        doc_data = {
            "fileName": "report.pdf",
            "category": "medical_records",
            "gcsPath": "ZAD-2024-01-0001/medical-records/report.pdf",
            "mimeType": "application/pdf",
            "sizeBytes": 1024,
            "uploadedBy": "staff@example.com",
            "uploadedAt": datetime(2024, 6, 1, tzinfo=timezone.utc),
            "processingStatus": "Completed",
            "verificationStatus": "AI Verified",
            "scanStatus": "clean",
            "extractedData": {"diagnosis": "silicosis"},
            "documentAiResults": None,
            "medicalAiResults": None,
        }
        mock_col, _ = _make_col_mock([_make_doc("file-rich", doc_data)])

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db_fn.return_value = _db_from_col(mock_col)
            resp = client.get(self.URL, headers=self.AUTH)

        doc = resp.json()["documents"][0]
        assert doc["scan_status"] == "clean"
        assert doc["extracted_data"] == {"diagnosis": "silicosis"}


# ── PATCH /api/v1/storage/cases/{case_id}/documents/{file_id} ─────────────────

class TestPatchDocumentMetadata:
    CASE_ID = "ZAD-2024-01-0001"
    FILE_ID = "file-abc-001"
    URL = "/api/v1/storage/cases/{}/documents/{}".format(CASE_ID, FILE_ID)
    AUTH = {"Authorization": "Bearer fake-token"}

    def _existing_snap(self, data: Optional[dict] = None):
        snap = MagicMock()
        snap.exists = True
        snap.to_dict.return_value = data or {
            "fileName": "report.pdf",
            "category": "medical_records",
            "gcsPath": "ZAD-2024-01-0001/medical-records/report.pdf",
            "mimeType": "application/pdf",
            "sizeBytes": 1024,
            "uploadedBy": "staff@example.com",
            "uploadedAt": None,
            "processingStatus": "Pending",
            "verificationStatus": "Unverified",
            "scanStatus": "clean",
            "extractedData": None,
            "documentAiResults": None,
            "medicalAiResults": None,
        }
        return snap

    def _wire_db(self, mock_db, existing_snap, updated_snap=None):
        """Wire get() → existing_snap (first call) and updated_snap (second call)."""
        ref = MagicMock()
        ref.get.side_effect = [existing_snap, updated_snap or existing_snap]
        mock_db.collection.return_value.document.return_value \
            .collection.return_value.document.return_value = ref
        return ref

    def test_updates_processing_status(self, client):
        existing = self._existing_snap()
        updated_data = dict(existing.to_dict())
        updated_data["processingStatus"] = "Completed"
        updated = MagicMock()
        updated.exists = True
        updated.to_dict.return_value = updated_data

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db = MagicMock()
            mock_db_fn.return_value = mock_db
            ref = self._wire_db(mock_db, existing, updated)

            resp = client.patch(
                self.URL,
                json={"processing_status": "Completed"},
                headers=self.AUTH,
            )

        assert resp.status_code == 200
        ref.update.assert_called_once_with({"processingStatus": "Completed"})
        assert resp.json()["processing_status"] == "Completed"

    def test_updates_verification_status(self, client):
        existing = self._existing_snap()
        updated_data = dict(existing.to_dict())
        updated_data["verificationStatus"] = "Manually Verified"
        updated = MagicMock()
        updated.exists = True
        updated.to_dict.return_value = updated_data

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db = MagicMock()
            mock_db_fn.return_value = mock_db
            ref = self._wire_db(mock_db, existing, updated)

            resp = client.patch(
                self.URL,
                json={"verification_status": "Manually Verified"},
                headers=self.AUTH,
            )

        assert resp.status_code == 200
        ref.update.assert_called_once_with({"verificationStatus": "Manually Verified"})

    def test_updates_extracted_data(self, client):
        payload = {"diagnosis": "pulmonary fibrosis", "icd_code": "J84.10"}
        existing = self._existing_snap()
        updated_data = dict(existing.to_dict())
        updated_data["extractedData"] = payload
        updated = MagicMock()
        updated.exists = True
        updated.to_dict.return_value = updated_data

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db = MagicMock()
            mock_db_fn.return_value = mock_db
            ref = self._wire_db(mock_db, existing, updated)

            resp = client.patch(
                self.URL,
                json={"extracted_data": payload},
                headers=self.AUTH,
            )

        assert resp.status_code == 200
        ref.update.assert_called_once_with({"extractedData": payload})
        assert resp.json()["extracted_data"] == payload

    def test_empty_patch_skips_firestore_update(self, client):
        existing = self._existing_snap()

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db = MagicMock()
            mock_db_fn.return_value = mock_db
            ref = self._wire_db(mock_db, existing)

            resp = client.patch(self.URL, json={}, headers=self.AUTH)

        assert resp.status_code == 200
        ref.update.assert_not_called()

    def test_returns_404_for_missing_document(self, client):
        missing = MagicMock()
        missing.exists = False

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db = MagicMock()
            mock_db_fn.return_value = mock_db
            mock_db.collection.return_value.document.return_value \
                .collection.return_value.document.return_value \
                .get.return_value = missing

            resp = client.patch(
                self.URL, json={"processing_status": "Completed"}, headers=self.AUTH
            )

        assert resp.status_code == 404

    def test_unauthenticated_returns_403(self, client):
        resp = client.patch(self.URL, json={"processing_status": "Completed"})
        assert resp.status_code in (401, 403)


# ── query_case_documents service unit tests ────────────────────────────────────

class TestQueryCaseDocumentsService:
    def test_no_filters_streams_all_documents(self):
        from app.services.metadata_service import query_case_documents

        docs = [_make_doc("d-001"), _make_doc("d-002")]
        mock_col, mock_query = _make_col_mock(docs)

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db_fn.return_value = _db_from_col(mock_col)
            result = query_case_documents(case_id="ZAD-2024-01-0001", page_size=20)

        assert len(result.documents) == 2
        assert result.has_more is False

    def test_category_filter_calls_where(self):
        from app.services.metadata_service import query_case_documents
        from app.models.storage import DocumentCategory

        mock_col, mock_query = _make_col_mock([])

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db_fn.return_value = _db_from_col(mock_col)
            query_case_documents(
                case_id="ZAD-2024-01-0001",
                category=DocumentCategory.vcf_documents,
            )

        mock_query.where.assert_any_call("category", "==", "vcf_documents")

    def test_detects_has_more_when_one_extra_returned(self):
        from app.services.metadata_service import query_case_documents

        # limit(2+1)=3 docs returned but page_size=2 → has_more
        docs = [_make_doc("d-001"), _make_doc("d-002"), _make_doc("d-003")]
        mock_col, mock_query = _make_col_mock(docs)

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db_fn.return_value = _db_from_col(mock_col)
            result = query_case_documents(case_id="ZAD-2024-01-0001", page_size=2)

        assert result.has_more is True
        assert result.next_page_token == "d-002"
        assert len(result.documents) == 2

    def test_limit_called_with_page_size_plus_one(self):
        from app.services.metadata_service import query_case_documents

        mock_col, mock_query = _make_col_mock([])

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db_fn.return_value = _db_from_col(mock_col)
            query_case_documents(case_id="ZAD-2024-01-0001", page_size=15)

        mock_query.limit.assert_called_once_with(16)

    def test_start_after_not_called_when_no_page_token(self):
        from app.services.metadata_service import query_case_documents

        mock_col, mock_query = _make_col_mock([])

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db_fn.return_value = _db_from_col(mock_col)
            query_case_documents(case_id="ZAD-2024-01-0001")

        mock_query.start_after.assert_not_called()

    def test_start_after_called_when_cursor_exists(self):
        from app.services.metadata_service import query_case_documents

        mock_col, mock_query = _make_col_mock([], cursor_exists=True)

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db_fn.return_value = _db_from_col(mock_col)
            query_case_documents(case_id="ZAD-2024-01-0001", page_token="d-010")

        mock_query.start_after.assert_called_once()

    def test_start_after_skipped_when_cursor_not_found(self):
        from app.services.metadata_service import query_case_documents

        mock_col, mock_query = _make_col_mock([], cursor_exists=False)

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db_fn.return_value = _db_from_col(mock_col)
            query_case_documents(case_id="ZAD-2024-01-0001", page_token="nonexistent-id")

        mock_query.start_after.assert_not_called()


# ── update_document_metadata service unit tests ───────────────────────────────

class TestUpdateDocumentMetadataService:
    def _make_ref(self, snap_data: Optional[dict] = None, exists: bool = True):
        snap = MagicMock()
        snap.exists = exists
        snap.to_dict.return_value = snap_data or {
            "fileName": "doc.pdf",
            "category": "legal_forms",
            "gcsPath": "ZAD-2024-01-0001/legal-forms/doc.pdf",
            "mimeType": "application/pdf",
            "sizeBytes": 512,
            "uploadedBy": "staff@example.com",
            "uploadedAt": None,
            "processingStatus": "Pending",
            "verificationStatus": "Unverified",
            "scanStatus": "clean",
            "extractedData": None,
            "documentAiResults": None,
            "medicalAiResults": None,
        }
        ref = MagicMock()
        ref.get.return_value = snap
        return ref, snap

    def test_updates_only_provided_fields(self):
        from app.services.metadata_service import update_document_metadata
        from app.models.storage import DocumentMetadataUpdateRequest, ProcessingStatus

        ref, _ = self._make_ref()

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db = MagicMock()
            mock_db_fn.return_value = mock_db
            mock_db.collection.return_value.document.return_value \
                .collection.return_value.document.return_value = ref

            update_document_metadata(
                case_id="ZAD-2024-01-0001",
                file_id="doc-001",
                request=DocumentMetadataUpdateRequest(
                    processing_status=ProcessingStatus.completed
                ),
            )

        ref.update.assert_called_once_with({"processingStatus": "Completed"})

    def test_no_firestore_write_when_all_fields_none(self):
        from app.services.metadata_service import update_document_metadata
        from app.models.storage import DocumentMetadataUpdateRequest

        ref, _ = self._make_ref()

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db = MagicMock()
            mock_db_fn.return_value = mock_db
            mock_db.collection.return_value.document.return_value \
                .collection.return_value.document.return_value = ref

            update_document_metadata(
                case_id="ZAD-2024-01-0001",
                file_id="doc-001",
                request=DocumentMetadataUpdateRequest(),
            )

        ref.update.assert_not_called()

    def test_raises_404_when_document_not_found(self):
        from app.services.metadata_service import update_document_metadata
        from app.models.storage import DocumentMetadataUpdateRequest, ProcessingStatus
        from fastapi import HTTPException

        ref, _ = self._make_ref(exists=False)

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db = MagicMock()
            mock_db_fn.return_value = mock_db
            mock_db.collection.return_value.document.return_value \
                .collection.return_value.document.return_value = ref

            with pytest.raises(HTTPException) as exc_info:
                update_document_metadata(
                    case_id="ZAD-2024-01-0001",
                    file_id="missing-id",
                    request=DocumentMetadataUpdateRequest(
                        processing_status=ProcessingStatus.completed
                    ),
                )

        assert exc_info.value.status_code == 404

    def test_returns_updated_document_response(self):
        from app.services.metadata_service import update_document_metadata
        from app.models.storage import DocumentMetadataUpdateRequest, VerificationStatus

        updated_data = {
            "fileName": "doc.pdf",
            "category": "legal_forms",
            "gcsPath": "ZAD-2024-01-0001/legal-forms/doc.pdf",
            "mimeType": "application/pdf",
            "sizeBytes": 512,
            "uploadedBy": "staff@example.com",
            "uploadedAt": None,
            "processingStatus": "Completed",
            "verificationStatus": "Manually Verified",
            "scanStatus": "clean",
            "extractedData": None,
            "documentAiResults": None,
            "medicalAiResults": None,
        }

        initial_snap = MagicMock()
        initial_snap.exists = True
        initial_snap.to_dict.return_value = {}

        updated_snap = MagicMock()
        updated_snap.exists = True
        updated_snap.to_dict.return_value = updated_data

        ref = MagicMock()
        ref.get.side_effect = [initial_snap, updated_snap]

        with patch("app.services.metadata_service.get_firestore_client") as mock_db_fn:
            mock_db = MagicMock()
            mock_db_fn.return_value = mock_db
            mock_db.collection.return_value.document.return_value \
                .collection.return_value.document.return_value = ref

            result = update_document_metadata(
                case_id="ZAD-2024-01-0001",
                file_id="doc-001",
                request=DocumentMetadataUpdateRequest(
                    verification_status=VerificationStatus.manually_verified
                ),
            )

        assert result.verification_status == VerificationStatus.manually_verified
        assert result.processing_status.value == "Completed"
