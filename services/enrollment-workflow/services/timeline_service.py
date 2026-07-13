"""
timeline_service.py — Append-only timeline event writer for case audit trail.

Every WTC/VCF status change, task creation, and deadline event is written
to cases/{caseId}/timeline as an immutable entry.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore

logger = logging.getLogger(__name__)


def write_timeline_event(
    db,
    case_id: str,
    event_type: str,
    description: str,
    performed_by: str = "system",
    metadata: dict[str, Any] | None = None,
) -> str:
    """
    Append an event to cases/{caseId}/timeline.
    Returns the new timeline document ID.
    """
    timeline_ref = (
        db.collection("cases")
        .document(case_id)
        .collection("timeline")
        .document()
    )
    doc_id = timeline_ref.id

    timeline_ref.set({
        "eventId": doc_id,
        "caseId": case_id,
        "timestamp": firestore.SERVER_TIMESTAMP,
        "eventType": event_type,
        "description": description,
        "performedBy": performed_by,
        "metadata": metadata or {},
    })

    logger.info(
        "timeline_event_written caseId=%s eventType=%s eventId=%s",
        case_id, event_type, doc_id,
    )
    return doc_id


def write_status_transition_event(
    db,
    case_id: str,
    workflow_type: str,
    old_status: str,
    new_status: str,
    performed_by: str = "system",
    extra_meta: dict[str, Any] | None = None,
) -> str:
    """Convenience wrapper for status-transition timeline events."""
    meta = {
        "workflowType": workflow_type,
        "oldStatus": old_status,
        "newStatus": new_status,
        **(extra_meta or {}),
    }
    return write_timeline_event(
        db=db,
        case_id=case_id,
        event_type=f"{workflow_type}StatusChange",
        description=f"{workflow_type} status changed: {old_status} → {new_status}",
        performed_by=performed_by,
        metadata=meta,
    )


def write_task_created_event(
    db,
    case_id: str,
    task_id: str,
    task_title: str,
    assigned_to: str | None,
    workflow_type: str,
    step: str,
) -> str:
    """Write a timeline event when a paralegal task is auto-created."""
    return write_timeline_event(
        db=db,
        case_id=case_id,
        event_type="TaskCreated",
        description=f"Paralegal task created: {task_title}",
        performed_by="system",
        metadata={
            "taskId": task_id,
            "taskTitle": task_title,
            "assignedTo": assigned_to,
            "workflowType": workflow_type,
            "step": step,
        },
    )


def write_deadline_event(
    db,
    case_id: str,
    deadline_date: str,
    days_remaining: int,
    event_subtype: str = "DeadlineCalculated",
) -> str:
    """Write a timeline event for VCF deadline calculation or alert."""
    return write_timeline_event(
        db=db,
        case_id=case_id,
        event_type=event_subtype,
        description=f"VCF filing deadline: {deadline_date} ({days_remaining} days remaining)",
        performed_by="system",
        metadata={
            "vcfFilingDeadline": deadline_date,
            "daysRemaining": days_remaining,
        },
    )