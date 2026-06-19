"""
routers/vcf.py — VCF registration workflow API endpoints.

Endpoints:
  POST /api/v1/vcf/register             Initiate VCF registration workflow
  GET  /api/v1/vcf/{case_id}            Get VCF registration status
  PUT  /api/v1/vcf/{case_id}/status     Update VCF registration status
  GET  /api/v1/vcf/{case_id}/prefill    Get pre-filled VCF form data
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status

from config import get_settings
from models.vcf_models import (
    InitiateVCFRegistrationRequest,
    UpdateVCFStatusRequest,
    VCFRegistrationRecord,
    VCFRegistrationInitiateResponse,
    VCFStatusUpdateResponse,
    VCFFormPrefillData,
)
from services.firestore_client import get_db
from services.pubsub_service import publish_enrollment_event
from services.vcf_workflow import (
    initiate_vcf_registration,
    update_vcf_status,
    get_vcf_registration,
    get_vcf_prefill_data,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/register",
    response_model=VCFRegistrationInitiateResponse,
    status_code=status.HTTP_200_OK,
    summary="Initiate VCF registration workflow for a case",
)
async def register_vcf(
    request: InitiateVCFRegistrationRequest,
    http_request: Request,
):
    """
    Initiate VCF registration workflow.
    Creates eligibility review task for paralegal.
    Idempotent — safe to call on already-registered cases.
    """
    db = get_db()
    settings = get_settings()

    try:
        result = initiate_vcf_registration(db=db, case_id=request.case_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.error("vcf_register_error caseId=%s error=%s", request.case_id, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")

    if result.get("initiated"):
        try:
            publish_enrollment_event(
                project_id=settings.gcp_project_id,
                topic_name=settings.pubsub_topic_enrollment,
                case_id=request.case_id,
                event_type="VCFRegistrationInitiated",
                old_status="",
                new_status="Not Registered",
                workflow_type="VCF",
                performed_by=http_request.state.user.get("uid", ""),
            )
        except Exception as exc:
            logger.warning("pubsub_publish_failed caseId=%s: %s", request.case_id, exc)

    return VCFRegistrationInitiateResponse(
        case_id=request.case_id,
        initiated=result["initiated"],
        registration_step=result["registration_step"],
        task_id=result.get("task_id"),
        message=result["message"],
    )


@router.get(
    "/{case_id}",
    response_model=VCFRegistrationRecord,
    status_code=status.HTTP_200_OK,
    summary="Get VCF registration status for a case",
)
async def get_vcf_status(
    case_id: str,
):
    """Retrieve current VCF registration status, claim number, and deadline."""
    db = get_db()

    try:
        record = get_vcf_registration(db=db, case_id=case_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.error("get_vcf_error caseId=%s error=%s", case_id, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")

    return VCFRegistrationRecord(case_id=case_id, **record)


@router.put(
    "/{case_id}/status",
    response_model=VCFStatusUpdateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update VCF registration status",
)
async def update_vcf(
    case_id: str,
    request: UpdateVCFStatusRequest,
    http_request: Request,
):
    """
    Update VCF registration status.
    When status = Registered: vcf_claim_number is REQUIRED.
    Automatically calculates VCF filing deadline on registration.
    """
    db = get_db()
    settings = get_settings()

    request = request.model_copy(update={"performed_by": http_request.state.user.get("uid", "")})

    try:
        result = update_vcf_status(db=db, case_id=case_id, request=request)
    except ValueError as exc:
        error_msg = str(exc)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
    except Exception as exc:
        logger.error("update_vcf_error caseId=%s error=%s", case_id, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")

    # Publish event
    try:
        publish_enrollment_event(
            project_id=settings.gcp_project_id,
            topic_name=settings.pubsub_topic_enrollment,
            case_id=case_id,
            event_type="VCFStatusChanged",
            old_status=result["old_status"],
            new_status=result["new_status"],
            workflow_type="VCF",
            performed_by=http_request.state.user.get("uid", ""),
            extra={"vcfFilingDeadline": result.get("vcf_filing_deadline")},
        )
    except Exception as exc:
        logger.warning("pubsub_publish_failed caseId=%s: %s", case_id, exc)

    return VCFStatusUpdateResponse(
        case_id=case_id,
        old_status=result["old_status"],
        new_status=result["new_status"],
        timeline_event_id=result["timeline_event_id"],
        vcf_filing_deadline=result.get("vcf_filing_deadline"),
        next_task_id=result.get("next_task_id"),
        message=f"VCF status updated: {result['old_status']} → {result['new_status']}",
    )


@router.get(
    "/{case_id}/prefill",
    response_model=VCFFormPrefillData,
    status_code=status.HTTP_200_OK,
    summary="Get pre-filled VCF registration form data from case record",
)
async def get_vcf_prefill(
    case_id: str,
):
    """
    Generate pre-filled VCF registration form data from the case record.
    Returns only the minimum PHI needed for VCF form completion.
    """
    db = get_db()

    try:
        prefill = get_vcf_prefill_data(db=db, case_id=case_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.error("get_vcf_prefill_error caseId=%s error=%s", case_id, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")

    return prefill
