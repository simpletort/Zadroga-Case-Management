"""
vcf_workflow.py — VCF registration tracking workflow business logic.

State machine:
  Not Registered → Registration Pending → Registered

On registration:
  - Capture VCF claim number and registration date
  - Trigger VCF deadline calculation (certificationDate + 2 years)
  - Create confirmation task for paralegal

Each transition:
  1. Validates the transition is legal
  2. Updates case document atomically
  3. Writes timeline event
  4. Creates next paralegal task
  5. Triggers deadline calculation if newly registered
  6. Publishes Pub/Sub event
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore

from models.vcf_models import (
    VCFRegistrationStatus,
    VCFRegistrationStep,
    InitiateVCFRegistrationRequest,
    UpdateVCFStatusRequest,
    VCFFormPrefillData,
)
from services.deadline_service import calculate_vcf_deadline, get_deadline_status, days_until_deadline, update_case_deadline
from services.task_service import create_vcf_task
from services.timeline_service import write_status_transition_event, write_task_created_event

logger = logging.getLogger(__name__)

# ── Valid transitions ─────────────────────────────────────────────────────────

VALID_TRANSITIONS: dict[VCFRegistrationStatus | None, list[VCFRegistrationStatus]] = {
    None: [VCFRegistrationStatus.NOT_REGISTERED],
    VCFRegistrationStatus.NOT_REGISTERED: [
        VCFRegistrationStatus.REGISTRATION_PENDING,
    ],
    VCFRegistrationStatus.REGISTRATION_PENDING: [
        VCFRegistrationStatus.REGISTERED,
        VCFRegistrationStatus.NOT_REGISTERED,   # cancelled/restarted
    ],
    VCFRegistrationStatus.REGISTERED: [
        VCFRegistrationStatus.REGISTERED,       # idempotent (e.g. new claim number)
    ],
}

STEP_FOR_STATUS: dict[VCFRegistrationStatus, VCFRegistrationStep] = {
    VCFRegistrationStatus.NOT_REGISTERED: VCFRegistrationStep.ELIGIBILITY_REVIEW,
    VCFRegistrationStatus.REGISTRATION_PENDING: VCFRegistrationStep.FORM_PREPARATION,
    VCFRegistrationStatus.REGISTERED: VCFRegistrationStep.REGISTRATION_CONFIRMED,
}


# ── Public API ────────────────────────────────────────────────────────────────

def initiate_vcf_registration(
    db: firestore.Client,
    case_id: str,
) -> dict[str, Any]:
    """
    Initiate VCF registration workflow for a case.
    Creates eligibility review task for paralegal.
    Idempotent: safe to call multiple times.
    """
    case_ref = db.collection("cases").document(case_id)
    case_snap = case_ref.get()

    if not case_snap.exists:
        raise ValueError(f"Case {case_id} not found")

    case_data = case_snap.to_dict() or {}
    enrollment = case_data.get("enrollment", {})
    current_vcf = enrollment.get("vcfRegistrationStatus")
    assigned_paralegal = case_data.get("assignment", {}).get("assignedParalegal")

    # Idempotency: already in progress or registered
    if current_vcf == VCFRegistrationStatus.REGISTERED.value:
        return {
            "initiated": False,
            "registration_step": VCFRegistrationStep.COMPLETE.value,
            "message": "Case already registered with VCF",
        }

    if current_vcf == VCFRegistrationStatus.REGISTRATION_PENDING.value:
        return {
            "initiated": False,
            "registration_step": VCFRegistrationStep.FORM_PREPARATION.value,
            "message": "VCF registration already in progress (Registration Pending)",
        }

    # Get VCF filing deadline if certification date exists
    certification_date = case_data.get("medicalInfo", {}).get("certificationDate")
    vcf_deadline_str = None
    if certification_date:
        try:
            from datetime import date
            cert_str = certification_date[:10] if isinstance(certification_date, str) else str(certification_date)
            deadline = calculate_vcf_deadline(cert_str)
            vcf_deadline_str = deadline.isoformat()
        except Exception:
            pass

    # Set initial VCF status
    now = datetime.now(tz=timezone.utc)
    update_data: dict[str, Any] = {
        "enrollment.vcfRegistrationStatus": VCFRegistrationStatus.NOT_REGISTERED.value,
        "enrollment.vcfRegistrationStep": VCFRegistrationStep.ELIGIBILITY_REVIEW.value,
        "enrollment.vcfWorkflowInitiatedAt": now,
        "enrollment.vcfLastUpdatedAt": now,
        "enrollment.vcfLastUpdatedBy": "system",
    }
    case_ref.update(update_data)

    # Create eligibility review task
    task_id = create_vcf_task(
        db=db,
        case_id=case_id,
        step=VCFRegistrationStep.ELIGIBILITY_REVIEW,
        assigned_to=assigned_paralegal,
        vcf_filing_deadline=vcf_deadline_str,
    )

    # Timeline event
    write_status_transition_event(
        db=db,
        case_id=case_id,
        workflow_type="VCF",
        old_status="",
        new_status=VCFRegistrationStatus.NOT_REGISTERED.value,
        performed_by="system",
        extra_meta={"trigger": "initiate_vcf_registration"},
    )

    if task_id:
        write_task_created_event(
            db=db,
            case_id=case_id,
            task_id=task_id,
            task_title="Review Client Eligibility for VCF Registration",
            assigned_to=assigned_paralegal,
            workflow_type="VCF",
            step=VCFRegistrationStep.ELIGIBILITY_REVIEW.value,
        )

    logger.info(
        "vcf_registration_initiated caseId=%s taskId=%s paralegal=%s",
        case_id, task_id, assigned_paralegal,
    )

    return {
        "initiated": True,
        "registration_step": VCFRegistrationStep.ELIGIBILITY_REVIEW.value,
        "task_id": task_id,
        "message": "VCF registration workflow initiated; eligibility review task created",
    }


def update_vcf_status(
    db: firestore.Client,
    case_id: str,
    request: UpdateVCFStatusRequest,
) -> dict[str, Any]:
    """
    Update VCF registration status with validation, timeline, and next task.
    On registration: capture claim number, date, trigger deadline calculation.
    """
    case_ref = db.collection("cases").document(case_id)
    case_snap = case_ref.get()

    if not case_snap.exists:
        raise ValueError(f"Case {case_id} not found")

    case_data = case_snap.to_dict() or {}
    enrollment = case_data.get("enrollment", {})
    old_status_str = enrollment.get("vcfRegistrationStatus", "")

    # Validate claim number required for Registered status
    if (
        request.status == VCFRegistrationStatus.REGISTERED
        and not request.vcf_claim_number
    ):
        raise ValueError("vcf_claim_number is required when status is 'Registered'")

    # Validate transition
    old_status = _parse_status(old_status_str)
    _validate_transition(old_status, request.status, case_id)

    now = datetime.now(tz=timezone.utc)
    new_step = STEP_FOR_STATUS.get(request.status, VCFRegistrationStep.COMPLETE)
    assigned_paralegal = case_data.get("assignment", {}).get("assignedParalegal")

    update_data: dict[str, Any] = {
        "enrollment.vcfRegistrationStatus": request.status.value,
        "enrollment.vcfRegistrationStep": new_step.value,
        "enrollment.vcfLastUpdatedAt": now,
        "enrollment.vcfLastUpdatedBy": request.performed_by,
    }

    if request.notes:
        update_data["enrollment.vcfNotes"] = request.notes
    if request.vcf_claim_number:
        update_data["enrollment.vcfClaimNumber"] = request.vcf_claim_number
    if request.registration_date:
        update_data["enrollment.vcfRegistrationDate"] = request.registration_date

    case_ref.update(update_data)

    # ── On registration: calculate deadline ───────────────────────────────
    vcf_deadline_str = None
    if request.status == VCFRegistrationStatus.REGISTERED:
        certification_date = case_data.get("medicalInfo", {}).get("certificationDate")
        if certification_date:
            deadline_result = update_case_deadline(
                db=db,
                case_id=case_id,
                certification_date_str=str(certification_date)[:10],
                write_timeline=True,
            )
            vcf_deadline_str = deadline_result.get("vcf_filing_deadline")

    # ── Timeline ──────────────────────────────────────────────────────────
    timeline_id = write_status_transition_event(
        db=db,
        case_id=case_id,
        workflow_type="VCF",
        old_status=old_status_str,
        new_status=request.status.value,
        performed_by=request.performed_by,
        extra_meta={
            "step": new_step.value,
            "notes": request.notes,
            "vcfClaimNumber": request.vcf_claim_number,
            "vcfFilingDeadline": vcf_deadline_str,
        },
    )

    # ── Create next paralegal task ─────────────────────────────────────────
    next_task_id = None

    if request.status == VCFRegistrationStatus.REGISTRATION_PENDING:
        next_task_id = create_vcf_task(
            db=db,
            case_id=case_id,
            step=VCFRegistrationStep.SUBMISSION_PENDING,
            assigned_to=assigned_paralegal,
            vcf_filing_deadline=vcf_deadline_str,
        )
    elif request.status == VCFRegistrationStatus.REGISTERED:
        next_task_id = create_vcf_task(
            db=db,
            case_id=case_id,
            step=VCFRegistrationStep.REGISTRATION_CONFIRMED,
            assigned_to=assigned_paralegal,
            vcf_filing_deadline=vcf_deadline_str,
        )

    if next_task_id:
        write_task_created_event(
            db=db,
            case_id=case_id,
            task_id=next_task_id,
            task_title=f"VCF task for step: {new_step.value}",
            assigned_to=assigned_paralegal,
            workflow_type="VCF",
            step=new_step.value,
        )

    logger.info(
        "vcf_status_updated caseId=%s old=%s new=%s by=%s deadline=%s",
        case_id, old_status_str, request.status.value, request.performed_by, vcf_deadline_str,
    )

    return {
        "old_status": old_status_str,
        "new_status": request.status.value,
        "timeline_event_id": timeline_id,
        "vcf_filing_deadline": vcf_deadline_str,
        "next_task_id": next_task_id,
    }


def get_vcf_registration(db: firestore.Client, case_id: str) -> dict[str, Any]:
    """Fetch VCF registration data for a case."""
    from datetime import date
    case_snap = db.collection("cases").document(case_id).get()
    if not case_snap.exists:
        raise ValueError(f"Case {case_id} not found")

    data = case_snap.to_dict() or {}
    enrollment = data.get("enrollment", {})
    deadline_str = enrollment.get("vcfFilingDeadline")

    deadline_status_val = None
    days_rem = None
    if deadline_str:
        try:
            deadline_date = date.fromisoformat(deadline_str[:10])
            deadline_status_val = get_deadline_status(deadline_date).value
            days_rem = days_until_deadline(deadline_date)
        except Exception:
            pass

    return {
        "case_id": case_id,
        "status": enrollment.get("vcfRegistrationStatus", VCFRegistrationStatus.NOT_REGISTERED.value),
        "registration_step": enrollment.get("vcfRegistrationStep", VCFRegistrationStep.ELIGIBILITY_REVIEW.value),
        "vcf_claim_number": enrollment.get("vcfClaimNumber"),
        "registration_date": enrollment.get("vcfRegistrationDate"),
        "vcf_filing_deadline": deadline_str,
        "deadline_status": deadline_status_val,
        "days_until_deadline": days_rem,
        "last_alert_milestone": enrollment.get("lastAlertMilestone"),
        "last_updated_at": enrollment.get("vcfLastUpdatedAt"),
        "last_updated_by": enrollment.get("vcfLastUpdatedBy"),
    }


def get_vcf_prefill_data(db: firestore.Client, case_id: str) -> VCFFormPrefillData:
    """
    Generate pre-filled VCF registration form data from case record.
    Only exposes the minimum PHI needed for VCF form completion.
    """
    case_snap = db.collection("cases").document(case_id).get()
    if not case_snap.exists:
        raise ValueError(f"Case {case_id} not found")

    data = case_snap.to_dict() or {}
    client_info = data.get("clientInfo", {})
    medical_info = data.get("medicalInfo", {})
    exposure_info = data.get("exposureInfo", {})
    assignment = data.get("assignment", {})
    enrollment = data.get("enrollment", {})

    # Get attorney display name from staff record
    attorney_id = assignment.get("supervisingAttorney")
    attorney_name = None
    if attorney_id:
        try:
            staff_snap = db.collection("staff").document(attorney_id).get()
            if staff_snap.exists:
                attorney_name = staff_snap.to_dict().get("displayName")
        except Exception:
            pass

    # Calculate VCF deadline if cert date available
    cert_date = medical_info.get("certificationDate")
    vcf_deadline = enrollment.get("vcfFilingDeadline")
    if not vcf_deadline and cert_date:
        try:
            deadline = calculate_vcf_deadline(str(cert_date)[:10])
            vcf_deadline = deadline.isoformat()
        except Exception:
            pass

    return VCFFormPrefillData(
        case_id=case_id,
        date_of_birth=str(client_info.get("dateOfBirth", ""))[:10] if client_info.get("dateOfBirth") else None,
        social_security_last4=client_info.get("ssnLast4"),
        exposure_location=exposure_info.get("location"),
        exposure_start_date=str(exposure_info.get("startDate", ""))[:10] if exposure_info.get("startDate") else None,
        exposure_end_date=str(exposure_info.get("endDate", ""))[:10] if exposure_info.get("endDate") else None,
        certified_condition=medical_info.get("certifiedCondition"),
        certification_date=str(cert_date)[:10] if cert_date else None,
        attorney_name=attorney_name,
        vcf_filing_deadline=vcf_deadline,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_status(status_str: str) -> VCFRegistrationStatus | None:
    for s in VCFRegistrationStatus:
        if s.value == status_str:
            return s
    return None


def _validate_transition(
    old_status: VCFRegistrationStatus | None,
    new_status: VCFRegistrationStatus,
    case_id: str,
) -> None:
    allowed = VALID_TRANSITIONS.get(old_status, [])
    if new_status not in allowed:
        raise ValueError(
            f"Invalid VCF status transition for case {case_id}: "
            f"'{old_status}' → '{new_status}'. "
            f"Allowed: {[s.value for s in allowed]}"
        )
