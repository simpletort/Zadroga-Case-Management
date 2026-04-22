"""
Certification Enrollment Workflow Service.

Implements the state machine for certification-based program enrollment
(e.g. WTC Health Program, VA benefits, any program requiring medical certification).

State machine:
    None → NOT_ENROLLED → APPLICATION_PENDING → ENROLLED
                       └→ ALREADY_ENROLLED (terminal)
                       └→ DECEASED (terminal)

Each status transition:
  1. Validates the transition is legal.
  2. Writes the new status + step to Firestore.
  3. Creates the appropriate paralegal task for the next action.
  4. Writes a timeline event.
  5. When transitioning to ENROLLED, auto-triggers the downstream
     registration workflow (fire-and-forget via Pub/Sub).

Firestore document path: cases/{caseId}
  Fields written under the `enrollment` map:
    certificationStatus, certificationProgram, certificationWorkflowStep,
    certificationDate, certificationNotes, certificationUpdatedAt, certificationUpdatedBy
"""

from __future__ import annotations

import structlog
from datetime import datetime, timezone
from typing import Optional

from google.cloud.firestore_v1.async_client import AsyncClient

from models.certification_models import (
    CertificationStatus,
    CertificationWorkflowStep,
    CertificationEnrollmentRecord,
    CertificationWorkflowTriggerResponse,
    CertificationStatusUpdateResponse,
)
from services.task_service import create_wtc_task
from services.timeline_service import (
    write_timeline_event,
    write_status_transition_event,
    write_task_created_event,
)

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# State machine — only list explicitly allowed transitions.
# Any pair not present here is rejected with HTTP 422.
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[Optional[CertificationStatus], list[CertificationStatus]] = {
    None: [CertificationStatus.NOT_ENROLLED],
    CertificationStatus.NOT_ENROLLED: [
        CertificationStatus.APPLICATION_PENDING,
        CertificationStatus.ALREADY_ENROLLED,
        CertificationStatus.DECEASED,
    ],
    CertificationStatus.APPLICATION_PENDING: [
        CertificationStatus.ENROLLED,
        CertificationStatus.NOT_ENROLLED,   # application rejected — restart
        CertificationStatus.DECEASED,
    ],
    CertificationStatus.ENROLLED: [
        CertificationStatus.ENROLLED,       # idempotent re-confirmation
    ],
    CertificationStatus.ALREADY_ENROLLED: [],   # terminal
    CertificationStatus.DECEASED: [],           # terminal
}

# Map each status to the workflow step that describes where we are after
# that status is reached.
STATUS_TO_STEP: dict[CertificationStatus, CertificationWorkflowStep] = {
    CertificationStatus.NOT_ENROLLED: CertificationWorkflowStep.PARALEGAL_TASK_CREATED,
    CertificationStatus.APPLICATION_PENDING: CertificationWorkflowStep.APPLICATION_PENDING,
    CertificationStatus.ENROLLED: CertificationWorkflowStep.ENROLLMENT_CONFIRMED,
    CertificationStatus.ALREADY_ENROLLED: CertificationWorkflowStep.WORKFLOW_SKIPPED,
    CertificationStatus.DECEASED: CertificationWorkflowStep.WORKFLOW_SKIPPED,
}

# Map each new status to the task step that should be created next.
# None means no task is needed at that transition.
STATUS_TO_NEXT_TASK_STEP: dict[CertificationStatus, Optional[str]] = {
    CertificationStatus.NOT_ENROLLED: "application_prep",
    CertificationStatus.APPLICATION_PENDING: "application_followup",
    CertificationStatus.ENROLLED: "enrollment_confirmation",
    CertificationStatus.ALREADY_ENROLLED: None,
    CertificationStatus.DECEASED: None,
}


def _validate_transition(
    current: Optional[CertificationStatus],
    new: CertificationStatus,
) -> None:
    """Raise ValueError if the transition is not allowed."""
    allowed = VALID_TRANSITIONS.get(current, [])
    if new not in allowed:
        current_str = current.value if current else "None"
        raise ValueError(
            f"Invalid certification status transition: {current_str} → {new.value}. "
            f"Allowed from {current_str}: {[s.value for s in allowed] or 'none (terminal)'}"
        )


async def _read_enrollment(db: AsyncClient, case_id: str) -> dict:
    """Read the enrollment sub-document from Firestore."""
    snap = await db.collection("cases").document(case_id).get()
    if not snap.exists:
        return {}
    data = snap.to_dict() or {}
    return data.get("enrollment", {})


async def _write_certification_fields(
    db: AsyncClient,
    case_id: str,
    fields: dict,
) -> None:
    """Partial-update just the enrollment.certification* fields on the case document."""
    update = {f"enrollment.{k}": v for k, v in fields.items()}
    await db.collection("cases").document(case_id).update(update)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def trigger_certification_workflow(
    db: AsyncClient,
    case_id: str,
    program: str,
    triggered_by: str,
    notes: Optional[str] = None,
) -> CertificationWorkflowTriggerResponse:
    """
    Idempotently start the certification enrollment workflow for a case.

    If the case already has a certification record, return the existing state
    instead of overwriting it (allows safe re-trigger from orchestrator).

    Steps:
      1. Read existing enrollment record.
      2. If already has a non-None certificationStatus → return existing.
      3. Write NOT_ENROLLED + initial step to Firestore.
      4. Create the first paralegal task (application prep).
      5. Write a timeline event.
    """
    enrollment = await _read_enrollment(db, case_id)
    existing_status_raw = enrollment.get("certificationStatus")

    # Idempotency: if a certification record already exists, return it.
    if existing_status_raw:
        existing_status = CertificationStatus(existing_status_raw)
        log.info(
            "certification_workflow_already_exists",
            case_id=case_id,
            program=program,
            existing_status=existing_status_raw,
        )
        return CertificationWorkflowTriggerResponse(
            case_id=case_id,
            program=program,
            status=existing_status,
            workflow_step=CertificationWorkflowStep(
                enrollment.get("certificationWorkflowStep",
                               CertificationWorkflowStep.INITIAL_ASSESSMENT.value)
            ),
            task_id=None,
            message=f"Certification workflow already exists with status: {existing_status.value}",
        )

    now = datetime.now(tz=timezone.utc)

    # Write initial state to Firestore
    await _write_certification_fields(db, case_id, {
        "certificationStatus": CertificationStatus.NOT_ENROLLED.value,
        "certificationProgram": program,
        "certificationWorkflowStep": CertificationWorkflowStep.PARALEGAL_TASK_CREATED.value,
        "certificationNotes": notes,
        "certificationUpdatedAt": now.isoformat(),
        "certificationUpdatedBy": triggered_by,
        "certificationCreatedAt": now.isoformat(),
    })

    # Create the initial paralegal task: prepare the certification application
    task_id = await create_wtc_task(
        db=db,
        case_id=case_id,
        step="application_prep",
        assigned_to=None,
    )

    # Timeline event
    await write_timeline_event(
        db=db,
        case_id=case_id,
        event_type="certification_workflow_triggered",
        description=f"Certification enrollment workflow started for program: {program}",
        performed_by=triggered_by,
        metadata={"program": program, "task_id": task_id},
    )
    await write_task_created_event(
        db=db,
        case_id=case_id,
        task_id=task_id,
        task_title="Prepare certification application",
        assigned_to=None,
        workflow_type="certification",
        step="application_prep",
    )

    log.info(
        "certification_workflow_triggered",
        case_id=case_id,
        program=program,
        task_id=task_id,
    )

    return CertificationWorkflowTriggerResponse(
        case_id=case_id,
        program=program,
        status=CertificationStatus.NOT_ENROLLED,
        workflow_step=CertificationWorkflowStep.PARALEGAL_TASK_CREATED,
        task_id=task_id,
        message="Certification enrollment workflow initiated.",
    )


async def update_certification_status(
    db: AsyncClient,
    case_id: str,
    new_status: CertificationStatus,
    updated_by: str,
    certification_date: Optional[str] = None,
    notes: Optional[str] = None,
) -> CertificationStatusUpdateResponse:
    """
    Advance the certification status along the state machine.

    Validation:
      - Transition must be in VALID_TRANSITIONS.
      - certification_date is required when new_status == ENROLLED.

    Side effects:
      - Writes new status + step + timestamps to Firestore.
      - Creates the next paralegal task for the new status.
      - Writes a timeline status-transition event.
      - When ENROLLED: publishes a Pub/Sub event so the registration workflow
        can be triggered by the orchestrator (fire-and-forget, best-effort).
    """
    if new_status == CertificationStatus.ENROLLED and not certification_date:
        raise ValueError("certification_date is required when setting status to ENROLLED.")

    enrollment = await _read_enrollment(db, case_id)
    raw_current = enrollment.get("certificationStatus")
    current_status: Optional[CertificationStatus] = (
        CertificationStatus(raw_current) if raw_current else None
    )

    _validate_transition(current_status, new_status)

    new_step = STATUS_TO_STEP[new_status]
    now = datetime.now(tz=timezone.utc)

    update_fields: dict = {
        "certificationStatus": new_status.value,
        "certificationWorkflowStep": new_step.value,
        "certificationUpdatedAt": now.isoformat(),
        "certificationUpdatedBy": updated_by,
    }
    if notes:
        update_fields["certificationNotes"] = notes
    if certification_date and new_status == CertificationStatus.ENROLLED:
        update_fields["certificationDate"] = certification_date

    await _write_certification_fields(db, case_id, update_fields)

    # Create next-step paralegal task
    task_id: Optional[str] = None
    next_step = STATUS_TO_NEXT_TASK_STEP.get(new_status)
    if next_step:
        task_id = await create_wtc_task(
            db=db,
            case_id=case_id,
            step=next_step,
            assigned_to=None,
        )
        await write_task_created_event(
            db=db,
            case_id=case_id,
            task_id=task_id,
            task_title=f"Certification task: {next_step.replace('_', ' ').title()}",
            assigned_to=None,
            workflow_type="certification",
            step=next_step,
        )

    # Timeline: status transition
    await write_status_transition_event(
        db=db,
        case_id=case_id,
        workflow_type="certification",
        old_status=current_status.value if current_status else "None",
        new_status=new_status.value,
        performed_by=updated_by,
        metadata={"program": enrollment.get("certificationProgram", "unknown")},
    )

    # When ENROLLED: fire Pub/Sub so orchestrator can trigger registration workflow.
    registration_triggered = False
    if new_status == CertificationStatus.ENROLLED:
        registration_triggered = await _publish_enrollment_confirmed(
            case_id=case_id,
            program=enrollment.get("certificationProgram", "unknown"),
            certification_date=certification_date,
        )

    log.info(
        "certification_status_updated",
        case_id=case_id,
        previous_status=current_status.value if current_status else None,
        new_status=new_status.value,
        task_id=task_id,
    )

    return CertificationStatusUpdateResponse(
        case_id=case_id,
        previous_status=current_status or CertificationStatus.NOT_ENROLLED,
        new_status=new_status,
        workflow_step=new_step,
        task_id=task_id,
        registration_triggered=registration_triggered,
        message=f"Certification status updated to {new_status.value}.",
    )


async def get_certification_enrollment(
    db: AsyncClient,
    case_id: str,
) -> Optional[CertificationEnrollmentRecord]:
    """
    Retrieve the current certification enrollment record for a case.
    Returns None if the workflow has never been triggered for this case.
    """
    enrollment = await _read_enrollment(db, case_id)
    if not enrollment.get("certificationStatus"):
        return None

    return CertificationEnrollmentRecord(
        case_id=case_id,
        program=enrollment.get("certificationProgram", "unknown"),
        status=CertificationStatus(enrollment["certificationStatus"]),
        workflow_step=CertificationWorkflowStep(
            enrollment.get(
                "certificationWorkflowStep",
                CertificationWorkflowStep.INITIAL_ASSESSMENT.value,
            )
        ),
        certification_date=enrollment.get("certificationDate"),
        notes=enrollment.get("certificationNotes"),
        updated_at=datetime.fromisoformat(
            enrollment.get("certificationUpdatedAt", datetime.utcnow().isoformat())
        ),
        updated_by=enrollment.get("certificationUpdatedBy", "unknown"),
        created_at=datetime.fromisoformat(
            enrollment.get("certificationCreatedAt", datetime.utcnow().isoformat())
        ),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _publish_enrollment_confirmed(
    case_id: str,
    program: str,
    certification_date: Optional[str],
) -> bool:
    """
    Publish a certification.enrolled Pub/Sub event so the orchestrator can
    trigger the downstream registration workflow automatically.

    Returns True if published successfully, False on error (non-fatal).
    """
    try:
        from google.cloud import pubsub_v1
        from config import settings
        import json

        publisher = pubsub_v1.PublisherClient()
        topic = publisher.topic_path(
            settings.gcp_project_id,
            settings.pubsub_topic_enrollment,
        )
        payload = {
            "event_type": "certification.enrolled",
            "source": "enrollment-workflow",
            "data": {
                "case_id": case_id,
                "program": program,
                "certification_date": certification_date,
            },
        }
        future = publisher.publish(
            topic,
            data=json.dumps(payload).encode("utf-8"),
            event_type="certification.enrolled",
        )
        future.result()
        log.info("certification_enrolled_event_published", case_id=case_id, program=program)
        return True
    except Exception as exc:
        # Non-fatal: the orchestrator can also poll for enrolled status.
        log.warning(
            "certification_enrolled_publish_failed",
            case_id=case_id,
            error=str(exc),
        )
        return False
