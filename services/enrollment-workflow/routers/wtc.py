"""
routers/wtc.py — WTC Health Program enrollment API endpoints.

Endpoints:
  POST /api/v1/wtc/trigger              Trigger WTC enrollment workflow
  GET  /api/v1/wtc/{case_id}            Get WTC enrollment status
  PUT  /api/v1/wtc/{case_id}/status     Update WTC enrollment status
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from config import get_settings
from middleware.auth import StaffUser, require_paralegal_or_above
from models.wtc_models import (
    TriggerWTCWorkflowRequest,
    UpdateWTCStatusRequest,
    WTCWorkflowTriggerResponse,
    WTCStatusUpdateResponse,
    WTCEnrollmentRecord,
)
from services.firestore_client import get_db
from services.pubsub_service import publish_enrollment_event
from services.wtc_workflow import trigger_wtc_workflow, update_wtc_status, get_wtc_enrollment

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/trigger",
    response_model=WTCWorkflowTriggerResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger WTC enrollment workflow for a case",
)
async def trigger_wtc(
    request: TriggerWTCWorkflowRequest,
    current_user: StaffUser = Depends(require_paralegal_or_above),
):
    """
    Trigger automated WTC Health Program enrollment sub-workflow.
    Idempotent — safe to call multiple times. Handles edge cases:
    already enrolled and deceased cases are skipped gracefully.
    """
    db = get_db()
    settings = get_settings()

    try:
        result = trigger_wtc_workflow(
            db=db,
            case_id=request.case_id,
            force=request.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.error("trigger_wtc_error caseId=%s error=%s", request.case_id, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")

    # Publish enrollment event (non-fatal)
    if result.get("triggered"):
        try:
            publish_enrollment_event(
                project_id=settings.gcp_project_id,
                topic_name=settings.pubsub_topic_enrollment,
                case_id=request.case_id,
                event_type="WTCWorkflowTriggered",
                old_status="",
                new_status="Not Enrolled",
                workflow_type="WTC",
                performed_by=current_user.uid,
            )
        except Exception as exc:
            logger.warning("pubsub_publish_failed caseId=%s: %s", request.case_id, exc)

    return WTCWorkflowTriggerResponse(
        case_id=request.case_id,
        triggered=result["triggered"],
        workflow_step=result["workflow_step"],
        task_id=result.get("task_id"),
        message=result["message"],
    )


@router.get(
    "/{case_id}",
    response_model=WTCEnrollmentRecord,
    status_code=status.HTTP_200_OK,
    summary="Get WTC enrollment status for a case",
)
async def get_wtc_status(
    case_id: str,
    current_user: StaffUser = Depends(require_paralegal_or_above),
):
    """Retrieve current WTC Health Program enrollment status and workflow step."""
    db = get_db()

    try:
        record = get_wtc_enrollment(db=db, case_id=case_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.error("get_wtc_error caseId=%s error=%s", case_id, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")

    return WTCEnrollmentRecord(case_id=case_id, **record)


@router.put(
    "/{case_id}/status",
    response_model=WTCStatusUpdateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update WTC enrollment status",
)
async def update_wtc(
    case_id: str,
    request: UpdateWTCStatusRequest,
    current_user: StaffUser = Depends(require_paralegal_or_above),
):
    """
    Update WTC enrollment status.
    Enforces valid state transitions. Creates next paralegal task automatically.
    Writes timeline event and publishes Pub/Sub notification.
    """
    db = get_db()
    settings = get_settings()

    # Override performed_by with authenticated user
    request = request.model_copy(update={"performed_by": current_user.uid})

    try:
        result = update_wtc_status(db=db, case_id=case_id, request=request)
    except ValueError as exc:
        error_msg = str(exc)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
    except Exception as exc:
        logger.error("update_wtc_error caseId=%s error=%s", case_id, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")

    # Publish event (non-fatal)
    try:
        publish_enrollment_event(
            project_id=settings.gcp_project_id,
            topic_name=settings.pubsub_topic_enrollment,
            case_id=case_id,
            event_type="WTCStatusChanged",
            old_status=result["old_status"],
            new_status=result["new_status"],
            workflow_type="WTC",
            performed_by=current_user.uid,
        )
    except Exception as exc:
        logger.warning("pubsub_publish_failed caseId=%s: %s", case_id, exc)

    return WTCStatusUpdateResponse(
        case_id=case_id,
        old_status=result["old_status"],
        new_status=result["new_status"],
        timeline_event_id=result["timeline_event_id"],
        next_task_id=result.get("next_task_id"),
        message=f"WTC status updated: {result['old_status']} → {result['new_status']}",
    )
