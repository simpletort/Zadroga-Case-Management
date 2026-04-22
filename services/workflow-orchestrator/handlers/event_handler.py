"""
Internal endpoints consumed by:
  - Cloud Tasks (deadline reminders)
  - Pub/Sub push subscriptions (inbound case events)

These routes are NOT publicly accessible — the Cloud Run ingress is
restricted to internal GCP traffic only for /internal/* paths.
"""

from __future__ import annotations

import base64
import json
import structlog
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from models import TaskStatus
from services.firestore_service import FirestoreService
from services.pubsub_service import PubSubService
from services.cloud_tasks_service import CloudTasksService
from services.workflow_engine import WorkflowEngine

log = structlog.get_logger()
router = APIRouter(prefix="/internal", tags=["Internal"])


# ---------------------------------------------------------------------------
# Models for inbound payloads
# ---------------------------------------------------------------------------

class ReminderPayload(BaseModel):
    task_id: str
    case_id: str
    task_type: str
    due_date: str
    assigned_to: str | None = None
    assigned_to_role: str | None = None


class DeadlineAlertPayload(BaseModel):
    case_id: str
    deadline_type: str    # "wtc" | "vcf"
    deadline: str
    days_remaining: int


class PubSubMessage(BaseModel):
    message: dict[str, Any]
    subscription: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_pubsub(message: dict) -> dict:
    # Pub/Sub push messages base64-encode the message body in the "data" field.
    # Decode and parse JSON to get the original event payload.
    """Decode a base64-encoded Pub/Sub message body."""
    raw = message.get("data", "")
    decoded = base64.b64decode(raw).decode("utf-8")
    return json.loads(decoded)


# ---------------------------------------------------------------------------
# Cloud Tasks callbacks
# ---------------------------------------------------------------------------

@router.post("/reminders", status_code=status.HTTP_200_OK)
async def handle_task_reminder(payload: ReminderPayload):
    """
    Fired by Cloud Tasks 24 hours before a task's due_date.
    Marks the task as OVERDUE if still not completed, and publishes an alert.
    """
    db = FirestoreService()
    pubsub = PubSubService()

    task = await db.get_task(case_id=payload.case_id, task_id=payload.task_id)
    if not task:
        log.warning("reminder_task_not_found", task_id=payload.task_id)
        return {"status": "skipped", "reason": "task not found"}

    if task.status == TaskStatus.COMPLETED:
        log.info("reminder_task_already_completed", task_id=payload.task_id)
        return {"status": "skipped", "reason": "already completed"}

    now_utc = datetime.now(tz=timezone.utc)
    due = datetime.fromisoformat(payload.due_date)
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)

    # At fire time, check if task is actually overdue (past due_date) vs just approaching.
    # Fire time is advance_hours before due_date; but by the time this handler runs,
    # the actual due_date may have already passed depending on queue latency.
    if now_utc >= due:
        # Past due — mark overdue and publish task.overdue event
        task.status = TaskStatus.OVERDUE
        task.updated_at = datetime.utcnow()
        await db.save_task(task)
        # Both branches call publish_task_overdue; notification service distinguishes overdue vs approaching
        # by checking days_remaining in the message. Here, negative days means it's overdue.
        pubsub.publish_task_overdue(
            case_id=payload.case_id,
            task_id=payload.task_id,
            task_type=payload.task_type,
            due_date=payload.due_date,
        )
        log.warning("task_marked_overdue", task_id=payload.task_id,
                    case_id=payload.case_id)
    else:
        # Still time — task is approaching but not yet overdue. Publish same event type.
        # Notification service reads days_remaining to decide: send "approaching" or "overdue" alert.
        pubsub.publish_task_overdue(
            case_id=payload.case_id,
            task_id=payload.task_id,
            task_type=payload.task_type,
            due_date=payload.due_date,
        )
        log.info("task_reminder_published", task_id=payload.task_id)

    task.reminder_sent_at = datetime.utcnow()
    await db.save_task(task)
    return {"status": "ok"}


@router.post("/deadline-alerts", status_code=status.HTTP_200_OK)
async def handle_deadline_alert(payload: DeadlineAlertPayload):
    """
    Fired by Cloud Tasks at 90/60/30/14/7 days before a VCF/WTC deadline.
    Publishes a deadline.approaching event and creates a reminder task.
    """
    db = FirestoreService()
    pubsub = PubSubService()

    pubsub.publish_deadline_approaching(
        case_id=payload.case_id,
        deadline_type=payload.deadline_type,
        deadline=payload.deadline,
        days_remaining=payload.days_remaining,
    )

    # Create a visible reminder task for the paralegal dashboard
    from models import Task, TaskType, TaskPriority
    from datetime import timedelta

    # days_remaining <= 14 is CRITICAL threshold: less than 2 weeks to meet deadline.
    # Before that, it's just HIGH priority for planning/awareness.
    priority = TaskPriority.CRITICAL if payload.days_remaining <= 14 else TaskPriority.HIGH
    task = Task(
        case_id=payload.case_id,
        title=(
            f"{payload.deadline_type.upper()} enrollment deadline in "
            f"{payload.days_remaining} days — {payload.deadline[:10]}"
        ),
        task_type=TaskType.DEADLINE_REMINDER,
        priority=priority,
        assigned_to_role="paralegal",
        due_date=datetime.fromisoformat(payload.deadline),
        metadata={
            "deadline_type": payload.deadline_type,
            "days_remaining": payload.days_remaining,
        },
    )
    # Create a visible Task (not just Pub/Sub event) so paralegal dashboard shows the reminder.
    # If notifications are missed, the task still appears in their queue as a fallback.
    await db.save_task(task)
    log.info("deadline_reminder_task_created", case_id=payload.case_id,
             deadline_type=payload.deadline_type,
             days_remaining=payload.days_remaining)
    return {"status": "ok", "task_id": task.id}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_arguments(mapping: dict[str, str], context: dict) -> dict:
    """
    Resolve dot-notation paths in an arguments_mapping against an event context dict.

    Example:
        mapping  = {"case_id": "data.case_id", "client_email": "data.client_email"}
        context  = {"data": {"case_id": "abc", "client_email": "x@y.com"}}
        returns  = {"case_id": "abc", "client_email": "x@y.com"}
    """
    resolved: dict = {}
    for key, path in mapping.items():
        parts = path.split(".")
        value: Any = context
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
                break
        resolved[key] = value
    return resolved


# ---------------------------------------------------------------------------
# Pub/Sub push subscription handler
# ---------------------------------------------------------------------------

@router.post("/pubsub/case-events", status_code=status.HTTP_200_OK)
async def handle_case_event(request: Request):
    """
    Receives push-delivered Pub/Sub messages from the case-events topic.
    Reacts to events from other microservices that should advance
    or trigger workflows.
    """
    body = await request.json()
    try:
        event = _decode_pubsub(body.get("message", {}))
    except Exception as exc:
        log.error("pubsub_decode_error", error=str(exc))
        # Return 200 so Pub/Sub does not keep redelivering a malformed message.
        # If we return non-200, Pub/Sub retries forever, causing an infinite loop.
        return {"status": "ignored"}

    event_type = event.get("event_type")
    data: dict = event.get("data", {})

    log.info("case_event_received", event_type=event_type, data=data)

    engine = WorkflowEngine()
    db = FirestoreService()

    # Dynamically look up which workflows are triggered by this event type.
    # Event-to-workflow mappings are stored in workflow_definitions/{id}.event_triggers
    # and can be edited by non-technical users via the admin API.
    definitions = await db.list_workflow_definitions(active_only=True)
    triggered_count = 0

    for defn in definitions:
        for trigger in defn.event_triggers:
            if trigger.event_type != event_type:
                continue
            arguments = _resolve_arguments(trigger.arguments_mapping, {"data": data})
            case_id = arguments.get("case_id") or data.get("case_id", "")
            try:
                await engine.trigger(
                    case_id=case_id,
                    workflow_type=defn.id,
                    triggered_by="system",
                    arguments=arguments,
                )
                triggered_count += 1
                log.info(
                    "event_triggered_workflow",
                    event_type=event_type,
                    workflow_id=defn.id,
                    case_id=case_id,
                )
            except Exception as exc:
                log.error(
                    "event_trigger_failed",
                    event_type=event_type,
                    workflow_id=defn.id,
                    error=str(exc),
                )

    return {"status": "ok", "event_type": event_type, "triggered": triggered_count}
