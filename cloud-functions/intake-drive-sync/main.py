"""
SimpleTort — Intake Drive Sync Cloud Function

HTTP trigger. Called by Apps Script immediately after a successful intake form
submission. Downloads each uploaded file from Google Drive (where Google Forms
deposits them) and uploads it to the correct GCS path. Creates and updates
Firestore cases/{caseId}/documents records.

Endpoint: POST /sync
Body:
  {
    "caseId":  "ZAD-2026-03-0001",
    "tokenId": "uuid-v4",
    "files": [
      {
        "driveFileId": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OmWZ",
        "fileName":    "medical_record.pdf",
        "mimeType":    "application/pdf",
        "category":    "medical_records"
      }
    ]
  }

Response:
  {
    "synced": [{ "docId": "...", "gcsPath": "...", "category": "...", "status": "uploaded" }],
    "errors": [{ "driveFileId": "...", "error": "..." }]
  }
  HTTP 200 — all files synced
  HTTP 207 — partial success
  HTTP 500 — all files failed

Auth: shared secret. Apps Script passes Authorization: Bearer <DRIVE_SYNC_SECRET>.

Environment variables:
  GCP_PROJECT_ID         — GCP project ID
  GCS_BUCKET_NAME        — e.g. zadroga-case-files-simpletort-prod
  FIRESTORE_DATABASE_ID  — default: (default)
  DRIVE_SYNC_SECRET      — shared secret (must match Apps Script constant)
"""

import logging
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import flask
import functions_framework
from google.cloud import firestore, storage as gcs

try:
    from google.auth import default as google_auth_default
    import googleapiclient.discovery
    import googleapiclient.http as gapi_http

    _DRIVE_AVAILABLE = True
except ImportError:
    _DRIVE_AVAILABLE = False

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
PROJECT_ID = os.environ["GCP_PROJECT_ID"]
BUCKET_NAME = os.environ["GCS_BUCKET_NAME"]
FIRESTORE_DB = os.environ.get("FIRESTORE_DATABASE_ID", "(default)")
DRIVE_SYNC_SECRET = os.environ.get("DRIVE_SYNC_SECRET", "")

# File validation constants — mirrored from shared/shared/middlewares/file_validation.py.
# Keep in sync with that file if limits change.
ALLOWED_MIME_TYPES: frozenset[str] = frozenset({
    "application/pdf",
    "image/jpeg",
    "image/png",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
})
MAX_FILE_SIZE_BYTES: int = 25 * 1024 * 1024  # 25 MB

# Valid document categories — used for validation only.
# The permanent GCS path is determined by the virus-scanner after a clean scan,
# using the category stored in the Firestore document record.
VALID_CATEGORIES: frozenset[str] = frozenset({
    "medical_records",
    "proof_of_presence",
    "id_documents",
    "legal_forms",
    "vcf_documents",
    "settlement_docs",
    "client_uploads",
})

# Module-level singletons
_db: firestore.Client | None = None
_gcs_client: gcs.Client | None = None
_drive_service = None


def _get_db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client(project=PROJECT_ID, database=FIRESTORE_DB)
    return _db


def _get_gcs() -> gcs.Client:
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = gcs.Client(project=PROJECT_ID)
    return _gcs_client


def _get_drive_service():
    """Build Drive API client using Application Default Credentials."""
    global _drive_service
    if _drive_service is None:
        if not _DRIVE_AVAILABLE:
            raise RuntimeError("google-api-python-client not installed")
        credentials, _ = google_auth_default(
            scopes=["https://www.googleapis.com/auth/drive.readonly"]
        )
        _drive_service = googleapiclient.discovery.build(
            "drive", "v3", credentials=credentials, cache_discovery=False
        )
    return _drive_service


def _download_drive_file(drive_service, drive_file_id: str, dest_path: str) -> None:
    """Download a Drive file to dest_path via the Drive API."""
    request = drive_service.files().get_media(fileId=drive_file_id)
    with open(dest_path, "wb") as fh:
        downloader = gapi_http.MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()


def _upload_to_staging(local_path: str, staging_path: str, mime_type: str) -> None:
    """Upload local_path to the GCS staging/ prefix.

    Staging uploads intentionally do NOT set temporary_hold — the virus-scanner
    Eventarc trigger owns the file from here: it scans, moves to the permanent
    path, sets the hold, and updates the Firestore document record.
    """
    bucket = _get_gcs().bucket(BUCKET_NAME)
    blob = bucket.blob(staging_path)
    blob.upload_from_filename(local_path, content_type=mime_type)


# ── HTTP Cloud Function entry point ───────────────────────────────────────────

@functions_framework.http
def sync_drive_files(request: flask.Request) -> flask.Response:
    """POST /sync — download Drive files and push to GCS."""

    # CORS preflight
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
    }
    if request.method == "OPTIONS":
        return flask.Response(status=204, headers=cors_headers)

    if request.method != "POST":
        return flask.make_response(
            flask.jsonify({"error": "Method not allowed"}), 405, cors_headers
        )

    # Verify shared secret
    if DRIVE_SYNC_SECRET:
        auth_header = request.headers.get("Authorization", "")
        if auth_header != "Bearer {}".format(DRIVE_SYNC_SECRET):
            logger.warning("sync_drive_files: unauthorized request from %s",
                           request.headers.get("X-Forwarded-For", "unknown"))
            return flask.make_response(
                flask.jsonify({"error": "Unauthorized"}), 401, cors_headers
            )

    # Parse body
    try:
        body = request.get_json(force=True) or {}
    except Exception:
        return flask.make_response(
            flask.jsonify({"error": "Invalid JSON body"}), 400, cors_headers
        )

    case_id: str = body.get("caseId", "").strip()
    token_id: str = body.get("tokenId", "").strip()
    files: list = body.get("files", [])

    if not case_id or not token_id:
        return flask.make_response(
            flask.jsonify({"error": "caseId and tokenId are required"}),
            400,
            cors_headers,
        )

    if not files:
        logger.info("sync_drive_files: no files to sync for case %s", case_id)
        return flask.make_response(
            flask.jsonify({"synced": [], "errors": []}), 200, cors_headers
        )

    db = _get_db()

    # Verify token exists and belongs to this case
    token_snap = db.collection("intake_tokens").document(token_id).get()
    if not token_snap.exists or token_snap.to_dict().get("caseId") != case_id:
        logger.error(
            "sync_drive_files: invalid token=%s for case=%s", token_id, case_id
        )
        return flask.make_response(
            flask.jsonify({"error": "Invalid token or case mismatch"}),
            403,
            cors_headers,
        )

    # Build Drive service once for the request
    try:
        drive_service = _get_drive_service()
    except Exception as exc:
        logger.error("sync_drive_files: Drive service init failed: %s", exc)
        return flask.make_response(
            flask.jsonify({"error": "Drive service unavailable: {}".format(exc)}),
            503,
            cors_headers,
        )

    synced: list[dict] = []
    errors: list[dict] = []

    for file_info in files:
        drive_file_id: str = file_info.get("driveFileId", "").strip()
        file_name: str = file_info.get("fileName", "unknown_file").strip()
        mime_type: str = file_info.get("mimeType", "application/octet-stream")
        category: str = file_info.get("category", "client_uploads")

        if not drive_file_id:
            errors.append({"driveFileId": drive_file_id, "error": "Missing driveFileId"})
            continue

        # Validate MIME type against allowed list (mirrors shared/middlewares/file_validation.py)
        if mime_type not in ALLOWED_MIME_TYPES:
            logger.warning(
                "Rejected file with unsupported MIME type '%s': case=%s drive=%s",
                mime_type, case_id, drive_file_id,
            )
            errors.append({
                "driveFileId": drive_file_id,
                "error": "Unsupported file type '{}'. Allowed: {}".format(
                    mime_type, ", ".join(sorted(ALLOWED_MIME_TYPES))
                ),
            })
            continue

        if category not in VALID_CATEGORIES:
            logger.warning(
                "Unknown category '%s' for case=%s — falling back to client_uploads",
                category,
                case_id,
            )
            category = "client_uploads"

        doc_id = str(uuid.uuid4())
        # Upload target is staging/ — virus-scanner Eventarc trigger picks it up,
        # scans the file, moves it to the permanent path, and updates Firestore.
        # Never upload directly to the permanent path from here.
        staging_path = "staging/{}/{}".format(doc_id, file_name)
        now = datetime.now(tz=timezone.utc)

        # Create placeholder Firestore record.
        # gcsPath stays None and processingStatus stays "pending_gcs_transfer"
        # until the virus-scanner updates them after a clean scan.
        doc_ref = (
            db.collection("cases")
            .document(case_id)
            .collection("documents")
            .document(doc_id)
        )
        doc_ref.set(
            {
                "fileName": file_name,
                "category": category,
                "gcsPath": None,
                "mimeType": mime_type,
                "sizeBytes": None,
                "uploadedBy": "intake-form",
                "uploadedAt": now,
                "processingStatus": "pending_gcs_transfer",
                "verificationStatus": "Unverified",
                "scanStatus": "pending",
                "driveFileId": drive_file_id,
                "extractedData": None,
                "documentAiResults": None,
                "medicalAiResults": None,
                "manualOverrides": [],
            }
        )

        # Download from Drive → upload to GCS staging/
        suffix = Path(file_name).suffix or ".bin"
        tmp_path: str | None = None

        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp_path = tmp.name

            _download_drive_file(drive_service, drive_file_id, tmp_path)
            size_bytes = Path(tmp_path).stat().st_size

            # Validate file size after download (mirrors shared/middlewares/file_validation.py)
            if size_bytes > MAX_FILE_SIZE_BYTES:
                logger.warning(
                    "Rejected oversized file (%d bytes > %d): case=%s drive=%s",
                    size_bytes, MAX_FILE_SIZE_BYTES, case_id, drive_file_id,
                )
                errors.append({
                    "driveFileId": drive_file_id,
                    "error": "File size {} MB exceeds maximum {} MB".format(
                        round(size_bytes / 1024 / 1024, 1),
                        MAX_FILE_SIZE_BYTES // 1024 // 1024,
                    ),
                })
                continue

            _upload_to_staging(tmp_path, staging_path, mime_type)

            # Record file size now; virus-scanner updates gcsPath + processingStatus
            # after the scan completes and it moves the file to the permanent path.
            doc_ref.update({"sizeBytes": size_bytes})

            logger.info(
                "File staged: case=%s docId=%s drive=%s staging=%s",
                case_id,
                doc_id,
                drive_file_id,
                staging_path,
            )
            synced.append(
                {
                    "docId": doc_id,
                    "stagingPath": staging_path,
                    "category": category,
                    "status": "pending_scan",
                }
            )

        except Exception as exc:
            logger.error(
                "File sync failed: case=%s drive=%s error=%s",
                case_id,
                drive_file_id,
                exc,
            )
            doc_ref.update(
                {
                    "processingStatus": "transfer_failed",
                    "transferError": str(exc)[:512],
                }
            )
            errors.append({"driveFileId": drive_file_id, "error": str(exc)[:256]})

        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    logger.info(
        "sync_drive_files complete: case=%s synced=%d errors=%d",
        case_id,
        len(synced),
        len(errors),
    )

    if errors and not synced:
        status_code = 500
    elif errors:
        status_code = 207  # partial success
    else:
        status_code = 200

    return flask.make_response(
        flask.jsonify({"synced": synced, "errors": errors}),
        status_code,
        cors_headers,
    )
