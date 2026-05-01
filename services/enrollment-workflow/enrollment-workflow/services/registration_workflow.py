"""
Generic Registration Workflow Service.

Implements the state machine for registering a client with any claims fund,
benefits program, or administrative system (e.g. VCF, FDNY claims, state funds).

State machine:
    None → NOT_REGISTERED → REGISTRATION_PENDING → REGISTERED
                          ← NOT_REGISTERED       (rejection / retry)

Each status transition:
  1. Validates the transition is legal.
  2. Writes the new status + step to Firestore.
  3. Creates the appropriate paralegal task for the next action.
  4. Writes a timeline event.
  5. When REGISTERED: validates registration_number is present, triggers
     deadline calculation (certificationDate + 2 years), and creates the
     deadline monitoring task.

Firestore document path: cases/{caseId}
  Fields written under the `enrollment` map:
    registrationStatus, registrationProgram, registrationWorkflowStep,
    registrationNumber, registrationNotes, registrationUpdatedAt,
    registrationUpdatedBy, filingDeadline, deadlineStatus, lastAlertMilestone
"""

from __future__ import annotations

import structlog
from datetime import datetime, timezone
from typing import Optional

from google.cloud.firestore_v1.async_client import AsyncClient

from models.registration_models import (
    DeadlineStatus,
    RegistrationRecord,
    RegistrationStatus,
    RegistrationWorkflowStep,
    RegistrationFormPrefillData,
)
from services.task_service import create_vcf_task, create_deadline_alert_task
from services.deadline_service import update_case_deadline
from services.timeline_service import (
    write_timeline_event,
    write_status_transition_event,
    write_task_created_event,
)

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[Optional[RegistrationStatus], list[RegistrationStatus]] = {
    None: [RegistrationStatus.NOT_REGISTERED],
    RegistrationStatus.NOT_REGISTERED: [RegistrationStatus.REGISTRATION_PENDING],
    RegistrationStatus.REGISTRATION_PENDING: [
        RegistrationStatus.REGISTERED,
        RegistrationStatus.NOT_REGISTERED,  # rejection / retry
    ],
    RegistrationStatus.REGISTERED: [
        RegistrationStatus.REGISTERED,      # idempotent re-confirmation
    ],
}

STATUS_TO_STEP: dict[RegistrationStatus, RegistrationWorkflowStep] = {
    RegistrationStatus.NOT_REGISTERED: RegistrationWorkflowStep.REGISTRATION_INITIATED,
    RegistrationStatus.REGISTRATION_PENDING: RegistrationWorkflowStep.SUBMISSION_PENDING,
    RegistrationStatus.REGISTERED: RegistrationWorkflowStep.REGISTERED,
}

STATUS_TO_NEXT_TASK_STEP: dict[RegistrationStatus, Optional[str]] = {
    RegistrationStatus.NOT_REGISTERED: "prepare_registration",
    RegistrationStatus.REGISTRATION_PENDING: "submit_registration",
    RegistrationStatus.REGISTERED: "confirm_registration",
}


def _validate_transition(
    current: Optional[RegistrationStatus],
    new: RegistrationStatus,
) -> None:
    allowed = VALID_TRANSITIONS.get(current, [])
    if new not in allowed:
        current_str = current.value if current else "None"
        raise ValueError(
            f"Invalid registration status transition: {current_str} → {new.value}. "
            f"Allowed from {current_str}: {[s.value for s in allowed] or 'none (terminal)'}"
        )


async def _read_enrollment(db: AsyncClient, case_id: str) -> dict:
    snap = await db.collection("cases").document(case_id).get()
    if not snap.exists:
        return {}
    data = snap.to_dict() or {}
    return data.get("enrollment", {})


async def _write_registration_fields(
    db: AsyncClient,
    case_id: str,
    fields: dict,
) -> None:
    update = {f"enrollment.{k}": v for k, v in fields.items()}
    await db.collection("cases").document(case_id).update(update)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def initiate_registration(
    db: AsyncClient,
    case_id: str,
    program: str,
    initiated_by: str,
    notes: Optional[str] = None,
) -> dict:
    """
    Idempotently start the registration workflow for a case.

    Prerequisite (enforced by caller): case must have certificationStatus == ENROLLED.
    If already initiated, returns the existing record without overwriting.

    Steps:
      1. Check for existing registration record (idempotency).
      2. Write NOT_REGISTERED + step to Firestore.
      3. Create the initial paralegal task (prepare registration package).
      4. Write timeline event.
    """
    enrollment = await _read_enrollment(db, case_id)
    existing_raw = enrollment.get("registrationStatus")

    if existing_raw:
        log.info(
            "registration_already_exists",
            case_id=case_id,
            program=program,
            existing_status=existing_raw,
        )
        return {
            "case_id": case_id,
            "program": program,
            "status": existing_raw,
            "message": f"Registration workflow already exists with status: {existing_raw}",
            "task_id": None,
        }

    now = datetime.now(tz=timezone.utc)
    await _write_registration_fields(db, case_id, {
        "registrationStatus": RegistrationStatus.NOT_REGISTERED.value,
        "registrationProgram": program,
        "registrationWorkflowStep": RegistrationWorkflowStep.REGISTRATION_INITIATED.value,
        "registrationNotes": notes,
        "registrationUpdatedAt": now.isoformat(),
        "registrationUpdatedBy": initiated_by,
        "registrationCreatedAt": now.isoformat(),
        "deadlineStatus": DeadlineStatus.NOT_SET.value,
    })

    task_id = await create_vcf_task(
        db=db,
        case_id=case_id,
        step="prepare_registration",
        assigned_to=None,
    )

    await write_timeline_event(
        db=db,
        case_id=case_id,
        event_type="registration_workflow_initiated",
        description=f"Registration workflow started for program: {program}",
        performed_by=initiated_by,
        metadata={"program": program, "task_id": task_id},
    )
    await write_task_created_event(
        db=db,
        case_id=case_id,
        task_id=task_id,
        task_title="Prepare registration application package",
        assigned_to=None,
        workflow_type="registration",
        step="prepare_registration",
    )

    log.info("registration_initiated", case_id=case_id, program=program, task_id=task_id)

    return {
        "case_id": case_id,
        "program": program,
        "status": RegistrationStatus.NOT_REGISTERED.value,
        "task_id": task_id,
        "message": "Registration workflow initiated.",
    }


async def update_registration_status(
    db: AsyncClient,
    case_id: str,
    new_status: RegistrationStatus,
    updated_by: str,
    registration_number: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """
    Advance the registration status along the state machine.

    Validation:
      - Transition must be in VALID_TRANSITIONS.
      - registration_number is required when new_status == REGISTERED.

    Side effects on REGISTERED:
      - Stores registration_number on Firestore.
      - Calls update_case_deadline() to calculate and persist the filing deadline
        (certificationDate + deadline_years from config).
      - Creates a CHECK_DEADLINE task and a 90-day monitoring task.
      - Sets deadlineStatus based on days remaining.
    """
    if new_status == RegistrationStatus.REGISTERED and not registration_number:
        raise ValueError("registration_number is required when setting status to REGISTERED.")

    enrollment = await _read_enrollment(db, case_id)
    raw_current = enrollment.get("registrationStatus")
    current_status: Optional[RegistrationStatus] = (
        RegistrationStatus(raw_current) if raw_current else None
    )

    _validate_transition(current_status, new_status)

    new_step = STATUS_TO_STEP[new_status]
    now = datetime.now(tz=timezone.utc)

    update_fields: dict = {
        "registrationStatus": new_status.value,
        "registrationWorkflowStep": new_step.value,
        "registrationUpdatedAt": now.isoformat(),
        "registrationUpdatedBy": updated_by,
    }
    if notes:
        update_fields["registrationNotes"] = notes
    if registration_number:
        update_fields["registrationNumber"] = registration_number

    await _write_registration_fields(db, case_id, update_fields)

    # Create the next-step paralegal task
    task_id: Optional[str] = None
    next_step = STATUS_TO_NEXT_TASK_STEP.get(new_status)
    if next_step:
        task_id = await create_vcf_task(
            db=db,
            case_id=case_id,
            step=next_step,
            assigned_to=None,
        )
        await write_task_created_event(
            db=db,
            case_id=case_id,
            task_id=task_id,
            task_title=f"Registration task: {next_step.replace('_', ' ').title()}",
            assigned_to=None,
            workflow_type="registration",
            step=next_step,
        )

    await write_status_transition_event(
        db=db,
        case_id=case_id,
        workflow_type="registration",
        old_status=current_status.value if current_status else "None",
        new_status=new_status.value,
        performed_by=updated_by,
        metadata={"program": enrollment.get("registrationProgram", "unknown")},
    )

    deadline_info: dict = {}

    # On REGISTERED: calculate the filing deadline and set up monitoring.
    if new_status == RegistrationStatus.REGISTERED:
        certification_date = enrollment.get("certificationDate")
        if certification_date:
            try:
                deadline_info = await update_case_deadline(
                    db=db,
                    case_id=case_id,
                    certification_date_str=certification_date,
                    write_timeline=True,
                )
                # Create deadline monitoring task (check + set alerts at 90/60/30 days)
                filing_deadline = deadline_info.get("filing_deadline")
                if filing_deadline:
                    deadline_task_id = await create_deadline_alert_task(
                        db=db,
                        case_id=case_id,
                        days_remaining=deadline_info.get("days_remaining", 730),
                        vcf_filing_deadline=filing_deadline,
                        assigned_to=None,
                    )
                    log.info(
                        "deadline_monitoring_task_created",
                        case_id=case_id,
                        task_id=deadline_task_id,
                        filing_deadline=filing_deadline,
                    )
            except Exception as exc:
                # Non-fatal: deadline calculation failure should not block registration.
                log.warning(
                    "deadline_calculation_failed",
                    case_id=case_id,
                    error=str(exc),
                )
        else:
            log.warning(
                "no_certification_date_for_deadline",
                case_id=case_id,
                note="Deadline will be calculated when certificationDate is set.",
            )

    log.info(
        "registration_status_updated",
        case_id=case_id,
        previous_status=current_status.value if current_status else None,
        new_status=new_status.value,
        task_id=task_id,
    )

    return {
        "case_id": case_id,
        "previous_status": current_status.value if current_status else None,
        "new_status": new_status.value,
        "workflow_step": new_step.value,
        "task_id": task_id,
        "filing_deadline": deadline_info.get("filing_deadline"),
        "message": f"Registration status updated to {new_status.value}.",
    }


async def get_registration(
    db: AsyncClient,
    case_id: str,
) -> Optional[RegistrationRecord]:
    """
    Retrieve the current registration record for a case.
    Returns None if the registration workflow has not been initiated.
    """
    enrollment = await _read_enrollment(db, case_id)
    if not enrollment.get("registrationStatus"):
        return None

    return RegistrationRecord(
        case_id=case_id,
        program=enrollment.get("registrationProgram", "unknown"),
        status=RegistrationStatus(enrollment["registrationStatus"]),
        workflow_step=RegistrationWorkflowStep(
            enrollment.get(
                "registrationWorkflowStep",
                RegistrationWorkflowStep.REGISTRATION_INITIATED.value,
            )
        ),
        registration_number=enrollment.get("registrationNumber"),
        filing_deadline=enrollment.get("filingDeadline"),
        deadline_status=DeadlineStatus(
            enrollment.get("deadlineStatus", DeadlineStatus.NOT_SET.value)
        ),
        last_alert_milestone=enrollment.get("lastAlertMilestone"),
        notes=enrollment.get("registrationNotes"),
        updated_at=datetime.fromisoformat(
            enrollment.get("registrationUpdatedAt", datetime.utcnow().isoformat())
        ),
        updated_by=enrollment.get("registrationUpdatedBy", "unknown"),
        created_at=datetime.fromisoformat(
            enrollment.get("registrationCreatedAt", datetime.utcnow().isoformat())
        ),
    )


async def get_registration_prefill(
    db: AsyncClient,
    case_id: str,
) -> Optional[RegistrationFormPrefillData]:
    """
    Assemble pre-fill data for the registration form from the case document.
    Returns None if the case does not exist.
    """
    snap = await db.collection("cases").document(case_id).get()
    if not snap.exists:
        return None

    data = snap.to_dict() or {}
    client = data.get("client", {})
    enrollment = data.get("enrollment", {})

    return RegistrationFormPrefillData(
        case_id=case_id,
        program=enrollment.get("registrationProgram", "unknown"),
        first_name=client.get("firstName"),
        last_name=client.get("lastName"),
        date_of_birth=client.get("dateOfBirth"),
        certification_date=enrollment.get("certificationDate"),
        filing_deadline=enrollment.get("filingDeadline"),
        registration_number=enrollment.get("registrationNumber"),
    )
