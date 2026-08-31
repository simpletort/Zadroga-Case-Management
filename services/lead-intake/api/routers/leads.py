"""
api/routers/leads.py — Lead ingestion and management endpoints.

All messaging (SMS) is handled by the notification service via Pub/Sub.
lead-intake publishes events and writes to Firestore. It does not call
the notification service directly.

POST /leads flow:
  1. Validate → deduplicate → create case (Firestore transaction)
  2. Inline VCF screening (synchronous)
  3. Write VCF result to Firestore case document
  4. Write staff in-app notification to /notifications (Firestore write)
  5. Publish lead-created  → notification service sends welcome_sms
  6. Publish lead-screened → audit trail
  7. Enqueue 48h Cloud Task → /internal/tasks/followup
  8. Return 201 with eligibility immediately

/internal/tasks/followup flow (48h later):
  1. Create Admin Staff task in /tasks (Firestore write)
  2. Publish lead-followup → notification service sends followup_sms

Route order: static paths must come before /{lead_id}
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from google.auth.transport import requests as google_requests
from google.cloud import firestore
from google.oauth2 import id_token

from config import get_settings
from logging_config import get_logger
from middleware.auth import PartnerContext, get_partner
from middleware.rate_limiter import limiter
from models.bulk_import import BulkImportRequest, LeadImportJobResponse, LeadImportJobResultsPage
from models.lead import (
    CaseDocument, CaseStatus,
    LeadCreatedResponse, LeadRequest, UpdateStatusRequest, VCFEligibility,
)
from services import bulk_import_service
from services.case_service import (
    get_case, update_case_status, process_lead_submission,
    assign_case_transactional, AssignmentConflict,
)
from services.duplicate_detection import is_idempotent_retry
from services.firestore_client import get_db
from services.pubsub_service import publish_lead_followup

logger    = get_logger(__name__)
router    = APIRouter(prefix="/leads", tags=["Leads"])
_settings = get_settings()

_TASKS_SA_EMAIL = (
    _settings.cloud_tasks_sa_email
    or f"lead-intake-service-account@{_settings.gcp_project_id}.iam.gserviceaccount.com"
)


# ── POST /leads ───────────────────────────────────────────────────────────────

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=LeadCreatedResponse,
    summary="Ingest a new lead",
)
@limiter.limit(f"{_settings.rate_limit_requests}/minute")
async def create_lead(
    request: Request,
    lead:    LeadRequest,
    partner: PartnerContext = Depends(get_partner),
    db:      firestore.AsyncClient = Depends(get_db),
) -> LeadCreatedResponse:
    request_id = str(uuid.uuid4())
    logger.info("lead_intake_started", request_id=request_id, partner_id=partner.partner_id)

    # Idempotency — same X-Request-ID returns the original case
    client_request_id = request.headers.get("X-Request-ID")
    if client_request_id:
        existing_id = await is_idempotent_retry(client_request_id, db)
        if existing_id:
            case = await get_case(existing_id, db)
            return LeadCreatedResponse(
                leadId=existing_id,
                status=case.status if case else CaseStatus.NEW_LEAD,
                vcfScreeningStatus=case.vcfEligibility if case else VCFEligibility.PENDING,
                requestId=client_request_id,
                timestamp=datetime.utcnow(),
            )

    # Dedup checks -> create case -> VCF screening -> notification -> pubsub
    # -> follow-up task enqueue. Shared with the bulk-import row worker so
    # both paths behave identically (services/case_service.py).
    return await process_lead_submission(
        lead=lead, partner_id=partner.partner_id, request_id=request_id,
        db=db, sa_email=_TASKS_SA_EMAIL,
    )


# ── GET /leads ────────────────────────────────────────────────────────────────

@router.get("", summary="List leads with filters and pagination")
@limiter.limit("200/minute")
async def list_leads(
    request:         Request,
    partner:         PartnerContext = Depends(get_partner),
    db:              firestore.AsyncClient = Depends(get_db),
    status_filter:   Optional[str] = Query(None, alias="status"),
    vcf_eligibility: Optional[str] = Query(None, alias="vcfEligibility"),
    source:          Optional[str] = Query(None),
    date_from:       Optional[date] = Query(None, alias="dateFrom"),
    date_to:         Optional[date] = Query(None, alias="dateTo"),
    search:          Optional[str] = Query(None, description="Email prefix search"),
    page_size:       int = Query(50, ge=1, le=200, alias="pageSize"),
    page_token:      Optional[str] = Query(None, alias="pageToken"),
) -> dict:
    cfg       = get_settings()
    cases_ref = db.collection(cfg.firestore_cases_collection)
    query     = cases_ref

    if status_filter:
        query = query.where("status", "==", status_filter)
    if vcf_eligibility:
        query = query.where("vcfEligibility", "==", vcf_eligibility)
    if source:
        query = query.where("marketingSource", "==", source)
    if search:
        query = (query
                 .where("email", ">=", search.lower())
                 .where("email", "<=", search.lower() + "\uf8ff"))

    query = query.order_by("createdAt", direction=firestore.Query.DESCENDING)

    if page_token:
        cursor = await cases_ref.document(page_token).get()
        if cursor.exists:
            query = query.start_after(cursor)

    query    = query.limit(page_size + 1)
    docs     = [doc async for doc in query.stream()]
    has_more = len(docs) > page_size
    if has_more:
        docs = docs[:page_size]

    cases_data = [
        {
            "caseId":          d.get("caseId"),
            "status":          d.get("status"),
            "vcfEligibility":  d.get("vcfEligibility"),
            "vcfScore":        (d.get("vcfScreeningDetails") or {}).get("score"),
            "firstName":       d.get("firstName"),
            "lastName":        d.get("lastName"),
            "email":           d.get("email"),
            "phone":           d.get("phone"),
            "marketingSource": d.get("marketingSource"),
            "partnerId":       d.get("partnerId"),
            "assignment":      d.get("assignment"),
            "createdAt":       d.get("createdAt"),
            "updatedAt":       d.get("updatedAt"),
        }
        for doc in docs
        for d in [doc.to_dict()]
    ]

    return {
        "cases":         cases_data,
        "pageSize":      page_size,
        "hasMore":       has_more,
        "nextPageToken": docs[-1].id if has_more and docs else None,
        "total":         len(cases_data),
    }


# ── POST /leads/bulk-assign ───────────────────────────────────────────────────

@router.post("/bulk-assign", summary="Bulk assign leads to a staff member")
async def bulk_assign(
    request: Request,
    partner: PartnerContext = Depends(get_partner),
    db:      firestore.AsyncClient = Depends(get_db),
) -> dict:
    body      = await request.json()
    case_ids  = body.get("caseIds", [])
    assignment = body.get("assignment", "")

    if not case_ids or not assignment:
        raise HTTPException(status_code=400, detail={
            "error": "INVALID_REQUEST", "message": "caseIds and assignment are required", "details": [],
        })
    if '@' in assignment:
        raise HTTPException(status_code=400, detail={
            "error": "INVALID_REQUEST", "message": "assignment must be a uid not email"
        })
    if len(case_ids) > 100:
        raise HTTPException(status_code=400, detail={
            "error": "INVALID_REQUEST", "message": "Maximum 100 cases per bulk operation", "details": [],
        })

    cfg= get_settings()
    updated, failed, skipped = [], [], []
    for case_id in case_ids:
        try:
            await assign_case_transactional(
                case_id=case_id, assignee=assignment, db=db,
            )
            updated.append(case_id)
        except AssignmentConflict as conflict:
            logger.info(
                "bulk_assign_skipped_already_assigned",
                case_id=case_id,
                existing_assignee=conflict.existing_assignee,
            )
            skipped.append({
                "caseId": case_id,
                "existingAssignee": conflict.existing_assignee,
            })
        except Exception as exc:
            logger.error("bulk_assign_failed", case_id=case_id, error=str(exc))
            failed.append(case_id)

    return {
        "updated": updated,
        "skipped": skipped,
        "failed":  failed,
        "total":   len(updated),
    }


# ── GET /leads/export/csv ─────────────────────────────────────────────────────

@router.get("/export/csv", summary="Export filtered leads as CSV")
@limiter.limit("10/minute")
async def export_leads_csv(
    request:         Request,
    partner:         PartnerContext = Depends(get_partner),
    db:              firestore.AsyncClient = Depends(get_db),
    status_filter:   Optional[str] = Query(None, alias="status"),
    vcf_eligibility: Optional[str] = Query(None, alias="vcfEligibility"),
    date_from:       Optional[date] = Query(None, alias="dateFrom"),
    date_to:         Optional[date] = Query(None, alias="dateTo"),
) -> StreamingResponse:
    cfg   = get_settings()
    query = db.collection(cfg.firestore_cases_collection)
    if status_filter:
        query = query.where("status", "==", status_filter)
    if vcf_eligibility:
        query = query.where("vcfEligibility", "==", vcf_eligibility)
    query = query.order_by("createdAt", direction=firestore.Query.DESCENDING).limit(5000)
    docs  = [doc async for doc in query.stream()]

    _FIELDS = [
        "caseId", "firstName", "lastName", "email", "phone",
        "status", "vcfEligibility", "exposureLocation",
        "exposureDateStart", "exposureDateEnd", "wtcHealthProgramStatus",
        "priorAttorney", "marketingSource", "assignedTo", "createdAt",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=_FIELDS)
    writer.writeheader()
    for doc in docs:
        d = doc.to_dict()
        writer.writerow({k: d.get(k, "") for k in _FIELDS})
    output.seek(0)
    filename = f"leads_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── POST /leads/bulk-import ───────────────────────────────────────────────────

@router.post(
    "/bulk-import",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=LeadImportJobResponse,
    summary="Bulk import leads from an Excel file with column mapping",
)
async def create_bulk_import(
    request: Request,
    file:    UploadFile = File(...),
    mapping: str        = Form(..., description="JSON-encoded BulkImportRequest"),
    partner: PartnerContext = Depends(get_partner),
    db:      firestore.AsyncClient = Depends(get_db),
) -> LeadImportJobResponse:
    """
    Registers the uploaded file with storage-gateway's case-less upload path
    for virus scanning and creates an async job — no parsing happens inline.
    Poll GET /bulk-import/{jobId} for progress; the file is only parsed once
    the scan clears (see services/bulk_import_service.handle_scan_check).
    """
    request_id = str(uuid.uuid4())

    try:
        mapping_data = json.loads(mapping)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail={
            "error": "INVALID_REQUEST", "message": f"mapping is not valid JSON: {exc}", "details": [],
        })
    try:
        bulk_request = BulkImportRequest(**mapping_data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={
            "error": "INVALID_REQUEST", "message": f"mapping does not match the expected shape: {exc}", "details": [],
        })

    file_bytes = await file.read()
    return await bulk_import_service.create_import_job(
        file_bytes=file_bytes,
        file_name=file.filename or "upload.xlsx",
        mapping=bulk_request,
        partner_id=partner.partner_id,
        request_id=request_id,
        db=db,
        settings=_settings,
        sa_email=_TASKS_SA_EMAIL,
    )


# ── GET /leads/bulk-import/{jobId} ────────────────────────────────────────────

@router.get(
    "/bulk-import/{job_id}",
    response_model=LeadImportJobResponse,
    summary="Get bulk import job status",
)
async def get_bulk_import_job(
    job_id:  str,
    partner: PartnerContext = Depends(get_partner),
    db:      firestore.AsyncClient = Depends(get_db),
) -> LeadImportJobResponse:
    job = await bulk_import_service.get_job(job_id, db)
    if not job:
        raise HTTPException(status_code=404, detail={
            "error": "NOT_FOUND", "message": f"Bulk import job {job_id} not found", "details": [],
        })
    return job


# ── GET /leads/bulk-import/{jobId}/results ────────────────────────────────────

@router.get(
    "/bulk-import/{job_id}/results",
    response_model=LeadImportJobResultsPage,
    summary="List bulk import per-row results",
)
async def get_bulk_import_results(
    job_id:     str,
    partner:    PartnerContext = Depends(get_partner),
    db:         firestore.AsyncClient = Depends(get_db),
    page_size:  int = Query(100, ge=1, le=500, alias="pageSize"),
    page_token: Optional[str] = Query(None, alias="pageToken"),
    outcome:    Optional[str] = Query(None),
) -> LeadImportJobResultsPage:
    return await bulk_import_service.list_job_results(
        job_id, db, page_size=page_size, page_token=page_token, outcome=outcome,
    )


# ── POST /leads/internal/tasks/bulk-import-scan-check ─────────────────────────

@router.post("/internal/tasks/bulk-import-scan-check", include_in_schema=False)
async def handle_bulk_import_scan_check(
    request: Request,
    db:      firestore.AsyncClient = Depends(get_db),
) -> dict:
    """Called by Cloud Tasks to poll storage-gateway's virus-scan status for
    a bulk-import job. Re-enqueues itself while pending/scanning."""
    _verify_cloud_tasks_oidc(request, "/api/v1/leads/internal/tasks/bulk-import-scan-check")

    body   = await request.json()
    job_id = body.get("jobId")
    if not job_id:
        logger.error("bulk_import_scan_check_missing_job_id")
        return {"status": "error", "message": "Missing jobId"}

    return await bulk_import_service.handle_scan_check(
        job_id=job_id, db=db, settings=_settings, sa_email=_TASKS_SA_EMAIL,
    )


# ── POST /leads/internal/tasks/bulk-import ─────────────────────────────────────

@router.post("/internal/tasks/bulk-import", include_in_schema=False)
async def handle_bulk_import_chunk(
    request: Request,
    db:      firestore.AsyncClient = Depends(get_db),
) -> dict:
    """Called by Cloud Tasks to process one chunk of rows for a bulk-import job."""
    _verify_cloud_tasks_oidc(request, "/api/v1/leads/internal/tasks/bulk-import")

    body      = await request.json()
    job_id    = body.get("jobId")
    row_start = body.get("rowStart")
    row_end   = body.get("rowEnd")
    if not job_id or row_start is None or row_end is None:
        logger.error("bulk_import_chunk_missing_fields")
        return {"status": "error", "message": "Missing jobId/rowStart/rowEnd"}

    return await bulk_import_service.process_chunk(
        job_id=job_id, row_start=row_start, row_end=row_end, db=db, sa_email=_TASKS_SA_EMAIL,
    )


# ── POST /leads/internal/tasks/followup ──────────────────────────────────────

@router.post("/internal/tasks/followup", include_in_schema=False)
async def handle_followup_task(
    request: Request,
    db:      firestore.AsyncClient = Depends(get_db),
) -> dict:
    """
    Called by Cloud Tasks 48 hours after lead creation.

    Creates an Admin Staff task in /tasks (Firestore write).
    Publishes lead-followup to Pub/Sub — notification service sends followup_sms.
    """
    _verify_cloud_tasks_oidc(request, "/api/v1/leads/internal/tasks/followup")

    body    = await request.json()
    case_id = body.get("caseId")
    if not case_id:
        logger.error("followup_task_missing_case_id")
        return {"status": "error", "message": "Missing caseId"}

    case = await get_case(case_id, db)
    if not case:
        logger.warning("followup_task_case_not_found", case_id=case_id)
        return {"status": "not_found"}

    if case.followupTaskCreated:
        logger.info("followup_skip_already_created", case_id=case_id)
        return {"status": "skipped", "reason": "Follow-up already created"}

    # Create Admin Staff task in Firestore
    cfg      = get_settings()
    task_ref = db.collection("tasks").document()
    await task_ref.set({
        "taskId":    task_ref.id,
        "type":      "FOLLOWUP_LEAD",
        "caseId":    case_id,
        "assignedTo": case.assignedTo or "admin_pool",
        "clientName":  f"{case.firstName} {case.lastName}",
        "clientEmail": case.email,
        "clientPhone": case.phone,
        "status":    "pending",
        "priority":  "high",
        "suggestedActions": [
            "Call client to confirm receipt of welcome communication",
            "Confirm VCF interest and exposure history",
            "Verify WTC Health Program enrollment status",
            "Schedule intake appointment if qualified",
        ],
        "createdAt": firestore.SERVER_TIMESTAMP,
        "dueAt":     firestore.SERVER_TIMESTAMP,
    })

    await db.collection(cfg.firestore_cases_collection).document(case_id).update({
        "followupTaskCreated": True,
        "followupTaskId":      task_ref.id,
        "updatedAt":           firestore.SERVER_TIMESTAMP,
    })
    logger.info("followup_task_created", case_id=case_id, task_id=task_ref.id)

    # Publish lead-followup → notification service sends followup_sms
    try:
        await publish_lead_followup(
            case_id    = case_id,
            first_name = case.firstName,
            phone      = case.phone,
            request_id = task_ref.id,
        )
    except Exception as exc:
        logger.error("pubsub_lead_followup_failed", case_id=case_id, error=str(exc))

    return {"status": "created", "taskId": task_ref.id}


def _verify_cloud_tasks_oidc(request: Request, expected_path: str) -> None:
    """Verify Google-signed OIDC token from Cloud Tasks. Skipped in dev/test.

    expected_path is the internal endpoint's own path (e.g.
    "/api/v1/leads/internal/tasks/followup") — it's also the audience Cloud
    Tasks signed the token for, since tasks_service.py sets audience=handler_url
    per-endpoint.
    """
    cfg = get_settings()
    if cfg.app_env in ("development", "test"):
        return

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "UNAUTHORIZED", "message": "Missing OIDC token", "details": []},
        )

    token    = auth_header.split(" ", 1)[1]
    audience = f"{cfg.cloud_tasks_handler_url}{expected_path}"
    try:
        id_info     = id_token.verify_oauth2_token(
            token, google_requests.Request(), audience=audience,
        )
        expected_sa = (
            cfg.cloud_tasks_sa_email
            or f"lead-intake-sa@{cfg.gcp_project_id}.iam.gserviceaccount.com"
        )
        if id_info.get("email") != expected_sa:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "FORBIDDEN", "message": "Unexpected service account", "details": []},
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "UNAUTHORIZED", "message": "Invalid OIDC token", "details": []},
        )


# ── GET /leads/{lead_id} ──────────────────────────────────────────────────────

@router.get("/{lead_id}", response_model=CaseDocument, summary="Get lead detail")
async def get_lead(
    lead_id: str,
    partner: PartnerContext = Depends(get_partner),
    db:      firestore.AsyncClient = Depends(get_db),
) -> CaseDocument:
    case = await get_case(lead_id, db)
    if not case:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "NOT_FOUND", "message": f"Case {lead_id} not found",
                "details": [], "requestId": str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    return case


# ── PATCH /leads/{lead_id}/status ─────────────────────────────────────────────

@router.patch("/{lead_id}/status", summary="Update case status")
async def update_lead_status(
    lead_id: str,
    body:    UpdateStatusRequest,
    partner: PartnerContext = Depends(get_partner),
    db:      firestore.AsyncClient = Depends(get_db),
) -> dict:
    case = await get_case(lead_id, db)
    if not case:
        raise HTTPException(
            status_code=404,
            detail={"error": "NOT_FOUND", "message": f"Case {lead_id} not found", "details": []},
        )
    updated_by = body.updatedBy or partner.partner_id
    await update_case_status(
        case_id=lead_id, new_status=body.status.value,
        updated_by=updated_by, note=body.note, db=db,
    )
    return {
        "caseId":    lead_id,
        "status":    body.status.value,
        "updatedAt": datetime.utcnow().isoformat(),
    }
