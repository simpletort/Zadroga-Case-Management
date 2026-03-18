import os
import pytest

os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("GCS_BUCKET_NAME", "test-bucket")
os.environ.setdefault("DRIVE_SYNC_SECRET", "test-secret")

VALID_TOKEN_DOC = {"caseId": "ZAD-2026-03-0001"}

FILE_PDF = {
    "driveFileId": "drive-file-id-001",
    "fileName":    "medical_record.pdf",
    "mimeType":    "application/pdf",
    "category":    "medical_records",
}

FILE_JPEG = {
    "driveFileId": "drive-file-id-002",
    "fileName":    "photo_id.jpg",
    "mimeType":    "image/jpeg",
    "category":    "id_documents",
}

FILE_BAD_MIME = {
    "driveFileId": "drive-file-id-003",
    "fileName":    "malware.exe",
    "mimeType":    "application/x-msdownload",
    "category":    "client_uploads",
}


@pytest.fixture(autouse=True)
def reset_module_singletons():
    import main
    main._db = None
    main._gcs_client = None
    main._drive_service = None
    yield
    main._db = None
    main._gcs_client = None
    main._drive_service = None
