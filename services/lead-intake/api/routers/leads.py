"""
api/routers/leads.py — Lead ingestion and management endpoints.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from google.cloud import firestore

from config import get_settings
from middleware.auth import PartnerContext, get_partner
from middleware.rate_limiter import limiter
from models.lead import (
    CaseStatus,
    ErrorDetail,
    ErrorResponse,
    LeadCreatedResponse,
    LeadRequest,
    VCFEligibility,
    CaseDocument,
)
from services.case_service import create_case, get_case, update_case_status
from services.duplicate_detection import detect_duplicate, is_idempotent_retry
from services.firestore_client import get_db
from services.notification_service import send_welcome_notifications
from services.pubsub_service import publish_lead_created
from services.tasks_service import create_followup_task
from services.validation import validate_lead
from logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/leads", tags=["Leads"])
settings = get_settings()

TASKS_SA_EMAIL = (
    settings.cloud_tasks_sa_email
    or f"lead-intake-sa@{settings.gcp_project_id}.iam.gserviceaccount.com"
)


def _error_response(request_id, error_code, message, details=None):
    return ErrorResponse(
        error=error_code,
        message=message,
        details=details or [],
        requestId=request_id,
        timestamp=datetime.utcnow(),
    ).model_dump()


# ── POST /leads — Ingest a new lead ──────────────────────────────────────────

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=LeadCreatedResponse,
    summary="Ingest a new lead",
)
@limiter.limit(f"{settings.rate_limit_requests}/minute")
async def create_lead(
    request: Request,
    lead: LeadRequest,
    partner: PartnerContext = Depends(get_partner),
    db: firestore.AsyncClient = Depends(get_db),
) -> LeadCreatedResponse:
    request_id = str(uuid.uuid4())
    logger.info("lead_intake_started", request_id=request_id, partner_id=partner.partner_id)

    # Domain validation
    validation_result = validate_lead(lead)
    if not validation_result.is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_error_response(request_id, "VALIDATION_ERROR", "Request validation failed", validation_result.errors),
        )

    # Idempotency
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

    # Duplicate detection
    existing_case_id = await detect_duplicate(email=str(lead.email), phone=lead.phone, db=db)
    if existing_case_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error_response(
                request_id, "DUPLICATE_LEAD",
                "A lead with this email and phone already exists",
                [ErrorDetail(field="email+phone", code="DUPLICATE", message=f"Case {existing_case_id} already exists")],
            ),
        )

    # Create case
    try:
        case: CaseDocument = await create_case(lead=lead, partner_id=partner.partner_id, request_id=request_id, db=db)
    except Exception as exc:
        logger.error("case_creation_failed", request_id=request_id, error=str(exc))
        raise HTTPException(status_code=500, detail=_error_response(request_id, "INTERNAL_ERROR", "Failed to create case."))

    # Publish Pub/Sub
    try:
        await publish_lead_created(case_id=case.caseId, partner_id=partner.partner_id, request_id=request_id, marketing_source=lead.marketingSource)
    except Exception as exc:
        logger.error("pubsub_publish_failed_non_fatal", case_id=case.caseId, error=str(exc))

    # Enqueue follow-up task
    try:
        task_name = await create_followup_task(case_id=case.caseId, service_account_email=TASKS_SA_EMAIL)
        logger.info("followup_task_enqueued", case_id=case.caseId, task=task_name)
    except Exception as exc:
        logger.error("followup_task_failed_non_fatal", case_id=case.caseId, error=str(exc))

    # Welcome notifications
    try:
        notif_result = await send_welcome_notifications(
            email=str(lead.email), phone=lead.phone,
            first_name=lead.firstName, case_id=case.caseId,
        )
        logger.info("notifications_dispatched", case_id=case.caseId, **notif_result)
    except Exception as exc:
        logger.error("notifications_failed_non_fatal", case_id=case.caseId, error=str(exc))

    logger.info("lead_intake_complete", case_id=case.caseId, request_id=request_id)
    return LeadCreatedResponse(
        leadId=case.caseId,
        status=case.status,
        vcfScreeningStatus=case.vcfEligibility,
        requestId=request_id,
        timestamp=datetime.utcnow(),
    )


# ── GET /leads — List with pagination, filters, search ───────────────────────

@router.get("", summary="List leads with filters and pagination")
@limiter.limit("200/minute")
async def list_leads(
    request: Request,
    partner: PartnerContext = Depends(get_partner),
    db: firestore.AsyncClient = Depends(get_db),
    status_filter: Optional[str] = Query(None, alias="status"),
    vcf_eligibility: Optional[str] = Query(None, alias="vcfEligibility"),
    source: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None, alias="dateFrom"),
    date_to: Optional[date] = Query(None, alias="dateTo"),
    search: Optional[str] = Query(None, description="Search by email prefix"),
    page_size: int = Query(50, ge=1, le=200, alias="pageSize"),
    page_token: Optional[str] = Query(None, alias="pageToken"),
) -> dict:
    settings_obj = get_settings()
    cases_ref = db.collection(settings_obj.firestore_cases_collection)
    query = cases_ref

    if status_filter:
        query = query.where("status", "==", status_filter)
    if vcf_eligibility:
        query = query.where("vcfEligibility", "==", vcf_eligibility)
    if source:
        query = query.where("marketingSource", "==", source)
    if search:
        # Prefix search on email
        query = query.where("email", ">=", search.lower()).where("email", "<=", search.lower() + "\uf8ff")

    query = query.order_by("createdAt", direction=firestore.Query.DESCENDING)

    # Cursor-based pagination
    if page_token:
        cursor_doc = await cases_ref.document(page_token).get()
        if cursor_doc.exists:
            query = query.start_after(cursor_doc)

    query = query.limit(page_size + 1)
    docs = [doc async for doc in query.stream()]

    has_more = len(docs) > page_size
    if has_more:
        docs = docs[:page_size]

    cases_data = []
    for doc in docs:
        data = doc.to_dict()
        # Mask sensitive fields for list view
        cases_data.append({
            "caseId": data.get("caseId"),
            "status": data.get("status"),
            "vcfEligibility": data.get("vcfEligibility"),
            "firstName": data.get("firstName"),
            "lastName": data.get("lastName"),
            "email": data.get("email"),
            "phone": data.get("phone"),
            "marketingSource": data.get("marketingSource"),
            "partnerId": data.get("partnerId"),
            "assignedTo": data.get("assignedTo"),
            "createdAt": data.get("createdAt"),
            "updatedAt": data.get("updatedAt"),
        })

    next_token = docs[-1].id if has_more and docs else None

    return {
        "cases": cases_data,
        "pageSize": page_size,
        "hasMore": has_more,
        "nextPageToken": next_token,
        "total": len(cases_data),
    }


# ── GET /leads/{lead_id} — Single case detail ────────────────────────────────

@router.get("/{lead_id}", response_model=CaseDocument, summary="Get lead detail")
async def get_lead(
    lead_id: str,
    partner: PartnerContext = Depends(get_partner),
    db: firestore.AsyncClient = Depends(get_db),
) -> CaseDocument:
    case = await get_case(lead_id, db)
    if not case:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": f"Case {lead_id} not found", "details": [], "requestId": str(uuid.uuid4()), "timestamp": datetime.utcnow().isoformat()})
    return case


# ── PATCH /leads/{lead_id}/status — Update case status (admin) ───────────────

@router.patch("/{lead_id}/status", summary="Update case status")
async def update_lead_status(
    lead_id: str,
    request: Request,
    partner: PartnerContext = Depends(get_partner),
    db: firestore.AsyncClient = Depends(get_db),
) -> dict:
    body = await request.json()
    new_status = body.get("status")
    note = body.get("note", "")
    updated_by = body.get("updatedBy", partner.partner_id)

    if new_status not in [s.value for s in CaseStatus]:
        raise HTTPException(status_code=400, detail={"error": "INVALID_STATUS", "message": f"Invalid status: {new_status}", "details": []})

    case = await get_case(lead_id, db)
    if not case:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": f"Case {lead_id} not found", "details": []})

    await update_case_status(
        case_id=lead_id,
        new_status=new_status,
        updated_by=updated_by,
        note=note,
        db=db,
    )
    return {"caseId": lead_id, "status": new_status, "updatedAt": datetime.utcnow().isoformat()}


# ── POST /leads/bulk-assign — Bulk assign to paralegal ───────────────────────

@router.post("/bulk-assign", summary="Bulk assign leads to a staff member")
async def bulk_assign(
    request: Request,
    partner: PartnerContext = Depends(get_partner),
    db: firestore.AsyncClient = Depends(get_db),
) -> dict:
    body = await request.json()
    case_ids: list[str] = body.get("caseIds", [])
    assign_to: str = body.get("assignTo", "")

    if not case_ids or not assign_to:
        raise HTTPException(status_code=400, detail={"error": "INVALID_REQUEST", "message": "caseIds and assignTo are required", "details": []})

    if len(case_ids) > 100:
        raise HTTPException(status_code=400, detail={"error": "INVALID_REQUEST", "message": "Maximum 100 cases per bulk operation", "details": []})

    settings_obj = get_settings()
    updated = []
    failed = []

    for case_id in case_ids:
        try:
            doc_ref = db.collection(settings_obj.firestore_cases_collection).document(case_id)
            await doc_ref.update({
                "assignedTo": assign_to,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            })
            updated.append(case_id)
        except Exception as exc:
            logger.error("bulk_assign_failed", case_id=case_id, error=str(exc))
            failed.append(case_id)

    return {"updated": updated, "failed": failed, "total": len(updated)}


# ── GET /leads/export — CSV export ───────────────────────────────────────────

@router.get("/export/csv", summary="Export filtered leads as CSV")
@limiter.limit("10/minute")
async def export_leads_csv(
    request: Request,
    partner: PartnerContext = Depends(get_partner),
    db: firestore.AsyncClient = Depends(get_db),
    status_filter: Optional[str] = Query(None, alias="status"),
    vcf_eligibility: Optional[str] = Query(None, alias="vcfEligibility"),
    date_from: Optional[date] = Query(None, alias="dateFrom"),
    date_to: Optional[date] = Query(None, alias="dateTo"),
) -> StreamingResponse:
    settings_obj = get_settings()
    cases_ref = db.collection(settings_obj.firestore_cases_collection)
    query = cases_ref

    if status_filter:
        query = query.where("status", "==", status_filter)
    if vcf_eligibility:
        query = query.where("vcfEligibility", "==", vcf_eligibility)

    query = query.order_by("createdAt", direction=firestore.Query.DESCENDING).limit(5000)
    docs = [doc async for doc in query.stream()]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "caseId", "firstName", "lastName", "email", "phone",
        "status", "vcfEligibility", "exposureLocation",
        "exposureDateStart", "exposureDateEnd", "wtcHealthProgramStatus",
        "priorAttorney", "marketingSource", "assignedTo", "createdAt",
    ])
    writer.writeheader()
    for doc in docs:
        data = doc.to_dict()
        writer.writerow({k: data.get(k, "") for k in writer.fieldnames})

    output.seek(0)
    filename = f"leads_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── POST /internal/tasks/followup — Cloud Tasks handler ──────────────────────

@router.post("/internal/tasks/followup", include_in_schema=False)
async def handle_followup_task(
    request: Request,
    db: firestore.AsyncClient = Depends(get_db),
) -> dict:
    """
    Called by Cloud Tasks 48 hours after lead creation.
    Checks if the client has logged into the portal; if not, creates a follow-up task.
    This endpoint is internal — protected by Cloud Tasks OIDC (no partner auth needed).
    """
    body = await request.json()
    case_id = body.get("caseId")

    if not case_id:
        logger.error("followup_task_missing_case_id")
        return {"status": "error", "message": "Missing caseId"}

    case = await get_case(case_id, db)
    if not case:
        logger.warning("followup_task_case_not_found", case_id=case_id)
        return {"status": "not_found"}

    if case.portalLoginAt:
        logger.info("followup_skip_portal_login", case_id=case_id)
        return {"status": "skipped", "reason": "Client logged in"}

    if case.followupTaskCreated:
        logger.info("followup_skip_already_created", case_id=case_id)
        return {"status": "skipped", "reason": "Follow-up already created"}

    # Create follow-up task in Firestore for assigned paralegal
    settings_obj = get_settings()
    task_ref = db.collection("tasks").document()
    await task_ref.set({
        "taskId": task_ref.id,
        "type": "FOLLOWUP_LEAD",
        "caseId": case_id,
        "assignedTo": case.assignedTo or "unassigned",
        "clientName": f"{case.firstName} {case.lastName}",
        "clientEmail": case.email,
        "clientPhone": case.phone,
        "status": "pending",
        "suggestedActions": [
            "Call client to confirm receipt of welcome email",
            "Resend portal login link if needed",
            "Confirm VCF interest and exposure history",
        ],
        "createdAt": firestore.SERVER_TIMESTAMP,
        "dueAt": firestore.SERVER_TIMESTAMP,
    })

    # Mark case as having follow-up created
    cases_ref = db.collection(settings_obj.firestore_cases_collection).document(case_id)
    await cases_ref.update({
        "followupTaskCreated": True,
        "followupTaskId": task_ref.id,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })

    logger.info("followup_task_created", case_id=case_id, task_id=task_ref.id)
    return {"status": "created", "taskId": task_ref.id}
