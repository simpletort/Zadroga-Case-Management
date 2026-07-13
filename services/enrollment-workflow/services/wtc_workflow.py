"""
wtc_workflow.py — WTC Health Program enrollment workflow business logic.

State machine:
  Not Enrolled → Application Pending → Enrolled
  Edge cases: Already Enrolled (skip), Deceased (skip)

Each transition:
  1. Validates the transition is legal
  2. Updates case document atomically
  3. Writes timeline event
  4. Creates next paralegal task
  5. Publishes Pub/Sub event
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore

from models.wtc_models import (
    WTCEnrollmentStatus,
    WTCWorkflowStep,
    UpdateWTCStatusRequest,
)
from services.timeline_service import write_status_transition_event, write_task_created_event
from services.task_service import create_wtc_task

logger = logging.getLogger(__name__)

# ── Valid transitions ─────────────────────────────────────────────────────────

VALID_TRANSITIONS: dict[WTCEnrollmentStatus | None, list[WTCEnrollmentStatus]] = {
    None: [WTCEnrollmentStatus.NOT_ENROLLED],
    WTCEnrollmentStatus.NOT_ENROLLED: [
        WTCEnrollmentStatus.APPLICATION_PENDING,
        WTCEnrollmentStatus.ALREADY_ENROLLED,
        WTCEnrollmentStatus.DECEASED,
    ],
    WTCEnrollmentStatus.APPLICATION_PENDING: [
        WTCEnrollmentStatus.ENROLLED,
        WTCEnrollmentStatus.NOT_ENROLLED,   # withdrawn/restarted
        WTCEnrollmentStatus.DECEASED,
    ],
    WTCEnrollmentStatus.ENROLLED: [
        WTCEnrollmentStatus.ENROLLED,       # idempotent update (e.g. new member ID)
    ],
    WTCEnrollmentStatus.ALREADY_ENROLLED: [],
    WTCEnrollmentStatus.DECEASED: [],
}

# ── Step after transition ─────────────────────────────────────────────────────

STEP_FOR_STATUS: dict[WTCEnrollmentStatus, WTCWorkflowStep] = {
    WTCEnrollmentStatus.NOT_ENROLLED: WTCWorkflowStep.PARALEGAL_TASK_CREATED,
    WTCEnrollmentStatus.APPLICATION_PENDING: WTCWorkflowStep.APPLICATION_SUBMITTED,
    WTCEnrollmentStatus.ENROLLED: WTCWorkflowStep.ENROLLMENT_CONFIRMED,
    WTCEnrollmentStatus.ALREADY_ENROLLED: WTCWorkflowStep.WORKFLOW_SKIPPED,
    WTCEnrollmentStatus.DECEASED: WTCWorkflowStep.WORKFLOW_SKIPPED,
}


# ── Public API ────────────────────────────────────────────────────────────────

def trigger_wtc_workflow(
    db: firestore.Client,
    case_id: str,
    force: bool = False,
) -> dict[str, Any]:
    """
    Trigger WTC enrollment workflow for a case identified as not enrolled.

    Returns dict with triggered status and task_id.
    Idempotent: safe to call multiple times (checks current state first).
    """
    case_ref = db.collection("cases").document(case_id)
    case_snap = case_ref.get()

    if not case_snap.exists:
        raise ValueError(f"Case {case_id} not found")

    case_data = case_snap.to_dict() or {}
    enrollment = case_data.get("enrollment", {})
    current_wtc = enrollment.get("wtcEnrollmentStatus")
    case_status = case_data.get("status", "")

    # ── Edge case: deceased ────────────────────────────────────────────────
    if case_status.lower() in ("deceased", "closed - deceased"):
        _write_skip_event(db, case_id, reason="deceased", performed_by="system")
        _update_case_wtc_status(db, case_ref, case_id, WTCEnrollmentStatus.DECEASED, {})
        return {
            "triggered": False,
            "workflow_step": WTCWorkflowStep.WORKFLOW_SKIPPED.value,
            "message": "Workflow skipped: case marked as deceased",
        }

    # ── Edge case: already enrolled ────────────────────────────────────────
    if current_wtc == WTCEnrollmentStatus.ENROLLED.value and not force:
        _write_skip_event(db, case_id, reason="already_enrolled", performed_by="system")
        return {
            "triggered": False,
            "workflow_step": WTCWorkflowStep.WORKFLOW_SKIPPED.value,
            "message": "Workflow skipped: case already enrolled in WTC Health Program",
        }

    if current_wtc == WTCEnrollmentStatus.APPLICATION_PENDING.value and not force:
        return {
            "triggered": False,
            "workflow_step": WTCWorkflowStep.APPLICATION_SUBMITTED.value,
            "message": "Workflow already in progress (Application Pending)",
        }

    # ── Get assigned paralegal for task assignment ─────────────────────────
    assigned_paralegal = case_data.get("assignment", {}).get("assignedParalegal")

    # ── Set initial status and create first task ───────────────────────────
    now = datetime.now(tz=timezone.utc)
    enrollment_update = {
        "enrollment.wtcEnrollmentStatus": WTCEnrollmentStatus.NOT_ENROLLED.value,
        "enrollment.wtcWorkflowStep": WTCWorkflowStep.PARALEGAL_TASK_CREATED.value,
        "enrollment.wtcWorkflowTriggeredAt": now,
        "enrollment.wtcLastUpdatedAt": now,
        "enrollment.wtcLastUpdatedBy": "system",
    }
    case_ref.update(enrollment_update)

    # Create paralegal task
    task_id = create_wtc_task(
        db=db,
        case_id=case_id,
        step=WTCWorkflowStep.PARALEGAL_TASK_CREATED,
        assigned_to=assigned_paralegal,
    )

    # Write timeline events
    write_status_transition_event(
        db=db,
        case_id=case_id,
        workflow_type="WTC",
        old_status="",
        new_status=WTCEnrollmentStatus.NOT_ENROLLED.value,
        performed_by="system",
        extra_meta={"trigger": "auto_workflow_trigger"},
    )
    if task_id:
        write_task_created_event(
            db=db,
            case_id=case_id,
            task_id=task_id,
            task_title="Assist Client with WTC Health Program Application",
            assigned_to=assigned_paralegal,
            workflow_type="WTC",
            step=WTCWorkflowStep.PARALEGAL_TASK_CREATED.value,
        )

    logger.info(
        "wtc_workflow_triggered caseId=%s taskId=%s paralegal=%s",
        case_id, task_id, assigned_paralegal,
    )

    return {
        "triggered": True,
        "workflow_step": WTCWorkflowStep.PARALEGAL_TASK_CREATED.value,
        "task_id": task_id,
        "message": "WTC enrollment workflow triggered; paralegal task created",
    }


def update_wtc_status(
    db: firestore.Client,
    case_id: str,
    request: UpdateWTCStatusRequest,
) -> dict[str, Any]:
    """
    Update WTC enrollment status with validation, timeline, and next task.
    Returns dict with timeline_event_id and next_task_id.
    """
    case_ref = db.collection("cases").document(case_id)
    case_snap = case_ref.get()

    if not case_snap.exists:
        raise ValueError(f"Case {case_id} not found")

    case_data = case_snap.to_dict() or {}
    enrollment = case_data.get("enrollment", {})
    old_status_str = enrollment.get("wtcEnrollmentStatus", "")

    # ── Validate transition ────────────────────────────────────────────────
    old_status = _parse_status(old_status_str)
    _validate_transition(old_status, request.status, case_id)

    # ── Build update payload ───────────────────────────────────────────────
    now = datetime.now(tz=timezone.utc)
    new_step = STEP_FOR_STATUS.get(request.status, WTCWorkflowStep.WORKFLOW_COMPLETE)

    update_data: dict[str, Any] = {
        "enrollment.wtcEnrollmentStatus": request.status.value,
        "enrollment.wtcWorkflowStep": new_step.value,
        "enrollment.wtcLastUpdatedAt": now,
        "enrollment.wtcLastUpdatedBy": request.performed_by,
    }

    if request.notes:
        update_data["enrollment.wtcNotes"] = request.notes
    if request.application_date:
        update_data["enrollment.wtcApplicationDate"] = request.application_date
    if request.enrollment_date:
        update_data["enrollment.wtcEnrollmentDate"] = request.enrollment_date
    if request.wtc_member_id:
        update_data["enrollment.wtcMemberId"] = request.wtc_member_id

    case_ref.update(update_data)

    # ── Write timeline event ───────────────────────────────────────────────
    timeline_id = write_status_transition_event(
        db=db,
        case_id=case_id,
        workflow_type="WTC",
        old_status=old_status_str,
        new_status=request.status.value,
        performed_by=request.performed_by,
        extra_meta={
            "step": new_step.value,
            "notes": request.notes,
            "wtcMemberId": request.wtc_member_id,
        },
    )

    # ── Create next paralegal task ─────────────────────────────────────────
    assigned_paralegal = case_data.get("assignment", {}).get("assignedParalegal")
    next_task_id = None

    if request.status == WTCEnrollmentStatus.APPLICATION_PENDING:
        next_task_id = create_wtc_task(
            db=db,
            case_id=case_id,
            step=WTCWorkflowStep.APPLICATION_SUBMITTED,
            assigned_to=assigned_paralegal,
        )
    elif request.status == WTCEnrollmentStatus.ENROLLED:
        next_task_id = create_wtc_task(
            db=db,
            case_id=case_id,
            step=WTCWorkflowStep.ENROLLMENT_CONFIRMED,
            assigned_to=assigned_paralegal,
        )

    if next_task_id:
        write_task_created_event(
            db=db,
            case_id=case_id,
            task_id=next_task_id,
            task_title=f"WTC task for step: {new_step.value}",
            assigned_to=assigned_paralegal,
            workflow_type="WTC",
            step=new_step.value,
        )

    logger.info(
        "wtc_status_updated caseId=%s old=%s new=%s by=%s",
        case_id, old_status_str, request.status.value, request.performed_by,
    )

    return {
        "old_status": old_status_str,
        "new_status": request.status.value,
        "timeline_event_id": timeline_id,
        "next_task_id": next_task_id,
    }


def get_wtc_enrollment(db: firestore.Client, case_id: str) -> dict[str, Any]:
    """Fetch WTC enrollment data for a case."""
    case_snap = db.collection("cases").document(case_id).get()
    if not case_snap.exists:
        raise ValueError(f"Case {case_id} not found")

    data = case_snap.to_dict() or {}
    enrollment = data.get("enrollment", {})

    return {
        "case_id": case_id,
        "status": enrollment.get("wtcEnrollmentStatus", WTCEnrollmentStatus.NOT_ENROLLED.value),
        "workflow_step": enrollment.get("wtcWorkflowStep", WTCWorkflowStep.INITIAL_ASSESSMENT.value),
        "workflow_triggered_at": enrollment.get("wtcWorkflowTriggeredAt"),
        "application_date": enrollment.get("wtcApplicationDate"),
        "enrollment_date": enrollment.get("wtcEnrollmentDate"),
        "wtc_member_id": enrollment.get("wtcMemberId"),
        "notes": enrollment.get("wtcNotes"),
        "last_updated_at": enrollment.get("wtcLastUpdatedAt"),
        "last_updated_by": enrollment.get("wtcLastUpdatedBy"),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_status(status_str: str) -> WTCEnrollmentStatus | None:
    for s in WTCEnrollmentStatus:
        if s.value == status_str:
            return s
    return None


def _validate_transition(
    old_status: WTCEnrollmentStatus | None,
    new_status: WTCEnrollmentStatus,
    case_id: str,
) -> None:
    allowed = VALID_TRANSITIONS.get(old_status, [])
    if new_status not in allowed:
        raise ValueError(
            f"Invalid WTC status transition for case {case_id}: "
            f"'{old_status}' → '{new_status}'. "
            f"Allowed: {[s.value for s in allowed]}"
        )


def _write_skip_event(
    db: firestore.Client,
    case_id: str,
    reason: str,
    performed_by: str,
) -> None:
    from services.timeline_service import write_timeline_event
    write_timeline_event(
        db=db,
        case_id=case_id,
        event_type="WTCWorkflowSkipped",
        description=f"WTC enrollment workflow skipped: {reason.replace('_', ' ')}",
        performed_by=performed_by,
        metadata={"reason": reason},
    )


def _update_case_wtc_status(
    db: firestore.Client,
    case_ref: firestore.DocumentReference,
    case_id: str,
    status: WTCEnrollmentStatus,
    extra: dict,
) -> None:
    now = datetime.now(tz=timezone.utc)
    update = {
        "enrollment.wtcEnrollmentStatus": status.value,
        "enrollment.wtcLastUpdatedAt": now,
        "enrollment.wtcLastUpdatedBy": "system",
        **extra,
    }
    case_ref.update(update)
