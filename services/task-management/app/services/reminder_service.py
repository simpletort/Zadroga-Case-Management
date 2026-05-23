"""
ReminderService — schedules a Cloud Tasks HTTP callback 24h before a task's dueAt.

The callback hits POST /internal/reminders on this service, which transitions
the task to "overdue" if it hasn't been completed or skipped by then.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2

from app.config import get_settings
from app.models.task import TaskResponse

logger = logging.getLogger(__name__)


def schedule_reminder(task: TaskResponse) -> str | None:
    """
    Schedules a Cloud Tasks HTTP POST to /internal/reminders at
    (task.dueAt - settings.reminder_advance_hours).

    Returns the Cloud Tasks task name, or None if skipped (no dueAt, or fire
    time is already in the past).
    """
    settings = get_settings()

    if not task.dueAt:
        return None

    if not settings.task_service_url or not settings.service_account_email:
        logger.warning(
            "reminder_skipped task_id=%s — TASK_SERVICE_URL or SERVICE_ACCOUNT_EMAIL not set",
            task.taskId,
        )
        return None

    due_at_aware = task.dueAt
    if due_at_aware.tzinfo is None:
        due_at_aware = due_at_aware.replace(tzinfo=timezone.utc)

    fire_at = due_at_aware - timedelta(hours=settings.reminder_advance_hours)
    now_utc = datetime.now(tz=timezone.utc)

    if fire_at <= now_utc:
        logger.warning(
            "reminder_in_the_past task_id=%s fire_at=%s — skipping",
            task.taskId,
            fire_at.isoformat(),
        )
        return None

    client = tasks_v2.CloudTasksClient()
    queue_path = client.queue_path(
        settings.gcp_project_id,
        settings.cloud_tasks_location,
        settings.cloud_tasks_queue,
    )

    payload = {
        "taskId": task.taskId,
        "caseId": task.caseId,
        "dueAt": due_at_aware.isoformat(),
    }

    ts = timestamp_pb2.Timestamp()
    ts.FromDatetime(fire_at)

    http_request = tasks_v2.HttpRequest(
        http_method=tasks_v2.HttpMethod.POST,
        url=f"{settings.task_service_url}/internal/reminders",
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload).encode(),
        oidc_token=tasks_v2.OidcToken(
            service_account_email=settings.service_account_email,
            audience=settings.task_service_url,
        ),
    )

    cloud_task = tasks_v2.Task(
        http_request=http_request,
        schedule_time=ts,
    )

    created = client.create_task(parent=queue_path, task=cloud_task)
    logger.info(
        "reminder_scheduled task_id=%s fire_at=%s cloud_task=%s",
        task.taskId,
        fire_at.isoformat(),
        created.name,
    )
    return created.name
