"""
api/services/bulk_import_service.py — Bulk lead import from Excel.

Pipeline (async, driven by Cloud Tasks — see tasks_service.py):
  1. create_import_job()   — validates the mapping structurally, stages the
                              file with storage-gateway's case-less upload
                              endpoint for virus scanning, creates the job
                              doc, enqueues the first scan-check task.
  2. handle_scan_check()   — polls storage-gateway's scan status. Re-enqueues
                              itself with backoff while pending/scanning.
                              Fails the whole job (no rows ever written) on
                              infected/error/timeout. On clean, fetches the
                              bytes, parses+maps rows into
                              lead_import_jobs/{jobId}/rows/{n}, and enqueues
                              row-processing chunk tasks.
  3. process_chunk()       — runs LeadRequest validation + the shared
                              case_service.process_lead_submission() pipeline
                              per row, best-effort (one bad row never blocks
                              the rest), writing lead_import_jobs/{jobId}/results/{n}.

AMBER zone (AI_ZONES.md) — same tier as case_service.py, whose
process_lead_submission() this drives per row.
"""
from __future__ import annotations

import datetime as dt
import math
import uuid
from typing import Any, Optional

from fastapi import HTTPException, status
from google.cloud import firestore
from google.cloud.firestore_v1 import AsyncTransaction
from pydantic import ValidationError

from config import Settings
from logging_config import get_logger
from models.bulk_import import (
    BulkImportRequest, ColumnMapping, LeadImportJobResponse,
    LeadImportJobResultsPage, LeadImportJobStatus, LeadImportJobSummary,
    RowImportResult, RowOutcome,
)
from models.lead import ErrorDetail, LeadRequest
from services import excel_parser, storage_gateway_client
from services.case_service import get_case, process_lead_submission
from services.duplicate_detection import is_idempotent_retry
from services.tasks_service import create_bulk_import_chunk_task, create_scan_check_task

logger = get_logger(__name__)

JOBS_COLLECTION = "lead_import_jobs"

# firstName/lastName/email/phone/exposureLocation/wtcHealthProgramStatus/
# priorAttorney are LeadRequest's own required top-level fields.
# exposureDates.{start,end} are required sub-fields. marketingSource is
# supplied by BulkImportRequest itself (applies to every row), not mapped
# per-column.
REQUIRED_LEAD_FIELDS: frozenset[str] = frozenset({
    "firstName", "lastName", "email", "phone", "exposureLocation",
    "exposureDates.start", "exposureDates.end",
    "wtcHealthProgramStatus", "priorAttorney",
})


# ── Stage 1: create the job ──────────────────────────────────────────────────

async def create_import_job(
    file_bytes: bytes,
    file_name:  str,
    mapping:    BulkImportRequest,
    partner_id: str,
    request_id: str,
    db:         firestore.AsyncClient,
    settings:   Settings,
    sa_email:   str,
) -> LeadImportJobResponse:
    if not file_name.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "INVALID_FILE", "message": "Only .xlsx files are supported.", "details": []},
        )

    _validate_mapping_completeness(mapping.columnMappings)

    real_headers = excel_parser.parse_header_row(
        file_bytes, mapping.sheetName, mapping.headerRowIndex,
    )
    _validate_headers_match(real_headers, mapping.columnMappings)

    content_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    reg = await storage_gateway_client.register_system_upload(
        settings=settings,
        file_name=file_name,
        content_type=content_type,
        size_bytes=len(file_bytes),
        context="bulk_lead_import",
    )
    await storage_gateway_client.put_file_bytes(reg["signed_url"], file_bytes, content_type)

    job_id = str(uuid.uuid4())
    now    = dt.datetime.now(tz=dt.timezone.utc)

    job_doc = {
        "jobId":            job_id,
        "status":           LeadImportJobStatus.QUEUED.value,
        "scanStatus":       "pending",
        "storageFileId":    reg["file_id"],
        "partnerId":        partner_id,
        "requestId":        request_id,
        "fileName":         file_name,
        "columnMappings":   [m.model_dump() for m in mapping.columnMappings],
        "sheetName":        mapping.sheetName,
        "headerRowIndex":   mapping.headerRowIndex,
        "marketingSource":  mapping.marketingSource,
        "defaultReferralCode": mapping.defaultReferralCode,
        "totalRows":        0,
        "processedRows":    0,
        "createdCount":     0,
        "skippedCount":     0,
        "failedCount":      0,
        "chunkCount":       0,
        "chunksCompleted":  0,
        "scanPollAttempts": 0,
        "createdAt":        now,
        "updatedAt":        now,
        "completedAt":      None,
        "errorMessage":     None,
    }
    await db.collection(JOBS_COLLECTION).document(job_id).set(job_doc)

    await create_scan_check_task(
        job_id=job_id, service_account_email=sa_email,
        delay_seconds=settings.bulk_import_scan_poll_delay_seconds,
    )

    logger.info("bulk_import_job_created", job_id=job_id, file_name=file_name, partner_id=partner_id)

    return _to_response(job_doc)


def _validate_mapping_completeness(column_mappings: list[ColumnMapping]) -> None:
    mapped_fields = {m.leadField for m in column_mappings}
    missing = REQUIRED_LEAD_FIELDS - mapped_fields
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_MAPPING",
                "message": "columnMappings is missing required LeadRequest fields.",
                "details": [
                    {"field": f, "code": "MISSING_MAPPING", "message": f"No column mapped to '{f}'"}
                    for f in sorted(missing)
                ],
            },
        )


def _validate_headers_match(real_headers: list[str], column_mappings: list[ColumnMapping]) -> None:
    real_set = set(real_headers)
    unmatched = [m.excelColumn for m in column_mappings if m.excelColumn not in real_set]
    if unmatched:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_MAPPING",
                "message": "Some mapped columns were not found in the uploaded file's header row.",
                "details": [
                    {"field": col, "code": "COLUMN_NOT_FOUND", "message": f"'{col}' not found. Available: {real_headers}"}
                    for col in unmatched
                ],
            },
        )


# ── Stage 2: wait for the virus scan, then parse + enqueue chunks ──────────────

async def handle_scan_check(
    job_id:   str,
    db:       firestore.AsyncClient,
    settings: Settings,
    sa_email: str,
) -> dict:
    job_ref  = db.collection(JOBS_COLLECTION).document(job_id)
    job_snap = await job_ref.get()
    if not job_snap.exists:
        logger.warning("bulk_import_scan_check_job_not_found", job_id=job_id)
        return {"status": "not_found"}

    job = job_snap.to_dict()
    if job.get("status") == LeadImportJobStatus.CANCELLED.value:
        return {"status": "cancelled"}

    status_resp = await storage_gateway_client.get_upload_status(settings, job["storageFileId"])
    scan_status = status_resp.get("scan_status", "pending")
    now         = dt.datetime.now(tz=dt.timezone.utc)

    if scan_status in ("pending", "scanning"):
        attempts = job.get("scanPollAttempts", 0) + 1
        if attempts >= settings.bulk_import_scan_poll_max_attempts:
            await _fail_job(job_ref, "Virus scan timed out.", now)
            logger.error("bulk_import_scan_timeout", job_id=job_id)
            return {"status": "scan_timeout"}

        await job_ref.update({
            "scanStatus": scan_status,
            "status": LeadImportJobStatus.SCANNING.value,
            "scanPollAttempts": attempts,
            "updatedAt": now,
        })
        await create_scan_check_task(
            job_id=job_id, service_account_email=sa_email,
            delay_seconds=settings.bulk_import_scan_poll_delay_seconds,
        )
        return {"status": "still_scanning", "attempts": attempts}

    if scan_status in ("infected", "error"):
        message = (
            "Uploaded file failed the virus scan and was rejected."
            if scan_status == "infected"
            else "Virus scan failed unexpectedly."
        )
        await _fail_job(job_ref, message, now, scan_status=scan_status)
        logger.warning("bulk_import_scan_rejected", job_id=job_id, scan_status=scan_status)
        return {"status": scan_status}

    # scan_status == "clean"
    read_url_resp = await storage_gateway_client.get_system_upload_read_url(settings, job["storageFileId"])
    file_bytes    = await storage_gateway_client.fetch_bytes(read_url_resp["signed_url"])

    sheet_name       = job.get("sheetName")
    header_row_index = job.get("headerRowIndex", 0)
    column_mappings  = [ColumnMapping(**m) for m in job.get("columnMappings", [])]
    marketing_source = job.get("marketingSource")
    default_referral = job.get("defaultReferralCode")

    rows_collection = job_ref.collection("rows")
    total_rows = 0
    batch = db.batch()
    batch_ops = 0

    for row_number, raw_row in enumerate(
        excel_parser.iter_rows(file_bytes, sheet_name, header_row_index), start=1,
    ):
        mapped = _apply_mapping(raw_row, column_mappings, marketing_source, default_referral)
        mapped["rowNumber"] = row_number
        doc_id = f"{row_number:04d}"
        batch.set(rows_collection.document(doc_id), _serialize_for_firestore(mapped))
        total_rows += 1
        batch_ops += 1

        if batch_ops >= 500:
            await batch.commit()
            batch = db.batch()
            batch_ops = 0

    if batch_ops:
        await batch.commit()

    if total_rows == 0:
        await _fail_job(job_ref, "No data rows found in the uploaded file.", now, scan_status="clean")
        return {"status": "no_rows"}

    chunk_size  = settings.bulk_import_chunk_size
    chunk_count = math.ceil(total_rows / chunk_size)

    await job_ref.update({
        "status":      LeadImportJobStatus.PROCESSING.value,
        "scanStatus":  "clean",
        "totalRows":   total_rows,
        "chunkCount":  chunk_count,
        "updatedAt":   now,
    })

    for i in range(chunk_count):
        row_start = i * chunk_size + 1
        row_end   = min((i + 1) * chunk_size, total_rows) + 1  # exclusive
        await create_bulk_import_chunk_task(
            job_id=job_id, row_start=row_start, row_end=row_end,
            service_account_email=sa_email,
        )

    logger.info("bulk_import_scan_clean_processing_started", job_id=job_id, total_rows=total_rows, chunk_count=chunk_count)
    return {"status": "processing_started", "totalRows": total_rows, "chunkCount": chunk_count}


async def _fail_job(job_ref, message: str, now: dt.datetime, scan_status: Optional[str] = None) -> None:
    update = {
        "status":       LeadImportJobStatus.FAILED.value,
        "errorMessage": message,
        "completedAt":  now,
        "updatedAt":    now,
    }
    if scan_status is not None:
        update["scanStatus"] = scan_status
    await job_ref.update(update)


def _apply_mapping(
    raw_row:          dict[str, Any],
    column_mappings:  list[ColumnMapping],
    marketing_source: Optional[str],
    default_referral: Optional[str],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if marketing_source:
        result["marketingSource"] = marketing_source
    if default_referral:
        result["referralCode"] = default_referral

    for m in column_mappings:
        value = raw_row.get(m.excelColumn)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            continue
        _set_nested(result, m.leadField.split("."), value)

    return result


def _set_nested(target: dict[str, Any], path: list[str], value: Any) -> None:
    for key in path[:-1]:
        target = target.setdefault(key, {})
    target[path[-1]] = value


def _serialize_for_firestore(value: Any) -> Any:
    """Firestore's Python client doesn't accept bare datetime.date — convert
    date/datetime cell values to ISO strings (Pydantic parses those back into
    date fields fine when the row is validated in process_chunk)."""
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize_for_firestore(v) for k, v in value.items()}
    return value


# ── Stage 3: process one chunk of rows ──────────────────────────────────────

async def process_chunk(
    job_id:    str,
    row_start: int,
    row_end:   int,
    db:        firestore.AsyncClient,
    sa_email:  str,
) -> dict:
    job_ref  = db.collection(JOBS_COLLECTION).document(job_id)
    job_snap = await job_ref.get()
    if not job_snap.exists:
        logger.warning("bulk_import_chunk_job_not_found", job_id=job_id)
        return {"status": "not_found"}

    job = job_snap.to_dict()
    if job.get("status") == LeadImportJobStatus.CANCELLED.value:
        return {"status": "cancelled"}

    partner_id = job["partnerId"]
    rows_ref    = job_ref.collection("rows")
    results_ref = job_ref.collection("results")

    created = skipped = failed = 0

    for n in range(row_start, row_end):
        doc_id = f"{n:04d}"
        result_ref = results_ref.document(doc_id)

        # Idempotency guard: a previous (possibly crashed) delivery of this
        # chunk task may have already processed this row.
        if (await result_ref.get()).exists:
            continue

        row_snap = await rows_ref.document(doc_id).get()
        if not row_snap.exists:
            continue

        row_data   = row_snap.to_dict()
        row_number = row_data.pop("rowNumber", n)
        row_request_id = f"{job_id}:{row_number}"

        try:
            lead = LeadRequest(**row_data)
        except ValidationError as exc:
            await result_ref.set(RowImportResult(
                rowNumber=row_number, outcome=RowOutcome.FAILED,
                error=ErrorDetail(field="row", code="VALIDATION_ERROR",
                                   message=_sanitize_validation_error(exc)),
            ).model_dump(mode="json"))
            failed += 1
            continue

        try:
            existing_case_id = await is_idempotent_retry(row_request_id, db)
            if existing_case_id:
                case = await get_case(existing_case_id, db)
                await result_ref.set(RowImportResult(
                    rowNumber=row_number, outcome=RowOutcome.CREATED,
                    caseId=existing_case_id,
                    vcfScreeningStatus=case.vcfEligibility if case else None,
                ).model_dump(mode="json"))
                created += 1
                continue

            resp = await process_lead_submission(
                lead=lead, partner_id=partner_id, request_id=row_request_id,
                db=db, sa_email=sa_email,
            )
            await result_ref.set(RowImportResult(
                rowNumber=row_number, outcome=RowOutcome.CREATED,
                caseId=resp.leadId, vcfScreeningStatus=resp.vcfScreeningStatus,
            ).model_dump(mode="json"))
            created += 1
        except HTTPException as exc:
            detail  = exc.detail if isinstance(exc.detail, dict) else {}
            message = detail.get("message", str(exc.detail))
            if exc.status_code == status.HTTP_409_CONFLICT:
                await result_ref.set(RowImportResult(
                    rowNumber=row_number, outcome=RowOutcome.SKIPPED_DUPLICATE,
                    error=ErrorDetail(field="email+phone", code="DUPLICATE_LEAD", message=message),
                ).model_dump(mode="json"))
                skipped += 1
            else:
                await result_ref.set(RowImportResult(
                    rowNumber=row_number, outcome=RowOutcome.FAILED,
                    error=ErrorDetail(field="row", code=detail.get("error", "ERROR"), message=message),
                ).model_dump(mode="json"))
                failed += 1
        except Exception as exc:
            logger.error("bulk_import_row_failed", job_id=job_id, row_number=row_number, error=str(exc))
            await result_ref.set(RowImportResult(
                rowNumber=row_number, outcome=RowOutcome.FAILED,
                error=ErrorDetail(field="row", code="INTERNAL_ERROR", message="Unexpected error processing this row."),
            ).model_dump(mode="json"))
            failed += 1

    await _record_chunk_completion(db, job_id, created, skipped, failed)
    logger.info("bulk_import_chunk_processed", job_id=job_id, row_start=row_start, row_end=row_end,
                created=created, skipped=skipped, failed=failed)
    return {"status": "processed", "jobId": job_id, "created": created, "skipped": skipped, "failed": failed}


def _sanitize_validation_error(exc: ValidationError) -> str:
    """Field path + message only — never include exc's raw input_value,
    which may contain the row's PII (email/phone/ssn/etc)."""
    parts = []
    for err in exc.errors():
        field = ".".join(str(loc) for loc in err["loc"])
        parts.append(f"{field}: {err['msg']}")
    return "; ".join(parts)[:500]


async def _record_chunk_completion(
    db: firestore.AsyncClient, job_id: str, created: int, skipped: int, failed: int,
) -> None:
    job_ref = db.collection(JOBS_COLLECTION).document(job_id)
    now     = dt.datetime.now(tz=dt.timezone.utc)
    processed = created + skipped + failed

    @firestore.async_transactional
    async def _txn(transaction: AsyncTransaction) -> None:
        snap = await job_ref.get(transaction=transaction)
        job  = snap.to_dict()

        chunks_completed = job.get("chunksCompleted", 0) + 1
        chunk_count       = job.get("chunkCount", 0)

        update = {
            "processedRows":   job.get("processedRows", 0) + processed,
            "createdCount":    job.get("createdCount", 0) + created,
            "skippedCount":    job.get("skippedCount", 0) + skipped,
            "failedCount":     job.get("failedCount", 0) + failed,
            "chunksCompleted": chunks_completed,
            "updatedAt":       now,
        }
        if chunks_completed >= chunk_count and job.get("status") != LeadImportJobStatus.FAILED.value:
            update["status"]      = LeadImportJobStatus.SUCCEEDED.value
            update["completedAt"] = now

        transaction.update(job_ref, update)

    transaction = db.transaction()
    await _txn(transaction)


# ── Read helpers ──────────────────────────────────────────────────────────────

async def get_job(job_id: str, db: firestore.AsyncClient) -> Optional[LeadImportJobResponse]:
    snap = await db.collection(JOBS_COLLECTION).document(job_id).get()
    if not snap.exists:
        return None
    return _to_response(snap.to_dict())


async def list_job_results(
    job_id: str, db: firestore.AsyncClient,
    page_size: int = 100, page_token: Optional[str] = None,
    outcome: Optional[str] = None,
) -> LeadImportJobResultsPage:
    query = db.collection(JOBS_COLLECTION).document(job_id).collection("results").order_by("rowNumber")
    if outcome:
        query = query.where("outcome", "==", outcome)
    if page_token:
        cursor_doc = await db.collection(JOBS_COLLECTION).document(job_id).collection("results").document(page_token).get()
        if cursor_doc.exists:
            query = query.start_after(cursor_doc)

    query = query.limit(page_size + 1)
    docs  = [doc async for doc in query.stream()]
    has_more = len(docs) > page_size
    if has_more:
        docs = docs[:page_size]

    results = [RowImportResult(**doc.to_dict()) for doc in docs]
    return LeadImportJobResultsPage(
        jobId=job_id,
        results=results,
        nextPageToken=docs[-1].id if has_more and docs else None,
    )


def _to_response(job: dict) -> LeadImportJobResponse:
    return LeadImportJobResponse(
        jobId=job["jobId"],
        status=LeadImportJobStatus(job["status"]),
        scanStatus=job.get("scanStatus"),
        summary=LeadImportJobSummary(
            totalRows=job.get("totalRows", 0),
            processed=job.get("processedRows", 0),
            created=job.get("createdCount", 0),
            skipped=job.get("skippedCount", 0),
            failed=job.get("failedCount", 0),
        ),
        createdAt=job["createdAt"],
        updatedAt=job["updatedAt"],
        completedAt=job.get("completedAt"),
        fileName=job["fileName"],
        partnerId=job["partnerId"],
        requestId=job["requestId"],
        errorMessage=job.get("errorMessage"),
    )
