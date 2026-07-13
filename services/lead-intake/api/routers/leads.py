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
import uuid
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from google.auth.transport import requests as google_requests
from google.cloud import firestore
from google.oauth2 import id_token

from config import get_settings
from logging_config import get_logger
from middleware.auth import PartnerContext, get_partner
from middleware.rate_limiter import limiter
from models.lead import (
    CaseDocument, CaseStatus, ErrorDetail, ErrorResponse,
    LeadCreatedResponse, LeadRequest, UpdateStatusRequest, VCFEligibility,
)
from services.case_service import (
    create_case, get_case, update_case_status,
    apply_vcf_screening_result, write_staff_screening_notification,
    assign_case_transactional, AssignmentConflict,
)
from services.duplicate_detection import detect_duplicate, detect_ssn_dob_duplicate, is_idempotent_retry
from services.firestore_client import get_db
from services.pubsub_service import (
    publish_lead_created, publish_lead_screened, publish_lead_followup,
)
from services.tasks_service import create_followup_task
from services.vcf_screener import run_screening

logger    = get_logger(__name__)
router    = APIRouter(prefix="/leads", tags=["Leads"])
_settings = get_settings()

_TASKS_SA_EMAIL = (
    _settings.cloud_tasks_sa_email
    or f"lead-intake-service-account@{_settings.gcp_project_id}.iam.gserviceaccount.com"
)


def _err(request_id: str, code: str, message: str, details=None) -> dict:
    return ErrorResponse(
        error=code, message=message,
        details=details or [], requestId=request_id,
        timestamp=datetime.utcnow(),
    ).model_dump(mode="json")


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

    # ── SSN + DOB hard duplicate check (mass_tort per AI_CONTEXT.md) ─────────
    # If match found: still create the case, but auto-flag as Disqualified
    # with a note referencing the matched case.
    ssn_dob_match = await detect_ssn_dob_duplicate(
        ssn=lead.ssn, date_of_birth=lead.dateOfBirth, db=db,
    )

    # Email + phone soft duplicate — blocks entirely (409)
    existing_case_id = await detect_duplicate(
        email=str(lead.email), phone=lead.phone, db=db,
    )
    if existing_case_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_err(
                request_id, "DUPLICATE_LEAD",
                "A lead with this email and phone already exists",
                [ErrorDetail(field="email+phone", code="DUPLICATE",
                             message=f"Case {existing_case_id} already exists")],
            ),
        )

    # Create case in Firestore (atomic transaction)
    try:
        case: CaseDocument = await create_case(
            lead=lead, partner_id=partner.partner_id,
            request_id=request_id, db=db,
        )
    except Exception as exc:
        logger.error("case_creation_failed", request_id=request_id, error=str(exc))
        raise HTTPException(
            status_code=500,
            detail=_err(request_id, "INTERNAL_ERROR", "Failed to create case."),
        )

    # ── SSN + DOB hard duplicate → auto-Disqualify ────────────────────────────
    # Case is created first (preserves the intake record for audit), then
    # immediately flagged.  VCF screening is skipped for duplicates.
    if ssn_dob_match:
        dup_note = f"Duplicate: matched caseId={ssn_dob_match.matched_case_id}"
        try:
            await update_case_status(
                case_id=case.caseId,
                new_status=CaseStatus.DISQUALIFIED.value,
                updated_by="system",
                note=dup_note,
                db=db,
            )
            case.status = CaseStatus.DISQUALIFIED
            logger.info(
                "ssn_dob_duplicate_auto_disqualified",
                case_id=case.caseId,
                matched_case_id=ssn_dob_match.matched_case_id,
            )
        except Exception as exc:
            logger.error(
                "ssn_dob_duplicate_disqualify_failed",
                case_id=case.caseId, error=str(exc),
            )

        return LeadCreatedResponse(
            leadId=case.caseId,
            status=case.status,
            vcfScreeningStatus=VCFEligibility.PENDING,
            requestId=request_id,
            timestamp=datetime.utcnow(),
        )

    # ── Inline VCF screening ──────────────────────────────────────────────────
    screening_result = None
    try:
        case_dict        = case.to_firestore_dict()
        screening_result = await run_screening(case.caseId, case_dict, db)
        await apply_vcf_screening_result(
            case_id           = case.caseId,
            eligibility       = screening_result.eligibility,
            new_status        = screening_result.case_status,
            screening_details = screening_result.to_dict(),
            db                = db,
        )
        case.vcfEligibility = VCFEligibility(screening_result.eligibility)
        case.status         = CaseStatus(screening_result.case_status)
        logger.info(
            "vcf_screening_complete",
            case_id=case.caseId,
            eligibility=screening_result.eligibility,
            score=screening_result.score,
        )
    except Exception as exc:
        logger.error("vcf_screening_failed_non_fatal", case_id=case.caseId, error=str(exc))

    # ── Staff in-app notification (Firestore write — not SMS) ─────────────────
    if screening_result is not None:
        try:
            await write_staff_screening_notification(
                case_id     = case.caseId,
                first_name  = lead.firstName,
                last_name   = lead.lastName,
                eligibility = screening_result.eligibility,
                score       = screening_result.score,
                flags       = screening_result.flags,
                assigned_to = case.assignedTo,
                db          = db,
            )
        except Exception as exc:
            logger.error("staff_notification_failed_non_fatal",
                         case_id=case.caseId, error=str(exc))

    # ── Pub/Sub: lead-created → notification service sends welcome_sms ────────
    # Phone and name are included in the payload so the notification service
    # can dispatch without making a Firestore lookup.
    try:
        await publish_lead_created(
            case_id          = case.caseId,
            partner_id       = partner.partner_id,
            request_id       = request_id,
            marketing_source = lead.marketingSource,
            first_name       = lead.firstName,
            last_name        = lead.lastName,
            phone            = lead.phone,
        )
    except Exception as exc:
        logger.error("pubsub_lead_created_failed", case_id=case.caseId, error=str(exc))

    # ── Pub/Sub: lead-screened → audit trail ──────────────────────────────────
    if screening_result is not None:
        try:
            await publish_lead_screened(
                case_id     = case.caseId,
                eligibility = screening_result.eligibility,
                score       = screening_result.score,
                flags       = screening_result.flags,
                new_status  = screening_result.case_status,
                request_id  = request_id,
            )
        except Exception as exc:
            logger.error("pubsub_lead_screened_failed", case_id=case.caseId, error=str(exc))

    # ── Cloud Task: 48h Admin Staff follow-up ─────────────────────────────────
    # Schedules a task that calls /internal/tasks/followup 48h from now.
    # That handler creates the Firestore task doc and publishes lead-followup
    # which triggers the follow-up SMS via the notification service.
    try:
        task_name = await create_followup_task(
            case_id=case.caseId, service_account_email=_TASKS_SA_EMAIL,
        )
        logger.info("followup_task_enqueued", case_id=case.caseId, task=task_name)
    except Exception as exc:
        logger.error("followup_task_failed_non_fatal", case_id=case.caseId, error=str(exc))

    logger.info("lead_intake_complete", case_id=case.caseId, request_id=request_id)
    return LeadCreatedResponse(
        leadId             = case.caseId,
        status             = case.status,
        vcfScreeningStatus = case.vcfEligibility,
        requestId          = request_id,
        timestamp          = datetime.utcnow(),
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
    _verify_cloud_tasks_oidc(request)

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


def _verify_cloud_tasks_oidc(request: Request) -> None:
    """Verify Google-signed OIDC token from Cloud Tasks. Skipped in dev/test."""
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
    audience = f"{cfg.cloud_tasks_handler_url}/api/v1/leads/internal/tasks/followup"
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
