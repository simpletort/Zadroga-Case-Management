"""
Orchestrator Adapter Router.

Prefix: /api/v1/enrollment

This router exposes the EXACT API paths expected by the Workflow Orchestrator's
`vcf-enrollment.yaml` Cloud Workflow YAML. It is an adapter layer — the
orchestrator speaks in WTC/VCF terms, but this service uses generic
certification/registration terminology internally.

Path contract (from workflow-orchestrator/cloud_workflows/vcf-enrollment.yaml):

  GET  /api/v1/enrollment/wtc-status?case_id={case_id}
       → { "wtc_enrolled": bool }
       Called by orchestrator to check if certification is complete before
       deciding whether to initiate registration.

  PUT  /api/v1/enrollment/wtc-status
       body: { "case_id": str, "action": "initiate_enrollment", "updated_by": str }
       → { "case_id": str, "status": str, "task_id": str | null }
       Called by orchestrator to trigger the certification enrollment workflow.

  GET  /api/v1/enrollment/vcf-status?case_id={case_id}
       → { "vcf_registered": bool }
       Called by orchestrator to check if registration is complete.

  PUT  /api/v1/enrollment/vcf-status
       body: { "case_id": str, "action": "submit_registration", "updated_by": str }
       → { "case_id": str, "status": str, "task_id": str | null }
       Called by orchestrator to trigger the registration workflow.

  GET  /api/v1/enrollment/deadlines?case_id={case_id}
       → { "wtc_deadline": str | null, "vcf_submission_deadline": str | null }
       Called by orchestrator to retrieve deadline dates for scheduling
       Cloud Tasks reminder callbacks.

IMPORTANT: These endpoints are called by the GCP Cloud Workflows runtime,
not by human users. They are authenticated via the service account that runs
the Cloud Workflow execution. The orchestrator uses Google-signed OIDC tokens.

Do NOT add breaking changes to these response shapes without also updating
vcf-enrollment.yaml in the workflow-orchestrator service.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from services.firestore_client import get_db as _get_db
from pydantic import BaseModel
from typing import Optional

from models.certification_models import CertificationStatus
from models.registration_models import RegistrationStatus
from services.certification_workflow import (
    get_certification_enrollment,
    trigger_certification_workflow,
)
from services.registration_workflow import (
    get_registration,
    initiate_registration,
)

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/enrollment", tags=["Orchestrator Adapter"])


# def _get_db():
    # return firestore.AsyncClient()


# ---------------------------------------------------------------------------
# Request body models for PUT endpoints
# ---------------------------------------------------------------------------

class WTCStatusAction(BaseModel):
    """
    Body for PUT /api/v1/enrollment/wtc-status.
    action must be "initiate_enrollment".
    """
    case_id: str
    action: str          # "initiate_enrollment"
    updated_by: str = "workflow-orchestrator"


class VCFStatusAction(BaseModel):
    """
    Body for PUT /api/v1/enrollment/vcf-status.
    action must be "submit_registration".
    """
    case_id: str
    action: str          # "submit_registration"
    updated_by: str = "workflow-orchestrator"


# ---------------------------------------------------------------------------
# Orchestrator endpoint: WTC certification status
# ---------------------------------------------------------------------------

@router.get(
    "/wtc-status",
    summary="[Orchestrator] Check if certification enrollment is complete",
    description=(
        "Called by vcf-enrollment.yaml Cloud Workflow. "
        "Returns wtc_enrolled: true when certificationStatus == ENROLLED."
    ),
)
async def get_wtc_status(
    case_id: str = Query(..., description="Firestore case document ID"),
):
    db = _get_db()
    try:
        record = await get_certification_enrollment(db=db, case_id=case_id)
        enrolled = (
            record is not None
            and record.status == CertificationStatus.ENROLLED
        )
        log.info(
            "orchestrator_wtc_status_check",
            case_id=case_id,
            wtc_enrolled=enrolled,
        )
        return {
            "case_id": case_id,
            "wtc_enrolled": enrolled,
            "certification_status": record.status.value if record else None,
        }
    except Exception as exc:
        log.error("orchestrator_wtc_status_error", case_id=case_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.put(
    "/wtc-status",
    summary="[Orchestrator] Initiate certification enrollment workflow",
    description=(
        "Called by vcf-enrollment.yaml Cloud Workflow with action='initiate_enrollment'. "
        "Triggers the certification workflow (idempotent)."
    ),
)
async def put_wtc_status(body: WTCStatusAction):
    if body.action != "initiate_enrollment":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown action '{body.action}'. Expected 'initiate_enrollment'.",
        )

    db = _get_db()
    try:
        result = await trigger_certification_workflow(
            db=db,
            case_id=body.case_id,
            program="wtc",           # orchestrator always uses WTC program
            triggered_by=body.updated_by,
        )
        log.info(
            "orchestrator_wtc_enrollment_triggered",
            case_id=body.case_id,
            status=result.status.value,
        )
        return {
            "case_id": body.case_id,
            "status": result.status.value,
            "workflow_step": result.workflow_step.value,
            "task_id": result.task_id,
            "message": result.message,
        }
    except Exception as exc:
        log.error("orchestrator_wtc_trigger_error", case_id=body.case_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


# ---------------------------------------------------------------------------
# Orchestrator endpoint: VCF registration status
# ---------------------------------------------------------------------------

@router.get(
    "/vcf-status",
    summary="[Orchestrator] Check if registration is complete",
    description=(
        "Called by vcf-enrollment.yaml Cloud Workflow. "
        "Returns vcf_registered: true when registrationStatus == REGISTERED."
    ),
)
async def get_vcf_status(
    case_id: str = Query(..., description="Firestore case document ID"),
):
    db = _get_db()
    try:
        record = await get_registration(db=db, case_id=case_id)
        registered = (
            record is not None
            and record.status == RegistrationStatus.REGISTERED
        )
        log.info(
            "orchestrator_vcf_status_check",
            case_id=case_id,
            vcf_registered=registered,
        )
        return {
            "case_id": case_id,
            "vcf_registered": registered,
            "registration_status": record.status.value if record else None,
            "registration_number": record.registration_number if record else None,
        }
    except Exception as exc:
        log.error("orchestrator_vcf_status_error", case_id=case_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.put(
    "/vcf-status",
    summary="[Orchestrator] Initiate registration workflow",
    description=(
        "Called by vcf-enrollment.yaml Cloud Workflow with action='submit_registration'. "
        "Triggers the registration workflow (idempotent)."
    ),
)
async def put_vcf_status(body: VCFStatusAction):
    if body.action != "submit_registration":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown action '{body.action}'. Expected 'submit_registration'.",
        )

    db = _get_db()
    try:
        result = await initiate_registration(
            db=db,
            case_id=body.case_id,
            program="vcf",           # orchestrator always uses VCF program
            initiated_by=body.updated_by,
        )
        log.info(
            "orchestrator_vcf_registration_triggered",
            case_id=body.case_id,
            status=result.get("status"),
        )
        return {
            "case_id": body.case_id,
            "status": result.get("status"),
            "task_id": result.get("task_id"),
            "message": result.get("message"),
        }
    except Exception as exc:
        log.error("orchestrator_vcf_trigger_error", case_id=body.case_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


# ---------------------------------------------------------------------------
# Orchestrator endpoint: deadline dates
# ---------------------------------------------------------------------------

@router.get(
    "/deadlines",
    summary="[Orchestrator] Get enrollment deadline dates for a case",
    description=(
        "Called by vcf-enrollment.yaml Cloud Workflow to get deadline dates "
        "for scheduling Cloud Tasks reminder callbacks. "
        "Returns both wtc_deadline and vcf_submission_deadline for backward compatibility."
    ),
)
async def get_deadlines(
    case_id: str = Query(..., description="Firestore case document ID"),
):
    """
    Return deadline dates in the shape expected by vcf-enrollment.yaml:
      {
        "wtc_deadline": null,               # WTC has no filing deadline (open enrollment)
        "vcf_submission_deadline": "YYYY-MM-DD"  # certificationDate + 2 years
      }

    The orchestrator uses vcf_submission_deadline to schedule Cloud Tasks callbacks
    at 90 / 60 / 30 days before the deadline.
    """
    db = _get_db()
    try:
        snap = await db.collection("cases").document(case_id).get()
        if not snap.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Case {case_id} not found",
            )

        data = snap.to_dict() or {}
        enrollment = data.get("enrollment", {})

        filing_deadline: Optional[str] = enrollment.get("filingDeadline")

        log.info(
            "orchestrator_deadlines_fetched",
            case_id=case_id,
            filing_deadline=filing_deadline,
        )

        return {
            "case_id": case_id,
            # WTC Health Program has no fixed filing deadline (open enrollment program).
            # Returns null so the orchestrator skips scheduling a WTC reminder task.
            "wtc_deadline": None,
            # The VCF submission deadline: certificationDate + 2 years.
            # Null if certification has not been confirmed yet.
            "vcf_submission_deadline": filing_deadline,
        }
    except HTTPException:
        raise
    except Exception as exc:
        log.error("orchestrator_deadlines_error", case_id=case_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
