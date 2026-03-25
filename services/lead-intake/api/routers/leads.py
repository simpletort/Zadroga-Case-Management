"""
api/routers/leads.py — Lead ingestion and management endpoints.

Route order matters in FastAPI — static paths must come before /{lead_id}:
  POST   /leads
  GET    /leads
  POST   /leads/bulk-assign               ← before /{lead_id}
  GET    /leads/export/csv                ← before /{lead_id}
  POST   /leads/internal/tasks/followup   ← before /{lead_id}
  GET    /leads/{lead_id}
  PATCH  /leads/{lead_id}/status
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
    CaseDocument,
    CaseStatus,
    ErrorDetail,
    ErrorResponse,
    LeadCreatedResponse,
    LeadRequest,
    UpdateStatusRequest,
    VCFEligibility,
)
from services.case_service import create_case, get_case, update_case_status
from services.duplicate_detection import detect_duplicate, is_idempotent_retry
from services.firestore_client import get_db
from services.notification_service import send_welcome_notifications
from services.pubsub_service import publish_lead_created
from services.tasks_service import create_followup_task
from services.validation import validate_lead

logger = get_logger(__name__)
router = APIRouter(prefix="/leads", tags=["Leads"])
_settings = get_settings()

_TASKS_SA_EMAIL = (
    _settings.cloud_tasks_sa_email
    or f"lead-intake-sa@{_settings.gcp_project_id}.iam.gserviceaccount.com"
)


def _err(request_id: str, code: str, message: str, details=None) -> dict:
    return ErrorResponse(
        error=code,
        message=message,
        details=details or [],
        requestId=request_id,
        timestamp=datetime.utcnow(),
    ).model_dump()


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
    lead: LeadRequest,
    partner: PartnerContext = Depends(get_partner),
    db: firestore.AsyncClient = Depends(get_db),
) -> LeadCreatedResponse:
    request_id = str(uuid.uuid4())
    logger.info("lead_intake_started", request_id=request_id, partner_id=partner.partner_id)

    # Domain validation (cross-field rules beyond Pydantic)
    validation_result = validate_lead(lead)
    if not validation_result.is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_err(request_id, "VALIDATION_ERROR", "Request validation failed", validation_result.errors),
        )

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

    # Duplicate detection — email AND phone must both be new
    existing_case_id = await detect_duplicate(email=str(lead.email), phone=lead.phone, db=db)
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

    # Create case (atomic Firestore transaction)
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

    # Publish lead-created event → triggers vcf_screener Cloud Function
    try:
        await publish_lead_created(
            case_id=case.caseId, partner_id=partner.partner_id,
            request_id=request_id, marketing_source=lead.marketingSource,
        )
    except Exception as exc:
        logger.error("pubsub_publish_failed_non_fatal", case_id=case.caseId, error=str(exc))

    # Enqueue 48-hour follow-up Cloud Task
    try:
        task_name = await create_followup_task(
            case_id=case.caseId, service_account_email=_TASKS_SA_EMAIL,
        )
        logger.info("followup_task_enqueued", case_id=case.caseId, task=task_name)
    except Exception as exc:
        logger.error("followup_task_failed_non_fatal", case_id=case.caseId, error=str(exc))

    # Send welcome email + SMS (non-blocking)
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


# ── GET /leads ────────────────────────────────────────────────────────────────

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
    search: Optional[str] = Query(None, description="Email prefix search"),
    page_size: int = Query(50, ge=1, le=200, alias="pageSize"),
    page_token: Optional[str] = Query(None, alias="pageToken"),
) -> dict:
    cfg = get_settings()
    cases_ref = db.collection(cfg.firestore_cases_collection)
    query = cases_ref

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

    query = query.limit(page_size + 1)
    docs = [doc async for doc in query.stream()]

    has_more = len(docs) > page_size
    if has_more:
        docs = docs[:page_size]

    cases_data = [
        {
            "caseId":          d.get("caseId"),
            "status":          d.get("status"),
            "vcfEligibility":  d.get("vcfEligibility"),
            "firstName":       d.get("firstName"),
            "lastName":        d.get("lastName"),
            "email":           d.get("email"),
            "phone":           d.get("phone"),
            "marketingSource": d.get("marketingSource"),
            "partnerId":       d.get("partnerId"),
            "assignedTo":      d.get("assignedTo"),
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
    db: firestore.AsyncClient = Depends(get_db),
) -> dict:
    body = await request.json()
    case_ids: list[str] = body.get("caseIds", [])
    assign_to: str = body.get("assignTo", "")

    if not case_ids or not assign_to:
        raise HTTPException(
            status_code=400,
            detail={"error": "INVALID_REQUEST", "message": "caseIds and assignTo are required", "details": []},
        )
    if len(case_ids) > 100:
        raise HTTPException(
            status_code=400,
            detail={"error": "INVALID_REQUEST", "message": "Maximum 100 cases per bulk operation", "details": []},
        )

    cfg = get_settings()
    updated, failed = [], []
    for case_id in case_ids:
        try:
            await db.collection(cfg.firestore_cases_collection).document(case_id).update(
                {"assignedTo": assign_to, "updatedAt": firestore.SERVER_TIMESTAMP}
            )
            updated.append(case_id)
        except Exception as exc:
            logger.error("bulk_assign_failed", case_id=case_id, error=str(exc))
            failed.append(case_id)

    return {"updated": updated, "failed": failed, "total": len(updated)}


# ── GET /leads/export/csv ─────────────────────────────────────────────────────

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
    cfg = get_settings()
    query = db.collection(cfg.firestore_cases_collection)

    if status_filter:
        query = query.where("status", "==", status_filter)
    if vcf_eligibility:
        query = query.where("vcfEligibility", "==", vcf_eligibility)

    query = query.order_by("createdAt", direction=firestore.Query.DESCENDING).limit(5000)
    docs = [doc async for doc in query.stream()]

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
    db: firestore.AsyncClient = Depends(get_db),
) -> dict:
    """
    Called by Cloud Tasks 48 hours after lead creation.
    Verifies the Google-signed OIDC token Cloud Tasks attaches to every request.
    """
    _verify_cloud_tasks_oidc(request)

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

    cfg = get_settings()
    task_ref = db.collection("tasks").document()
    await task_ref.set({
        "taskId":    task_ref.id,
        "type":      "FOLLOWUP_LEAD",
        "caseId":    case_id,
        "assignedTo": case.assignedTo or "unassigned",
        "clientName":  f"{case.firstName} {case.lastName}",
        "clientEmail": case.email,
        "clientPhone": case.phone,
        "status":    "pending",
        "suggestedActions": [
            "Call client to confirm receipt of welcome email",
            "Resend portal login link if needed",
            "Confirm VCF interest and exposure history",
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
    return {"status": "created", "taskId": task_ref.id}


def _verify_cloud_tasks_oidc(request: Request) -> None:
    """
    Verify the Google-signed OIDC bearer token Cloud Tasks attaches to every
    HTTP target request. Skipped in development/test for local ease.
    """
    cfg = get_settings()
    if cfg.app_env in ("development", "test"):
        return

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        logger.warning("cloud_tasks_missing_oidc_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "UNAUTHORIZED", "message": "Missing OIDC token", "details": []},
        )

    token = auth_header.split(" ", 1)[1]
    try:
        audience = f"{cfg.cloud_tasks_handler_url}/api/v1/leads/internal/tasks/followup"
        id_info = id_token.verify_oauth2_token(
            token, google_requests.Request(), audience=audience,
        )
        expected_sa = (
            cfg.cloud_tasks_sa_email
            or f"lead-intake-sa@{cfg.gcp_project_id}.iam.gserviceaccount.com"
        )
        if id_info.get("email") != expected_sa:
            logger.warning("cloud_tasks_wrong_sa", got=id_info.get("email"), expected=expected_sa)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "FORBIDDEN", "message": "Unexpected service account", "details": []},
            )
    except ValueError as exc:
        logger.warning("cloud_tasks_invalid_oidc_token", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "UNAUTHORIZED", "message": "Invalid OIDC token", "details": []},
        )


# ── GET /leads/{lead_id} ──────────────────────────────────────────────────────
# Wildcard — must stay after all static /leads/* routes above.

@router.get("/{lead_id}", response_model=CaseDocument, summary="Get lead detail")
async def get_lead(
    lead_id: str,
    partner: PartnerContext = Depends(get_partner),
    db: firestore.AsyncClient = Depends(get_db),
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
    body: UpdateStatusRequest,
    partner: PartnerContext = Depends(get_partner),
    db: firestore.AsyncClient = Depends(get_db),
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
    return {"caseId": lead_id, "status": body.status.value, "updatedAt": datetime.utcnow().isoformat()}
