"""
SimpleTort — Virus Scanner Cloud Function (Gen 2)

Trigger: GCS Eventarc — google.cloud.storage.object.v1.finalized
         on bucket: zadroga-case-files-{PROJECT_ID}
         path filter: staging/**

Flow:
  1. Extract fileId from blob path  (staging/{fileId}/{fileName})
  2. Read file_uploads/{fileId} from Firestore → get caseId, finalPath, etc.
  3. Update scan_status = "scanning"
  4. Download blob to /tmp
  5. Run ClamAV via scanner.scan_file()
  6a. CLEAN  → copy staging → finalPath, delete staging blob
               update file_uploads + cases/.../documents with scan_status=clean
  6b. INFECTED → copy staging → quarantine/{timestamp}/{fileId}/{fileName}
                 delete staging blob
                 update Firestore scan_status=infected, isQuarantined=True
                 publish to Pub/Sub virus-detected topic
  7. Delete /tmp file

Environment variables (set via --set-env-vars in deploy.sh):
  GCP_PROJECT_ID          — GCP project
  GCS_BUCKET_NAME         — storage bucket
  GCS_QUARANTINE_PREFIX   — default: quarantine
  PUBSUB_TOPIC_VIRUS_DETECTED — default: virus-detected
  FIRESTORE_DATABASE_ID   — default: (default)
"""

import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import functions_framework
from cloudevents.http import CloudEvent
from google.cloud import firestore, storage as gcs

from notifier import publish_virus_detected
from scanner import ScanResult, scan_file

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── Configuration from environment ────────────────────────────────────────
PROJECT_ID = os.environ["GCP_PROJECT_ID"]
BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "zadroga-case-files-{}".format(PROJECT_ID))
QUARANTINE_PREFIX = os.environ.get("GCS_QUARANTINE_PREFIX", "quarantine")
PUBSUB_TOPIC = os.environ.get("PUBSUB_TOPIC_VIRUS_DETECTED", "virus-detected")
FIRESTORE_DB = os.environ.get("FIRESTORE_DATABASE_ID", "(default)")

_gcs_client: gcs.Client | None = None
_db: firestore.Client | None = None


def _get_gcs() -> gcs.Client:
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = gcs.Client(project=PROJECT_ID)
    return _gcs_client


def _get_db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client(project=PROJECT_ID, database=FIRESTORE_DB)
    return _db


# ── Cloud Function entry point ─────────────────────────────────────────────

@functions_framework.cloud_event
def virus_scan(event: CloudEvent) -> None:
    """
    Triggered by a GCS object-finalize event via Eventarc.
    event.data contains: bucket, name, contentType, size, metageneration, etc.
    """
    data = event.data
    bucket_name: str = data["bucket"]
    blob_path: str = data["name"]

    logger.info("virus_scan triggered: bucket=%s blob=%s", bucket_name, blob_path)

    # Only process files in the staging prefix
    if not blob_path.startswith("staging/"):
        logger.info("Ignoring non-staging blob: %s", blob_path)
        return

    # ── Parse fileId from path: staging/{fileId}/{fileName} ───────────────
    parts = blob_path.split("/")
    if len(parts) < 3:
        logger.error("Unexpected staging path format: %s", blob_path)
        return

    file_id = parts[1]
    file_name = "/".join(parts[2:])     # handles filenames with slashes (rare)

    # ── Load Firestore record ──────────────────────────────────────────────
    db = _get_db()
    upload_ref = db.collection("file_uploads").document(file_id)
    upload_snap = upload_ref.get()

    if not upload_snap.exists:
        logger.error("No file_uploads record for fileId=%s blob=%s", file_id, blob_path)
        return

    upload_data = upload_snap.to_dict()

    # Skip re-processing if a previous invocation already completed the scan.
    existing_status = upload_data.get("scanStatus")
    if existing_status in ("clean", "infected"):
        logger.info(
            "Skipping re-scan: fileId=%s already has scanStatus=%s",
            file_id, existing_status,
        )
        return

    case_id: str | None = upload_data.get("caseId")
    category: str = upload_data.get("category", "")
    final_path: str = upload_data.get("finalPath", "")
    uploaded_by: str = upload_data.get("uploadedBy", "unknown")

    # ── Mark as scanning ──────────────────────────────────────────────────
    upload_ref.update({"scanStatus": "scanning"})
    if case_id:
        _case_doc_ref(db, case_id, file_id).update({"scanStatus": "scanning"})

    # ── Download to /tmp ──────────────────────────────────────────────────
    bucket = _get_gcs().bucket(bucket_name)
    blob = bucket.blob(blob_path)

    with tempfile.NamedTemporaryFile(
        suffix=Path(file_name).suffix or ".bin", delete=False
    ) as tmp_file:
        tmp_path = tmp_file.name

    try:
        blob.download_to_filename(tmp_path)
        logger.info("Downloaded %s → %s", blob_path, tmp_path)
    except Exception as exc:
        logger.error("Download failed for %s: %s", blob_path, exc)
        if upload_data.get("scanStatus") in ("clean", "infected"):
            logger.info(
                "Staging file gone but scan already completed "
                "(scanStatus=%s); ignoring download error for fileId=%s",
                upload_data.get("scanStatus"), file_id,
            )
            return
        _mark_error(upload_ref, db, case_id, file_id, str(exc))
        return

    # ── Scan ───────────────────────────────────────────────────────────────
    try:
        result: ScanResult = scan_file(tmp_path)
    except Exception as exc:
        logger.error("Unexpected scan exception for %s: %s", blob_path, exc)
        _cleanup_tmp(tmp_path)
        _mark_error(upload_ref, db, case_id, file_id, str(exc))
        return
    finally:
        _cleanup_tmp(tmp_path)

    scan_completed_at = datetime.now(tz=timezone.utc)

    if result.is_clean:
        _handle_clean(
            bucket=bucket,
            staging_blob=blob,
            blob_path=blob_path,
            final_path=final_path,
            upload_ref=upload_ref,
            db=db,
            case_id=case_id,
            file_id=file_id,
            raw_output=result.raw_output,
            scan_completed_at=scan_completed_at,
        )
    else:
        _handle_infected(
            bucket=bucket,
            staging_blob=blob,
            blob_path=blob_path,
            upload_ref=upload_ref,
            db=db,
            case_id=case_id,
            file_id=file_id,
            file_name=file_name,
            category=category,
            uploaded_by=uploaded_by,
            threat=result.threat or "UNKNOWN",
            raw_output=result.raw_output,
            scan_completed_at=scan_completed_at,
        )


# ── Outcome handlers ───────────────────────────────────────────────────────

def _handle_clean(
    *,
    bucket: gcs.Bucket,
    staging_blob: gcs.Blob,
    blob_path: str,
    final_path: str,
    upload_ref,
    db: firestore.Client,
    case_id: str | None,
    file_id: str,
    raw_output: str,
    scan_completed_at: datetime,
) -> None:
    logger.info("Clean scan — moving %s → %s", blob_path, final_path)

    # Copy to permanent location
    bucket.copy_blob(staging_blob, bucket, final_path)
    # Delete staging object
    staging_blob.delete()

    # Protect the permanent file from lifecycle transitions until the case is
    # closed/settled.  temporaryHold=True means GCS will skip NEARLINE/COLDLINE
    # transitions and deletion for this object regardless of age.
    # Custom metadata provides a human-readable label in the GCS console.
    if case_id:
        dest_blob = bucket.blob(final_path)
        dest_blob.temporary_hold = True
        dest_blob.metadata = {"case-status": "active"}
        dest_blob.patch()
        logger.info(
            "Temporary hold set on permanent file: fileId=%s path=%s",
            file_id, final_path,
        )

    if case_id:
        _case_doc_ref(db, case_id, file_id).update({
            "scanStatus": "clean",
            "gcsPath": final_path,
            "scanCompletedAt": scan_completed_at,
        })

    updates = {
        "scanStatus": "clean",
        "scanCompletedAt": scan_completed_at,
        "scanResult": raw_output[:2048],    # cap stored output size
    }
    upload_ref.update(updates)

    logger.info("Clean file finalised: fileId=%s path=%s", file_id, final_path)


def _handle_infected(
    *,
    bucket: gcs.Bucket,
    staging_blob: gcs.Blob,
    blob_path: str,
    upload_ref,
    db: firestore.Client,
    case_id: str | None,
    file_id: str,
    file_name: str,
    category: str,
    uploaded_by: str,
    threat: str,
    raw_output: str,
    scan_completed_at: datetime,
) -> None:
    timestamp_str = scan_completed_at.strftime("%Y%m%dT%H%M%S")
    quarantine_path = "{}/{}/{}/{}".format(
        QUARANTINE_PREFIX, timestamp_str, file_id, file_name
    )

    logger.warning(
        "Infected file detected — quarantining: fileId=%s threat=%s path=%s",
        file_id, threat, quarantine_path,
    )

    # Copy to quarantine, then delete staging
    try:
        bucket.copy_blob(staging_blob, bucket, quarantine_path)
    except Exception as exc:
        logger.error("Quarantine copy failed for %s: %s", blob_path, exc)
        quarantine_path = None

    try:
        staging_blob.delete()
    except Exception as exc:
        logger.error("Staging delete failed for %s: %s", blob_path, exc)

    if case_id:
        _case_doc_ref(db, case_id, file_id).update({
            "scanStatus": "infected",
            "isQuarantined": True,
            "scanCompletedAt": scan_completed_at,
        })

    updates = {
        "scanStatus": "infected",
        "scanCompletedAt": scan_completed_at,
        "scanResult": raw_output[:2048],
        "isQuarantined": True,
        "quarantinePath": quarantine_path,
    }
    upload_ref.update(updates)

    # Pub/Sub notification (non-fatal)
    publish_virus_detected(
        project_id=PROJECT_ID,
        topic_name=PUBSUB_TOPIC,
        file_id=file_id,
        case_id=case_id,
        file_name=file_name,
        category=category,
        uploaded_by=uploaded_by,
        staging_path=blob_path,
        quarantine_path=quarantine_path or "",
        threat=threat,
    )


# ── Helpers ────────────────────────────────────────────────────────────────

def _case_doc_ref(db: firestore.Client, case_id: str, file_id: str):
    return (
        db.collection("cases")
        .document(case_id)
        .collection("documents")
        .document(file_id)
    )


def _mark_error(upload_ref, db: firestore.Client, case_id: str | None, file_id: str, detail: str) -> None:
    upload_ref.update({"scanStatus": "error", "scanResult": detail[:2048]})
    if case_id:
        _case_doc_ref(db, case_id, file_id).update({"scanStatus": "error"})


def _cleanup_tmp(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass
