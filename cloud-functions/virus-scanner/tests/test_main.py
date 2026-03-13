"""
Unit tests for the virus_scan Cloud Function entry point.
"""

import sys
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

# Set required env vars before importing main
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("GCS_BUCKET_NAME", "test-bucket")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _make_event(bucket: str, blob_name: str) -> MagicMock:
    event = MagicMock()
    event.data = {"bucket": bucket, "name": blob_name}
    return event


def _make_upload_snap(file_id: str, case_id: str | None = "ZAD-2024-01-0001") -> MagicMock:
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = {
        "fileId": file_id,
        "caseId": case_id,
        "fileName": "records.pdf",
        "category": "medical_records",
        "finalPath": "ZAD-2024-01-0001/medical-records/records.pdf",
        "uploadedBy": "staff@simpletort.com",
        "stagingPath": "staging/{}/records.pdf".format(file_id),
    }
    return snap


class TestVirusScanFunction:
    def test_ignores_non_staging_blobs(self):
        from main import virus_scan
        event = _make_event("test-bucket", "ZAD-2024-01-0001/medical-records/file.pdf")

        with patch("main._get_db") as mock_db, patch("main._get_gcs") as mock_gcs:
            virus_scan(event)
            mock_db.assert_not_called()
            mock_gcs.assert_not_called()

    def test_skips_when_firestore_record_missing(self):
        from main import virus_scan
        event = _make_event("test-bucket", "staging/uuid-001/records.pdf")

        mock_snap = MagicMock()
        mock_snap.exists = False

        mock_db = MagicMock()
        mock_db.collection.return_value.document.return_value.get.return_value = mock_snap

        with patch("main._get_db", return_value=mock_db), \
             patch("main._get_gcs") as mock_gcs:
            virus_scan(event)
            mock_gcs.assert_not_called()

    def test_clean_scan_moves_to_final_path(self):
        from main import virus_scan
        file_id = "uuid-clean-001"
        event = _make_event("test-bucket", "staging/{}/records.pdf".format(file_id))

        mock_snap = _make_upload_snap(file_id)

        # Firestore mocks
        mock_upload_ref = MagicMock()
        mock_case_doc_ref = MagicMock()
        mock_db = MagicMock()
        mock_db.collection.return_value.document.return_value.get.return_value = mock_snap
        mock_db.collection.return_value.document.return_value = mock_upload_ref

        # GCS mocks
        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_gcs_client = MagicMock()
        mock_gcs_client.bucket.return_value = mock_bucket

        from scanner import ScanResult
        clean_result = ScanResult(is_clean=True, raw_output="/tmp/f: OK")

        with patch("main._get_db", return_value=mock_db), \
             patch("main._get_gcs", return_value=mock_gcs_client), \
             patch("main.scan_file", return_value=clean_result), \
             patch("main.tempfile.NamedTemporaryFile") as mock_tmp:

            mock_tmp.return_value.__enter__ = MagicMock(return_value=MagicMock(name="/tmp/f.pdf"))
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

            virus_scan(event)

        # Staging blob should be copied then deleted
        mock_bucket.copy_blob.assert_called_once()
        mock_blob.delete.assert_called_once()

    def test_infected_scan_quarantines_and_publishes(self):
        from main import virus_scan
        file_id = "uuid-infected-001"
        event = _make_event("test-bucket", "staging/{}/malware.pdf".format(file_id))

        mock_snap = _make_upload_snap(file_id)
        mock_upload_ref = MagicMock()
        mock_db = MagicMock()
        mock_db.collection.return_value.document.return_value.get.return_value = mock_snap
        mock_db.collection.return_value.document.return_value = mock_upload_ref

        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_gcs_client = MagicMock()
        mock_gcs_client.bucket.return_value = mock_bucket

        from scanner import ScanResult
        infected_result = ScanResult(
            is_clean=False,
            raw_output="/tmp/m.pdf: Eicar-Signature FOUND",
            threat="Eicar-Signature",
        )

        with patch("main._get_db", return_value=mock_db), \
             patch("main._get_gcs", return_value=mock_gcs_client), \
             patch("main.scan_file", return_value=infected_result), \
             patch("main.publish_virus_detected") as mock_pub, \
             patch("main.tempfile.NamedTemporaryFile") as mock_tmp:

            mock_tmp.return_value.__enter__ = MagicMock(return_value=MagicMock(name="/tmp/m.pdf"))
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

            virus_scan(event)

        # Quarantine copy + staging delete
        mock_bucket.copy_blob.assert_called_once()
        mock_blob.delete.assert_called_once()
        # Pub/Sub notification published
        mock_pub.assert_called_once()
        call_kwargs = mock_pub.call_args.kwargs
        assert call_kwargs["threat"] == "Eicar-Signature"
        assert call_kwargs["file_id"] == file_id
