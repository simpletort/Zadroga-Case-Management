"""
Enrollment API Router — generic certification and registration endpoints.

Prefix: /api/v1/enrollment

These are the human-facing / frontend-facing endpoints used by the paralegal
dashboard and case management UI. They use program-agnostic terminology
(certification / registration) rather than program-specific names (WTC / VCF).

Endpoints:
  Certification (formerly WTC):
    POST   /certification/trigger          — start certification workflow
    GET    /certification/{case_id}        — get current certification status
    PUT    /certification/{case_id}/status — advance certification state machine

  Registration (formerly VCF):
    POST   /registration/initiate          — start registration workflow
    GET    /registration/{case_id}         — get current registration status
    PUT    /registration/{case_id}/status  — advance registration state machine
    GET    /registration/{case_id}/prefill — get pre-filled registration form data
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from services.firestore_client import get_db as _get_db
from config import settings

from middleware.auth import require_paralegal_or_above
from models.certification_models import (
    CertificationEnrollmentRecord,
    CertificationStatusUpdateResponse,
    CertificationWorkflowTriggerResponse,
    TriggerCertificationWorkflowRequest,
    UpdateCertificationStatusRequest,
)
from models.registration_models import (
    InitiateRegistrationRequest,
    RegistrationFormPrefillData,
    RegistrationRecord,
    UpdateRegistrationStatusRequest,
)
from services.certification_workflow import (
    get_certification_enrollment,
    trigger_certification_workflow,
    update_certification_status,
)
from services.registration_workflow import (
    get_registration,
    get_registration_prefill,
    initiate_registration,
    update_registration_status,
)

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/enrollment", tags=["Enrollment"])


# def _get_db():
#     return firestore.AsyncClient(project=settings.gcp_project_id, database=settings.firestore_database_id)


# ===========================================================================
# Certification endpoints
# ===========================================================================

@router.post(
    "/certification/trigger",
    response_model=CertificationWorkflowTriggerResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger certification enrollment workflow",
    description=(
        "Idempotently start the certification enrollment workflow for a case. "
        "Re-triggering an already-enrolled case returns the existing state."
    ),
)
async def trigger_certification(
    body: TriggerCertificationWorkflowRequest,
    _user=Depends(require_paralegal_or_above),
    db=Depends(_get_db),
):
    try:
        return await trigger_certification_workflow(
            db=db,
            case_id=body.case_id,
            program=body.program,
            triggered_by=body.triggered_by,
            notes=body.notes,
        )
    except Exception as exc:
        log.error("trigger_certification_failed", case_id=body.case_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.get(
    "/certification/{case_id}",
    response_model=CertificationEnrollmentRecord,
    summary="Get certification enrollment status",
)
async def get_certification(
    case_id: str,
    _user=Depends(require_paralegal_or_above),
    db=Depends(_get_db),
):
    record = await get_certification_enrollment(db=db, case_id=case_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No certification record found for case {case_id}",
        )
    return record


@router.put(
    "/certification/{case_id}/status",
    response_model=CertificationStatusUpdateResponse,
    summary="Update certification enrollment status",
    description=(
        "Advance the certification status along the state machine. "
        "Returns HTTP 422 for invalid transitions."
    ),
)
async def update_certification(
    case_id: str,
    body: UpdateCertificationStatusRequest,
    _user=Depends(require_paralegal_or_above),
    db=Depends(_get_db),
):
    try:
        return await update_certification_status(
            db=db,
            case_id=case_id,
            new_status=body.new_status,
            updated_by=body.updated_by,
            certification_date=body.certification_date,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except Exception as exc:
        log.error("update_certification_failed", case_id=case_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


# ===========================================================================
# Registration endpoints
# ===========================================================================

@router.post(
    "/registration/initiate",
    status_code=status.HTTP_200_OK,
    summary="Initiate registration workflow",
    description=(
        "Start the registration workflow for a case that has completed certification. "
        "Idempotent: re-initiating an already-registered case returns the existing record."
    ),
)
async def initiate_registration_endpoint(
    body: InitiateRegistrationRequest,
    _user=Depends(require_paralegal_or_above),
    db=Depends(_get_db),
):
    # Validate prerequisite: must have certification completed
    cert = await get_certification_enrollment(db=db, case_id=body.case_id)
    if not cert:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Certification workflow must be triggered before initiating registration.",
        )

    try:
        return await initiate_registration(
            db=db,
            case_id=body.case_id,
            program=body.program,
            initiated_by=body.initiated_by,
            notes=body.notes,
        )
    except Exception as exc:
        log.error("initiate_registration_failed", case_id=body.case_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.get(
    "/registration/{case_id}",
    response_model=RegistrationRecord,
    summary="Get registration status",
)
async def get_registration_endpoint(
    case_id: str,
    _user=Depends(require_paralegal_or_above),
    db=Depends(_get_db),
):
    record = await get_registration(db=db, case_id=case_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No registration record found for case {case_id}",
        )
    return record


@router.put(
    "/registration/{case_id}/status",
    summary="Update registration status",
    description=(
        "Advance the registration status along the state machine. "
        "registration_number is required when transitioning to REGISTERED."
    ),
)
async def update_registration_endpoint(
    case_id: str,
    body: UpdateRegistrationStatusRequest,
    _user=Depends(require_paralegal_or_above),
    db=Depends(_get_db),
):
    try:
        return await update_registration_status(
            db=db,
            case_id=case_id,
            new_status=body.new_status,
            updated_by=body.updated_by,
            registration_number=body.registration_number,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except Exception as exc:
        log.error("update_registration_failed", case_id=case_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.get(
    "/registration/{case_id}/prefill",
    response_model=RegistrationFormPrefillData,
    summary="Get pre-filled registration form data",
    description=(
        "Returns client and case data pre-populated for the registration portal "
        "or DocuSign template. Never logged."
    ),
)
async def get_prefill(
    case_id: str,
    _user=Depends(require_paralegal_or_above),
    db=Depends(_get_db),
):
    data = await get_registration_prefill(db=db, case_id=case_id)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case {case_id} not found",
        )
    return data
