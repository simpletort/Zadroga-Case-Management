"""
task_service.py — Auto-creates paralegal tasks for each enrollment workflow step.

Tasks are stored in cases/{caseId}/tasks sub-collection.
Each task has: title, instructions, due_date, priority, status, assigned_to.
Task completion triggers next workflow step via task watcher (external).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from google.cloud import firestore

from models.wtc_models import WTCWorkflowStep
from models.vcf_models import VCFRegistrationStep

logger = logging.getLogger(__name__)

# ── WTC Task Definitions ──────────────────────────────────────────────────────

WTC_TASKS: dict[WTCWorkflowStep, dict[str, Any]] = {
    WTCWorkflowStep.PARALEGAL_TASK_CREATED: {
        "title": "Assist Client with WTC Health Program Application",
        "instructions": (
            "1. Review case record to confirm client is not enrolled in WTC Health Program.\n"
            "2. Contact client to explain WTC Health Program benefits and application process.\n"
            "3. Gather required documentation: proof of exposure, medical records, employment records.\n"
            "4. Complete WTC Health Program application form (Form WTC-APP-001) with client.\n"
            "5. Submit application to WTC Health Program (nyc.gov/health/wtc).\n"
            "6. Record submission date and application reference number in case notes.\n"
            "7. Update case status to 'Application Pending' once submitted.\n"
            "DEADLINE: Submit within 14 days of task assignment."
        ),
        "due_days": 14,
        "priority": "high",
        "category": "WTC Enrollment",
    },
    WTCWorkflowStep.APPLICATION_SUBMITTED: {
        "title": "Follow Up on WTC Health Program Application Status",
        "instructions": (
            "1. Check WTC Health Program portal for application status update.\n"
            "2. Contact WTC program intake office if no update within 30 days.\n"
            "3. Provide any additional documentation requested by WTC program.\n"
            "4. Document all communications in case timeline.\n"
            "5. Update status to 'Enrolled' once confirmation received.\n"
            "6. Capture WTC member ID number when enrollment is confirmed."
        ),
        "due_days": 30,
        "priority": "medium",
        "category": "WTC Enrollment",
    },
    WTCWorkflowStep.ENROLLMENT_CONFIRMED: {
        "title": "Verify and Document WTC Health Program Enrollment",
        "instructions": (
            "1. Obtain WTC enrollment confirmation letter from client or WTC program.\n"
            "2. Verify WTC member ID number is correct.\n"
            "3. Upload enrollment confirmation document to case documents.\n"
            "4. Update case WTC status to 'Enrolled' with enrollment date.\n"
            "5. Notify supervising attorney that client is enrolled.\n"
            "6. Proceed with VCF registration workflow if not yet initiated."
        ),
        "due_days": 7,
        "priority": "high",
        "category": "WTC Enrollment",
    },
}

# ── VCF Task Definitions ──────────────────────────────────────────────────────

VCF_TASKS: dict[VCFRegistrationStep, dict[str, Any]] = {
    VCFRegistrationStep.ELIGIBILITY_REVIEW: {
        "title": "Review Client Eligibility for VCF Registration",
        "instructions": (
            "1. Confirm client has WTC-certified condition (required for VCF).\n"
            "2. Verify 9/11 exposure location is covered by VCF (Ground Zero, Fresh Kills, Pentagon, Shanksville).\n"
            "3. Check exposure dates fall within VCF-eligible period (Sep 11, 2001 – May 30, 2002).\n"
            "4. Confirm client is not registered with VCF under a different law firm.\n"
            "5. Calculate VCF filing deadline: certification date + 2 years.\n"
            "6. Document eligibility review findings in case notes.\n"
            "7. Proceed to registration if eligible; flag attorney if not eligible."
        ),
        "due_days": 7,
        "priority": "high",
        "category": "VCF Registration",
    },
    VCFRegistrationStep.FORM_PREPARATION: {
        "title": "Prepare VCF Registration Form for Client",
        "instructions": (
            "1. Use the VCF pre-fill endpoint to generate form data from case record.\n"
            "2. Access VCF online system at vcf.gov to initiate registration.\n"
            "3. Enter all required claimant information accurately.\n"
            "4. Attach supporting documentation: ID, exposure proof, medical certification.\n"
            "5. Review completed form with supervising attorney before submission.\n"
            "6. Have client review and confirm accuracy of registration details.\n"
            "NOTE: Filing deadline is certification date + 2 years. Do NOT miss this deadline."
        ),
        "due_days": 10,
        "priority": "high",
        "category": "VCF Registration",
    },
    VCFRegistrationStep.SUBMISSION_PENDING: {
        "title": "Submit VCF Registration and Capture Claim Number",
        "instructions": (
            "1. Submit the completed VCF registration form at vcf.gov.\n"
            "2. Capture the VCF Claim Number assigned upon submission.\n"
            "3. Record the registration date (today's date).\n"
            "4. Update case VCF status to 'Registered' with claim number and date.\n"
            "5. Upload VCF confirmation/submission receipt to case documents.\n"
            "6. Set a calendar reminder for 30 days before the filing deadline."
        ),
        "due_days": 5,
        "priority": "high",
        "category": "VCF Registration",
    },
    VCFRegistrationStep.REGISTRATION_CONFIRMED: {
        "title": "Confirm VCF Registration and Begin Filing Preparation",
        "instructions": (
            "1. Verify VCF registration is confirmed and claim number is active.\n"
            "2. Check VCF claimant portal to confirm registration status.\n"
            "3. Begin gathering documents for VCF claim filing.\n"
            "4. Notify supervising attorney that VCF registration is confirmed.\n"
            "5. Schedule client intake meeting to review VCF filing requirements.\n"
            "6. Note VCF filing deadline prominently in case record."
        ),
        "due_days": 14,
        "priority": "medium",
        "category": "VCF Registration",
    },
}


# ── Public API ────────────────────────────────────────────────────────────────

def create_wtc_task(
    db,
    case_id: str,
    step: WTCWorkflowStep | str,
    assigned_to: str | None = None,
    deadline_override: datetime | None = None,
) -> str | None:
    """
    Create a WTC-workflow paralegal task.
    Returns the task document ID, or None if no task defined for this step.
    Accepts either a WTCWorkflowStep enum or a raw string step name.
    """
    # Normalize string → enum so dict lookup works
    if isinstance(step, str):
        try:
            step = WTCWorkflowStep(step)
        except ValueError:
            # Map certification_workflow.py string keys to WTCWorkflowStep values
            _STRING_MAP = {
                "application_prep": WTCWorkflowStep.PARALEGAL_TASK_CREATED,
                "application_followup": WTCWorkflowStep.APPLICATION_SUBMITTED,
                "enrollment_confirmation": WTCWorkflowStep.ENROLLMENT_CONFIRMED,
            }
            step = _STRING_MAP.get(step)
            if step is None:
                logger.warning("create_wtc_task: unknown step string, skipping task creation")
                return None

    task_def = WTC_TASKS.get(step)
    if not task_def:
        return None

    return _create_task(
        db=db,
        case_id=case_id,
        task_def=task_def,
        workflow_type="WTC",
        step=step.value,
        assigned_to=assigned_to,
        deadline_override=deadline_override,
    )


def create_vcf_task(
    db,
    case_id: str,
    step: VCFRegistrationStep | str,
    assigned_to: str | None = None,
    deadline_override: datetime | None = None,
    vcf_filing_deadline: str | None = None,
) -> str | None:
    """
    Create a VCF-workflow paralegal task.
    Returns the task document ID, or None if no task defined for this step.
    Accepts either a VCFRegistrationStep enum or a raw string step name.
    """
    if isinstance(step, str):
        try:
            step = VCFRegistrationStep(step)
        except ValueError:
            # Map registration_workflow.py string keys to VCFRegistrationStep values
            _STRING_MAP = {
                "prepare_registration": VCFRegistrationStep.ELIGIBILITY_REVIEW,
                "submit_registration": VCFRegistrationStep.SUBMISSION_PENDING,
                "confirm_registration": VCFRegistrationStep.REGISTRATION_CONFIRMED,
            }
            step = _STRING_MAP.get(step)
            if step is None:
                logger.warning("create_vcf_task: unknown step string, skipping task creation")
                return None

    task_def = VCF_TASKS.get(step)
    if not task_def:
        return None

    extra = {}
    if vcf_filing_deadline:
        extra["vcfFilingDeadline"] = vcf_filing_deadline
        # Override due_days if deadline is approaching
        extra_instructions = f"\n\nIMPORTANT: VCF filing deadline is {vcf_filing_deadline}."
        task_def = {**task_def, "instructions": task_def["instructions"] + extra_instructions}

    return _create_task(
        db=db,
        case_id=case_id,
        task_def=task_def,
        workflow_type="VCF",
        step=step.value,
        assigned_to=assigned_to,
        deadline_override=deadline_override,
        extra_metadata=extra,
    )


def create_deadline_alert_task(
    db: firestore.Client,
    case_id: str,
    days_remaining: int,
    vcf_filing_deadline: str,
    assigned_to: str | None = None,
) -> str:
    """Create an urgent task when VCF filing deadline is approaching."""
    if days_remaining <= 30:
        priority = "urgent"
        due_days = min(days_remaining - 5, 7)
    elif days_remaining <= 60:
        priority = "high"
        due_days = 14
    else:
        priority = "high"
        due_days = 21

    task_def = {
        "title": f"URGENT: VCF Filing Deadline in {days_remaining} Days — {vcf_filing_deadline}",
        "instructions": (
            f"VCF filing deadline is approaching: {vcf_filing_deadline} ({days_remaining} days remaining).\n\n"
            "ACTION REQUIRED:\n"
            "1. Review current VCF claim filing status immediately.\n"
            "2. Contact client to gather any outstanding documentation.\n"
            "3. Confirm all medical records and exposure evidence is complete.\n"
            "4. Notify supervising attorney of deadline urgency.\n"
            "5. Schedule client meeting within 5 business days if filing not yet submitted.\n"
            "6. Do NOT allow this deadline to pass — missing the VCF deadline is fatal to the claim."
        ),
        "due_days": due_days,
        "priority": priority,
        "category": "VCF Deadline Alert",
    }

    return _create_task(
        db=db,
        case_id=case_id,
        task_def=task_def,
        workflow_type="VCF",
        step="deadline_alert",
        assigned_to=assigned_to,
        extra_metadata={
            "daysRemaining": days_remaining,
            "vcfFilingDeadline": vcf_filing_deadline,
            "alertType": f"deadline_{days_remaining}d",
        },
    )


# ── Internal ──────────────────────────────────────────────────────────────────

def _create_task(
    db,
    case_id: str,
    task_def: dict[str, Any],
    workflow_type: str,
    step: str,
    assigned_to: str | None = None,
    deadline_override: datetime | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> str:
    """Write a task document to cases/{caseId}/tasks and return its ID."""
    task_ref = (
        db.collection("cases")
        .document(case_id)
        .collection("tasks")
        .document()
    )
    task_id = task_ref.id
    now = datetime.now(tz=timezone.utc)
    due_date = deadline_override or (now + timedelta(days=task_def["due_days"]))

    task_ref.set({
        "taskId": task_id,
        "caseId": case_id,
        "title": task_def["title"],
        "instructions": task_def["instructions"],
        "category": task_def.get("category", workflow_type),
        "workflowType": workflow_type,
        "workflowStep": step,
        "status": "pending",
        "priority": task_def["priority"],
        "assignedTo": assigned_to,
        "dueDate": due_date,
        "createdAt": firestore.SERVER_TIMESTAMP,
        "completedAt": None,
        "metadata": extra_metadata or {},
    })

    logger.info(
        "task_created caseId=%s taskId=%s workflow=%s step=%s priority=%s",
        case_id, task_id, workflow_type, step, task_def["priority"],
    )
    return task_id