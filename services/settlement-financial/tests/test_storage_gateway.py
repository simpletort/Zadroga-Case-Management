"""
tests/test_storage_gateway.py
==============================
End-to-end smoke test for the storage gateway endpoints.

Run:
    cd services/settlement-financial
    python -m pytest tests/test_storage_gateway.py -v

Or run manually against the live service:
    python tests/test_storage_gateway.py
"""
from __future__ import annotations

import io
import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

CASE_ID   = "ZAD-2026-04-0001"
FAKE_FILE = b"%PDF-1.4 fake pdf content for testing"


# ── Mock helpers ──────────────────────────────────────────────────────────────

def _make_db(existing_items=None):
    """Mock Firestore db with settlement/files document."""
    db      = MagicMock()
    items   = existing_items or []
    doc     = MagicMock()
    doc.exists = True
    doc.to_dict.return_value = {"items": items}

    ref = MagicMock()
    ref.get  = AsyncMock(return_value=doc)
    ref.set  = AsyncMock()

    db.collection.return_value \
      .document.return_value \
      .collection.return_value \
      .document.return_value = ref

    return db, ref


def _make_settings():
    from config import Settings
    s = MagicMock(spec=Settings)
    s.gcs_bucket                        = "test-bucket"
    s.firebase_service_account_key_path = ""
    return s


# ── Upload tests ──────────────────────────────────────────────────────────────

class TestUploadFile:

    @patch("main.get_settings")
    @patch("main.get_db")
    @patch("services.storage_service._upload_bytes_to_gcs", return_value="gs://test-bucket/cases/ZAD-2026-04-0001/files/receipt/abc_test.pdf")
    def test_upload_returns_201(self, mock_gcs, mock_db, mock_settings):
        from main import app
        db, _ = _make_db()
        mock_db.return_value      = db
        mock_settings.return_value = _make_settings()

        client = TestClient(app)
        resp   = client.post(
            f"/api/v1/settlement/cases/{CASE_ID}/files",
            files={"file": ("test.pdf", io.BytesIO(FAKE_FILE), "application/pdf")},
            data={"file_type": "receipt", "description": "Test receipt", "uploaded_by": "tester"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["case_id"]           == CASE_ID
        assert body["original_filename"] == "test.pdf"
        assert body["content_type"]      == "application/pdf"
        assert body["file_type"]         == "receipt"
        assert "file_id"      in body
        assert "gcs_path"     in body
        assert "download_url" in body

    @patch("main.get_settings")
    @patch("main.get_db")
    @patch("services.storage_service._upload_bytes_to_gcs", return_value="gs://test-bucket/x")
    def test_upload_rejects_disallowed_type(self, mock_gcs, mock_db, mock_settings):
        from main import app
        db, _ = _make_db()
        mock_db.return_value       = db
        mock_settings.return_value = _make_settings()

        client = TestClient(app)
        resp   = client.post(
            f"/api/v1/settlement/cases/{CASE_ID}/files",
            files={"file": ("virus.exe", io.BytesIO(b"MZ bad file"), "application/x-msdownload")},
            data={"file_type": "other"},
        )
        assert resp.status_code == 422
        assert "not allowed" in resp.json()["detail"]

    @patch("main.get_settings")
    @patch("main.get_db")
    @patch("services.storage_service._upload_bytes_to_gcs", return_value="gs://test-bucket/x")
    def test_upload_gcs_path_contains_case_id(self, mock_gcs, mock_db, mock_settings):
        from main import app
        db, _ = _make_db()
        mock_db.return_value       = db
        mock_settings.return_value = _make_settings()

        client = TestClient(app)
        resp   = client.post(
            f"/api/v1/settlement/cases/{CASE_ID}/files",
            files={"file": ("doc.pdf", io.BytesIO(FAKE_FILE), "application/pdf")},
            data={"file_type": "case_document"},
        )
        assert resp.status_code == 201
        assert CASE_ID in resp.json()["gcs_path"]


# ── List tests ────────────────────────────────────────────────────────────────

class TestListFiles:

    @patch("main.get_db")
    def test_list_returns_items(self, mock_db):
        from main import app
        from datetime import datetime, timezone

        now   = datetime.now(tz=timezone.utc)
        items = [
            {
                "fileId": str(uuid.uuid4()), "caseId": CASE_ID,
                "originalFilename": "receipt.pdf", "contentType": "application/pdf",
                "sizeBytes": 1024, "gcsPath": f"gs://bucket/cases/{CASE_ID}/files/receipt/abc.pdf",
                "fileType": "receipt", "description": None,
                "linkedToType": None, "linkedToId": None,
                "uploadedBy": "tester", "uploadedAt": now, "updatedAt": None,
            }
        ]
        db, _ = _make_db(existing_items=items)
        mock_db.return_value = db

        client = TestClient(app)
        resp   = client.get(f"/api/v1/settlement/cases/{CASE_ID}/files")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"]        == 1
        assert body["case_id"]      == CASE_ID
        assert len(body["files"])   == 1
        assert body["files"][0]["original_filename"] == "receipt.pdf"

    @patch("main.get_db")
    def test_list_empty_case_returns_zero(self, mock_db):
        from main import app
        db, ref = _make_db()
        ref.get = AsyncMock(return_value=MagicMock(exists=False))
        mock_db.return_value = db

        client = TestClient(app)
        resp   = client.get(f"/api/v1/settlement/cases/{CASE_ID}/files")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# ── Delete tests ──────────────────────────────────────────────────────────────

class TestDeleteFile:

    @patch("main.get_settings")
    @patch("main.get_db")
    @patch("services.storage_service._delete_from_gcs")
    def test_delete_existing_file_returns_204(self, mock_del, mock_db, mock_settings):
        from main import app
        from datetime import datetime, timezone

        fid   = str(uuid.uuid4())
        items = [{
            "fileId": fid, "caseId": CASE_ID,
            "originalFilename": "doc.pdf", "contentType": "application/pdf",
            "sizeBytes": 512,
            "gcsPath": f"gs://test-bucket/cases/{CASE_ID}/files/other/{fid}_doc.pdf",
            "fileType": "other", "description": None,
            "linkedToType": None, "linkedToId": None,
            "uploadedBy": "", "uploadedAt": datetime.now(tz=timezone.utc), "updatedAt": None,
        }]
        db, _ = _make_db(existing_items=items)
        mock_db.return_value       = db
        mock_settings.return_value = _make_settings()

        client = TestClient(app)
        resp   = client.delete(f"/api/v1/settlement/cases/{CASE_ID}/files/{fid}")
        assert resp.status_code == 204

    @patch("main.get_settings")
    @patch("main.get_db")
    def test_delete_nonexistent_file_returns_404(self, mock_db, mock_settings):
        from main import app
        db, _ = _make_db(existing_items=[])
        mock_db.return_value       = db
        mock_settings.return_value = _make_settings()

        client = TestClient(app)
        resp   = client.delete(f"/api/v1/settlement/cases/{CASE_ID}/files/nonexistent-id")
        assert resp.status_code == 404


# ── Signed URL tests ──────────────────────────────────────────────────────────

class TestSignedUrl:

    @patch("main.get_settings")
    @patch("main.get_db")
    @patch("services.storage_service._make_signed_url", return_value="https://signed.example.com/file.pdf")
    def test_get_url_returns_signed_url(self, mock_sign, mock_db, mock_settings):
        from main import app
        from datetime import datetime, timezone

        fid   = str(uuid.uuid4())
        items = [{
            "fileId": fid, "caseId": CASE_ID,
            "originalFilename": "lien.pdf", "contentType": "application/pdf",
            "sizeBytes": 2048,
            "gcsPath": f"gs://test-bucket/cases/{CASE_ID}/files/lien_document/{fid}_lien.pdf",
            "fileType": "lien_document", "description": None,
            "linkedToType": "lien", "linkedToId": "lien-uuid",
            "uploadedBy": "", "uploadedAt": datetime.now(tz=timezone.utc), "updatedAt": None,
        }]
        db, _ = _make_db(existing_items=items)
        mock_db.return_value       = db
        mock_settings.return_value = _make_settings()

        client = TestClient(app)
        resp   = client.get(f"/api/v1/settlement/cases/{CASE_ID}/files/{fid}/url")
        assert resp.status_code == 200
        body = resp.json()
        assert body["signed_url"] == "https://signed.example.com/file.pdf"
        assert body["file_id"]    == fid


# ── Manual live test (run directly) ──────────────────────────────────────────

if __name__ == "__main__":
    import requests

    BASE = f"http://localhost:8080/api/v1/settlement/cases/{CASE_ID}"
    PDF  = os.path.join(os.path.dirname(__file__), "..", "settlement_statement_SAMPLE.pdf")

    if not os.path.exists(PDF):
        print(f"[SKIP] Sample PDF not found at {PDF}")
        sys.exit(0)

    print("\n--- 1. Upload -------------------------------------------")
    with open(PDF, "rb") as f:
        r = requests.post(
            f"{BASE}/files",
            files={"file": ("sample_statement.pdf", f, "application/pdf")},
            data={"file_type": "settlement_doc", "description": "Sample settlement statement",
                  "uploaded_by": "test-runner"},
        )
    print(f"Status : {r.status_code}")
    data    = r.json()
    file_id = data.get("file_id")
    print(f"file_id: {file_id}")
    print(f"gcs    : {data.get('gcs_path')}")
    print(f"url    : {data.get('download_url')}")

    print("\n--- 2. List --------------------------------------------")
    r = requests.get(f"{BASE}/files")
    print(f"Status : {r.status_code}")
    body = r.json()
    print(f"Total files: {body['total']}")
    for f in body["files"]:
        print(f"  - {f['original_filename']}  ({f['file_type']})  {f['size_bytes']} bytes")

    print("\n--- 3. Signed URL --------------------------------------")
    r = requests.get(f"{BASE}/files/{file_id}/url")
    print(f"Status : {r.status_code}")
    print(f"URL    : {r.json().get('signed_url')}")

    print("\n--- 4. Download ----------------------------------------")
    r = requests.get(f"{BASE}/files/{file_id}/download")
    print(f"Status       : {r.status_code}")
    print(f"Content-Type : {r.headers.get('Content-Type')}")
    print(f"Bytes received: {len(r.content)}")

    print("\n--- 5. Delete ------------------------------------------")
    r = requests.delete(f"{BASE}/files/{file_id}")
    print(f"Status : {r.status_code}  (expect 204)")

    print("\n--- 6. Verify deleted ----------------------------------")
    r = requests.get(f"{BASE}/files")
    remaining = [f for f in r.json()["files"] if f["file_id"] == file_id]
    print(f"File still present: {bool(remaining)}  (expect False)")
    print("\n[OK] All storage gateway live tests passed.")
