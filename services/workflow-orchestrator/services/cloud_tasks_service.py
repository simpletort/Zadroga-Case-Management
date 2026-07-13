"""
CloudTasksService — schedules deadline reminder tasks via GCP Cloud Tasks.

When a Task has a due_date, we schedule a Cloud Tasks HTTP request
back to this service's /internal/reminders endpoint 24 hours before.
This triggers a Pub/Sub notification to alert the assignee.
"""

from __future__ import annotations

import json
import structlog
from datetime import datetime, timedelta, timezone
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2

from config import settings
from models import Task

log = structlog.get_logger()


class CloudTasksService:
    def __init__(self):
        self._client = tasks_v2.CloudTasksAsyncClient()
        # queue_path returns the fully-qualified resource name: projects/{p}/locations/{r}/queues/{q}
        # Used for all task creation and management calls to this queue.
        self._queue_path = self._client.queue_path(
            settings.gcp_project_id,
            settings.gcp_region,
            settings.cloud_tasks_queue,
        )

    async def schedule_deadline_reminder(
        self,
        task: Task,
        advance_hours: int = 24,
    ) -> str | None:
        """
        Schedules an HTTP task that fires `advance_hours` before task.due_date.
        Returns the Cloud Tasks task name, or None if scheduling was skipped.
        """
        if not task.due_date:
            return None

        fire_at = task.due_date - timedelta(hours=advance_hours)
        now_utc = datetime.now(tz=timezone.utc)

        # Ensure due_date is tz-aware for comparison (handle both aware and naive datetimes)
        due_date_aware = task.due_date
        if due_date_aware.tzinfo is None:
            due_date_aware = due_date_aware.replace(tzinfo=timezone.utc)
        fire_at_aware = fire_at
        if fire_at_aware.tzinfo is None:
            fire_at_aware = fire_at_aware.replace(tzinfo=timezone.utc)

        # Skip scheduling if reminder would fire in the past (deadline has already passed).
        # Cloud Tasks would try to run it immediately, which is useless for a stale task.
        if fire_at_aware <= now_utc:
            log.warning("deadline_reminder_in_the_past",
                        task_id=task.id, fire_at=fire_at_aware.isoformat())
            return None

        payload = {
            "task_id": task.id,
            "case_id": task.case_id,
            "task_type": task.task_type,
            "due_date": due_date_aware.isoformat(),
            "assigned_to": task.assigned_to,
            "assigned_to_role": task.assigned_to_role,
        }

        # timestamp_pb2.Timestamp: protobuf Timestamp type (used by Cloud Tasks API).
        # Convert Python datetime to proto format for schedule_time.
        ts = timestamp_pb2.Timestamp()
        ts.FromDatetime(fire_at_aware)

        # OIDC token: required because Cloud Run rejects unauthenticated requests.
        # Token proves this service account is authorized to call /internal/reminders.
        http_request = tasks_v2.HttpRequest(
            http_method=tasks_v2.HttpMethod.POST,
            url=f"{settings.cloud_tasks_service_url}/internal/reminders",
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload).encode(),
            oidc_token=tasks_v2.OidcToken(
                service_account_email=settings.service_account_email,
                audience=settings.cloud_tasks_service_url,
            ),
        )

        cloud_task = tasks_v2.Task(
            http_request=http_request,
            schedule_time=ts,
        )

        created = await self._client.create_task(
            parent=self._queue_path,
            task=cloud_task,
        )
        log.info("deadline_reminder_scheduled",
                 task_id=task.id, fire_at=fire_at_aware.isoformat(),
                 cloud_task_name=created.name)
        return created.name

    async def schedule_enrollment_deadline_check(
        self,
        case_id: str,
        deadline: datetime,
        deadline_type: str,  # "wtc" | "vcf"
        advance_days: list[int] | None = None,
    ) -> list[str]:
        """
        Schedules multiple reminders at 90, 60, 30, 14, and 7 days
        before a VCF/WTC enrollment deadline.
        """
        if advance_days is None:
            # Multiple checkpoints allow for escalating notifications and plan adjustments.
            # 90/60 days: early planning; 30/14 days: urgent focus; 7 days: final push.
            advance_days = [90, 60, 30, 14, 7]

        names: list[str] = []
        now_utc = datetime.now(tz=timezone.utc)

        deadline_aware = deadline
        if deadline_aware.tzinfo is None:
            deadline_aware = deadline_aware.replace(tzinfo=timezone.utc)

        for days in advance_days:
            fire_at = deadline_aware - timedelta(days=days)
            # Skip past-due checkpoints: if 90-day mark has already passed, don't create task for it.
            # Avoids cluttering the queue with junk tasks for milestones the deadline has already crossed.
            if fire_at <= now_utc:
                continue

            payload = {
                "case_id": case_id,
                "deadline_type": deadline_type,
                "deadline": deadline_aware.isoformat(),
                "days_remaining": days,
            }

            ts = timestamp_pb2.Timestamp()
            ts.FromDatetime(fire_at)

            http_request = tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=f"{settings.cloud_tasks_service_url}/internal/deadline-alerts",
                headers={"Content-Type": "application/json"},
                body=json.dumps(payload).encode(),
                oidc_token=tasks_v2.OidcToken(
                    service_account_email=settings.service_account_email,
                    audience=settings.cloud_tasks_service_url,
                ),
            )

            cloud_task = tasks_v2.Task(
                http_request=http_request,
                schedule_time=ts,
            )

            created = await self._client.create_task(
                parent=self._queue_path,
                task=cloud_task,
            )
            names.append(created.name)
            log.info("enrollment_deadline_reminder_scheduled",
                     case_id=case_id, deadline_type=deadline_type,
                     days_remaining=days, fire_at=fire_at.isoformat())

        return names
