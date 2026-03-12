"""
routers/leads.py — POST /api/v1/leads endpoint.

Request lifecycle:
  1. JWT auth (middleware/auth.py)
  2. Rate limit check (100/min per partner)
  3. Pydantic validation (models/lead.py)
  4. Domain validation (services/validation.py)
  5. Idempotency check (same requestId seen before?)
  6. Duplicate detection (email AND phone match)
  7. Firestore case creation (atomic, transactional)
  8. Pub/Sub event publish (lead-created)
  9. Cloud Tasks 48hr follow-up enqueue
  10. Async welcome notifications (SendGrid + Twilio)
  11. Return 201 with caseId

HTTP status codes:
  201 — Created successfully
  400 — Validation failure (Pydantic or domain rules)
  409 — Duplicate lead (email AND phone already exist)
  422 — FastAPI unprocessable entity (type errors)
  429 — Rate limit exceeded
  500 — Internal server error
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
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
from services.case_service import create_case, get_case
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

# Service account email for Cloud Tasks OIDC (set via env)
TASKS_SA_EMAIL = settings.__dict__.get(
    "cloud_tasks_sa_email",
    f"lead-intake-sa@{settings.gcp_project_id}.iam.gserviceaccount.com"
)


def _error_response(
    request_id: str,
    error_code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> dict:
    return ErrorResponse(
        error=error_code,
        message=message,
        details=details or [],
        requestId=request_id,
        timestamp=datetime.utcnow(),
    ).model_dump()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=LeadCreatedResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Validation failure"},
        409: {"model": ErrorResponse, "description": "Duplicate lead"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
    summary="Ingest a new lead",
    description="Validates, deduplicates, creates a case, and triggers screening.",
)
@limiter.limit(f"{settings.rate_limit_requests}/minute")
async def create_lead(
    request: Request,
    lead: LeadRequest,
    partner: PartnerContext = Depends(get_partner),
    db: firestore.AsyncClient = Depends(get_db),
) -> LeadCreatedResponse:
    request_id = str(uuid.uuid4())

    logger.info(
        "lead_intake_started",
        request_id=request_id,
        partner_id=partner.partner_id,
        marketing_source=lead.marketingSource,
    )

    # ── Step 1: Domain-level validation ──────────────────────────────────
    validation_result = validate_lead(lead)
    if not validation_result.is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_error_response(
                request_id=request_id,
                error_code="VALIDATION_ERROR",
                message="Request validation failed",
                details=validation_result.errors,
            ),
        )

    # ── Step 2: Idempotency — has this exact requestId been processed? ────
    # (Only relevant if client sends X-Request-ID header; here we generate it,
    # but if the client sends their own, wire it in from request.headers.)
    client_request_id = request.headers.get("X-Request-ID")
    if client_request_id:
        existing_id = await is_idempotent_retry(client_request_id, db)
        if existing_id:
            case = await get_case(existing_id, db)
            logger.info(
                "idempotent_retry_detected",
                request_id=client_request_id,
                existing_case=existing_id,
            )
            return LeadCreatedResponse(
                leadId=existing_id,
                status=case.status if case else CaseStatus.NEW_LEAD,
                vcfScreeningStatus=case.vcfEligibility if case else VCFEligibility.PENDING,
                requestId=client_request_id,
                timestamp=datetime.utcnow(),
            )

    # ── Step 3: Duplicate detection ───────────────────────────────────────
    existing_case_id = await detect_duplicate(
        email=str(lead.email),
        phone=lead.phone,
        db=db,
    )
    if existing_case_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error_response(
                request_id=request_id,
                error_code="DUPLICATE_LEAD",
                message="A lead with this email and phone already exists",
                details=[
                    ErrorDetail(
                        field="email+phone",
                        code="DUPLICATE",
                        message=f"Case {existing_case_id} already exists for this contact",
                    )
                ],
            ),
        )

    # ── Step 4: Create Firestore case (atomic transaction) ────────────────
    try:
        case: CaseDocument = await create_case(
            lead=lead,
            partner_id=partner.partner_id,
            request_id=request_id,
            db=db,
        )
    except Exception as exc:
        logger.error(
            "case_creation_failed",
            request_id=request_id,
            partner_id=partner.partner_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_error_response(
                request_id=request_id,
                error_code="INTERNAL_ERROR",
                message="Failed to create case. Please retry.",
            ),
        )

    # ── Step 5: Publish Pub/Sub event ─────────────────────────────────────
    try:
        await publish_lead_created(
            case_id=case.caseId,
            partner_id=partner.partner_id,
            request_id=request_id,
            marketing_source=lead.marketingSource,
        )
    except Exception as exc:
        # Non-fatal: case is created; screener can be triggered manually
        logger.error(
            "pubsub_publish_failed_non_fatal",
            case_id=case.caseId,
            error=str(exc),
        )

    # ── Step 6: Enqueue 48-hour follow-up task ────────────────────────────
    try:
        task_name = await create_followup_task(
            case_id=case.caseId,
            service_account_email=TASKS_SA_EMAIL,
        )
        logger.info("followup_task_enqueued", case_id=case.caseId, task=task_name)
    except Exception as exc:
        logger.error(
            "followup_task_failed_non_fatal",
            case_id=case.caseId,
            error=str(exc),
        )

    # ── Step 7: Send welcome notifications (fire-and-forget) ─────────────
    # These are non-blocking: run them after returning the response in production.
    # Here we await them inline; in high-throughput scenarios use BackgroundTasks.
    try:
        notif_result = await send_welcome_notifications(
            email=str(lead.email),
            phone=lead.phone,
            first_name=lead.firstName,
            case_id=case.caseId,
        )
        logger.info(
            "notifications_dispatched",
            case_id=case.caseId,
            email_ok=notif_result["email"],
            sms_ok=notif_result["sms"],
        )
    except Exception as exc:
        logger.error(
            "notifications_failed_non_fatal",
            case_id=case.caseId,
            error=str(exc),
        )

    # ── Step 8: Return 201 ────────────────────────────────────────────────
    logger.info(
        "lead_intake_complete",
        case_id=case.caseId,
        request_id=request_id,
        partner_id=partner.partner_id,
    )

    return LeadCreatedResponse(
        leadId=case.caseId,
        status=case.status,
        vcfScreeningStatus=case.vcfEligibility,
        requestId=request_id,
        timestamp=datetime.utcnow(),
    )


@router.get(
    "/{lead_id}",
    response_model=CaseDocument,
    summary="Get a lead/case by ID",
)
async def get_lead(
    lead_id: str,
    partner: PartnerContext = Depends(get_partner),
    db: firestore.AsyncClient = Depends(get_db),
) -> CaseDocument:
    case = await get_case(lead_id, db)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "NOT_FOUND",
                "message": f"Case {lead_id} not found",
                "details": [],
                "requestId": str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    return case
