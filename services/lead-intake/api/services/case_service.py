"""
api/services/case_service.py — Firestore case CRUD with atomic ID generation.

Changes vs original:
  - apply_vcf_screening_result(): writes VCF screening output + creates
    staff in-app notification in the notifications collection.
  - write_staff_screening_notification(): writes a Firestore notification
    document for the assigned paralegal/admin_staff to see in their dashboard.
    This replaces the removed notification_dispatcher Cloud Function.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from google.cloud import firestore
from google.cloud.firestore_v1 import AsyncTransaction

from config import get_settings
from models.lead import (
    CaseDocument, CaseStatus, ErrorDetail, ErrorResponse,
    LeadCreatedResponse, LeadRequest, VCFEligibility,
)
from logging_config import get_logger
from services.duplicate_detection import detect_duplicate, detect_ssn_dob_duplicate
from services.pubsub_service import publish_lead_created, publish_lead_screened
from services.tasks_service import create_followup_task
from services.vcf_screener import run_screening

logger = get_logger(__name__)


def _err(request_id: str, code: str, message: str, details=None) -> dict:
    return ErrorResponse(
        error=code, message=message,
        details=details or [], requestId=request_id,
        timestamp=datetime.utcnow(),
    ).model_dump(mode="json")

_case_id_prefix_cache: Optional[str] = None


async def _fetch_prefix(db: firestore.AsyncClient) -> str:
    global _case_id_prefix_cache
    if _case_id_prefix_cache is not None:
        return _case_id_prefix_cache
    doc = await db.collection("firmSettings").document("case_id_prefix").get()
    _case_id_prefix_cache = (doc.to_dict() or {}).get("prefix", "CASE") if doc.exists else "CASE"
    return _case_id_prefix_cache


def reset_prefix_cache() -> None:
    """Invalidate the in-process prefix cache. Call after updating firmSettings/case_id_prefix."""
    global _case_id_prefix_cache
    _case_id_prefix_cache = None


def _counter_doc_id(prefix: str, year: int, month: int) -> str:
    return f"{prefix}-{year:04d}-{month:02d}"


def _case_id(prefix: str, year: int, month: int, count: int) -> str:
    return f"{prefix}-{year:04d}-{month:02d}-{count:04d}"


async def _get_next_case_id(
    db:          firestore.AsyncClient,
    transaction: AsyncTransaction,
    now:         datetime,
) -> str:
    settings    = get_settings()
    prefix      = await _fetch_prefix(db)
    counter_id  = _counter_doc_id(prefix, now.year, now.month)
    counter_ref = db.collection(settings.firestore_counters_collection).document(counter_id)
    counter_doc = await counter_ref.get(transaction=transaction)
    current_count = counter_doc.to_dict().get("count", 0) if counter_doc.exists else 0
    new_count     = current_count + 1
    transaction.set(
        counter_ref,
        {"count": new_count, "updatedAt": firestore.SERVER_TIMESTAMP, "yearMonth": counter_id},
        merge=True,
    )
    return _case_id(prefix, now.year, now.month, new_count)


async def create_case(
    lead:       LeadRequest,
    partner_id: str,
    request_id: str,
    db:         firestore.AsyncClient,
) -> CaseDocument:
    """Create a new case document in Firestore (atomic ID generation)."""
    settings = get_settings()
    now      = datetime.utcnow()

    @firestore.async_transactional
    async def _txn(transaction: AsyncTransaction) -> CaseDocument:
        case_id  = await _get_next_case_id(db, transaction, now)
        case     = CaseDocument.from_lead(
            lead=lead, case_id=case_id, partner_id=partner_id, request_id=request_id,
        )
        case_ref = db.collection(settings.firestore_cases_collection).document(case_id)
        transaction.set(case_ref, case.to_firestore_dict())
        logger.info("case_created", case_id=case_id, partner_id=partner_id)
        return case

    transaction = db.transaction()
    return await _txn(transaction)


async def process_lead_submission(
    lead:       LeadRequest,
    partner_id: str,
    request_id: str,
    db:         firestore.AsyncClient,
    sa_email:   str,
) -> LeadCreatedResponse:
    """
    Full lead pipeline shared by POST /leads and the bulk-import row worker:
      dedup checks -> create_case -> VCF screening -> staff notification ->
      pubsub events -> follow-up task enqueue.

    Lifted verbatim from routers/leads.py's create_lead() (steps 2-9) so both
    callers behave identically. Idempotency (X-Request-ID replay) is handled
    by the caller before this is invoked — it isn't part of this pipeline
    because the bulk-import worker uses its own idempotency key scheme
    (job_id:row_number) rather than a client-supplied header.

    Raises HTTPException(409, ...) on an email+phone soft duplicate.
    """
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
            lead=lead, partner_id=partner_id,
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
            partner_id       = partner_id,
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
            case_id=case.caseId, service_account_email=sa_email,
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


async def write_staff_screening_notification(
    case_id:     str,
    first_name:  str,
    last_name:   str,
    eligibility: str,
    score:       int,
    flags:       list[str],
    assigned_to: Optional[str],
    db:          firestore.AsyncClient,
) -> None:
    """
    Write an in-app notification document to /notifications/{id} for staff.

    This replaces the removed notification_dispatcher Cloud Function.
    The auth-rbac frontend reads the notifications collection to show
    alerts in the staff dashboard.

    Notification types match the old Cloud Function schema so the frontend
    doesn't need changes:
      CASE_QUALIFIED    — paralegal can convert to active case
      CASE_DISQUALIFIED — admin staff awareness
      CASE_NEEDS_REVIEW — paralegal manual review required

    Firestore document schema:
      notificationId : str
      type           : str
      title          : str
      body           : str
      caseId         : str
      assignedTo     : str (uid or "admin_pool")
      priority       : "high" | "normal"
      read           : false
      createdAt      : SERVER_TIMESTAMP
    """
    _TYPE_MAP = {
        "eligible":     ("CASE_QUALIFIED",    "high"),
        "ineligible":   ("CASE_DISQUALIFIED", "normal"),
        "needs_review": ("CASE_NEEDS_REVIEW", "high"),
    }
    notif_type, priority = _TYPE_MAP.get(eligibility, ("CASE_SCREENED", "normal"))
    full_name = f"{first_name} {last_name}".strip()

    if eligibility == "eligible":
        title = f"Case {case_id} qualified for VCF"
        body  = f"{full_name} passed VCF screening (score: {score}). Ready to convert to active case."
    elif eligibility == "ineligible":
        title = f"Case {case_id} did not qualify"
        body  = f"{full_name} did not meet VCF eligibility criteria."
    else:
        flag_summary = "; ".join(flags[:3]) if flags else "See screening details"
        title = f"Case {case_id} requires manual review"
        body  = f"Flags: {flag_summary}"

    notif_ref = db.collection("notifications").document()
    try:
        await notif_ref.set({
            "notificationId": notif_ref.id,
            "type":           notif_type,
            "title":          title,
            "body":           body,
            "caseId":         case_id,
            "assignedTo":     assigned_to or "admin_pool",
            "priority":       priority,
            "read":           False,
            "createdAt":      firestore.SERVER_TIMESTAMP,
        })
        logger.info(
            "staff_notification_written",
            case_id=case_id,
            notif_type=notif_type,
            assigned_to=assigned_to,
        )
    except Exception as exc:
        # Non-fatal — case is already created and screened; notification is supplementary
        logger.error("staff_notification_write_failed", case_id=case_id, error=str(exc))


async def apply_vcf_screening_result(
    case_id:           str,
    eligibility:       str,
    new_status:        str,
    screening_details: dict,
    db:                firestore.AsyncClient,
) -> None:
    """
    Write VCF screening results to the case document.
    Called synchronously from POST /leads immediately after run_screening().
    """
    settings      = get_settings()
    doc_ref       = db.collection(settings.firestore_cases_collection).document(case_id)
    now           = datetime.utcnow()
    history_entry = {
        "status":    new_status,
        "timestamp": now.isoformat(),
        "updatedBy": "vcf-screener-inline",
        "note":      f"VCF screening: {eligibility} (score={screening_details.get('score', 0)})",
    }
    await doc_ref.update({
        "vcfEligibility":      eligibility,
        "vcfScreeningDetails": screening_details,
        "status":              new_status,
        "statusHistory":       firestore.ArrayUnion([history_entry]),
        "updatedAt":           firestore.SERVER_TIMESTAMP,
    })
    logger.info(
        "vcf_screening_applied",
        case_id=case_id,
        eligibility=eligibility,
        status=new_status,
    )


async def get_case(case_id: str, db: firestore.AsyncClient) -> Optional[CaseDocument]:
    settings = get_settings()
    doc      = await db.collection(settings.firestore_cases_collection).document(case_id).get()
    if not doc.exists:
        return None
    try:
        data = doc.to_dict()
        # Decrypt ssn_encrypted → ssn (in-memory only, never re-persisted as plaintext)
        if data.get("ssn_encrypted"):
            try:
                from shared.crypto import decrypt_ssn
                data["ssn"] = decrypt_ssn(data["ssn_encrypted"])
            except Exception as exc:
                logger.error("ssn_decryption_failed", case_id=case_id, error=str(exc))
                data["ssn"] = None
        return CaseDocument(**data)
    except Exception as exc:
        logger.error("case_deserialisation_failed", case_id=case_id, error=str(exc))
        raise


async def list_cases(db: firestore.AsyncClient, filters: dict, limit: int = 50) -> list[dict]:
    settings = get_settings()
    query    = db.collection(settings.firestore_cases_collection)
    if filters.get("status"):
        query = query.where("status", "==", filters["status"])
    if filters.get("vcfEligibility"):
        query = query.where("vcfEligibility", "==", filters["vcfEligibility"])
    query = query.order_by("createdAt", direction=firestore.Query.DESCENDING).limit(limit)
    return [doc.to_dict() async for doc in query.stream()]


async def update_case_status(
    case_id:    str,
    new_status: str,
    updated_by: str,
    note:       str,
    db:         firestore.AsyncClient,
) -> None:
    settings      = get_settings()
    now           = datetime.utcnow()
    doc_ref       = db.collection(settings.firestore_cases_collection).document(case_id)
    history_entry = {
        "status":    new_status,
        "timestamp": now.isoformat(),
        "updatedBy": updated_by,
        "note":      note,
    }
    update_payload = {
        "status":        new_status,
        "statusHistory": firestore.ArrayUnion([history_entry]),
        "updatedAt":     firestore.SERVER_TIMESTAMP,
    }
    # When a lead is activated it becomes a full case — flip the flag
    if new_status == CaseStatus.ACTIVE.value:
        update_payload["isLead"] = False

    await doc_ref.update(update_payload)
    logger.info(
        "case_status_updated",
        case_id=case_id,
        new_status=new_status,
        updated_by=updated_by,
    )


async def update_case_vcf_status(
    case_id:           str,
    vcf_eligibility:   str,
    screening_details: dict,
    db:                firestore.AsyncClient,
) -> None:
    """Manual override — updates VCF fields without touching status history."""
    settings = get_settings()
    doc_ref  = db.collection(settings.firestore_cases_collection).document(case_id)
    await doc_ref.update({
        "vcfEligibility":      vcf_eligibility,
        "vcfScreeningDetails": screening_details,
        "updatedAt":           firestore.SERVER_TIMESTAMP,
    })
    logger.info("case_vcf_updated", case_id=case_id, vcf_eligibility=vcf_eligibility)


# ── Transactional case assignment ────────────────────────────────────────────

class AssignmentConflict(Exception):
    """Raised when a case already has an assignedParalegal."""
    def __init__(self, case_id: str, existing_assignee: str):
        self.case_id = case_id
        self.existing_assignee = existing_assignee
        super().__init__(
            f"Case {case_id} already assigned to {existing_assignee}"
        )


async def assign_case_transactional(
    case_id:    str,
    assignee:   str,
    db:         firestore.AsyncClient,
) -> dict:
    """
    Assign a paralegal to a case inside a Firestore transaction.

    Read-check-write pattern:
      1. Read the case document inside the transaction.
      2. If assignment.assignedParalegal is already set → raise AssignmentConflict
         (the caller decides whether to skip or surface the conflict).
      3. Otherwise, write the assignment atomically.

    Returns the written assignment dict on success.
    Raises AssignmentConflict if already assigned.
    Raises ValueError if the case document does not exist.
    """
    settings = get_settings()
    doc_ref  = db.collection(settings.firestore_cases_collection).document(case_id)

    @firestore.async_transactional
    async def _txn(transaction: AsyncTransaction):
        snapshot = await doc_ref.get(transaction=transaction)

        if not snapshot.exists:
            raise ValueError(f"Case {case_id} not found")

        data = snapshot.to_dict()
        existing_assignment = data.get("assignment") or {}
        existing_paralegal  = existing_assignment.get("assignedParalegal")

        if existing_paralegal:
            raise AssignmentConflict(case_id, existing_paralegal)

        assignment_payload = {
            "assignment.assignedParalegal": assignee,
            "assignment.assignmentDate":    firestore.SERVER_TIMESTAMP,
            "updatedAt":                    firestore.SERVER_TIMESTAMP,
        }
        transaction.update(doc_ref, assignment_payload)

        logger.info(
            "case_assigned_transactional",
            case_id=case_id,
            assignee=assignee,
        )
        return {"assignedParalegal": assignee, "case_id": case_id}

    transaction = db.transaction()
    return await _txn(transaction)
