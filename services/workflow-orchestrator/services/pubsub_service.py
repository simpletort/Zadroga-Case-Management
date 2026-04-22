"""
PubSubService — publishes domain events from the Workflow Orchestrator.

Events published:
  topic: case-events
    - workflow.triggered
    - workflow.completed
    - workflow.failed
    - task.created
    - task.completed
    - task.overdue

  topic: deadline-alerts
    - deadline.approaching  (fired by Cloud Tasks callbacks → this service)
"""

from __future__ import annotations

import json
import structlog
from datetime import datetime
from typing import Any

from google.cloud import pubsub_v1

from config import settings

log = structlog.get_logger()


class PubSubService:
    def __init__(self):
        self._publisher = pubsub_v1.PublisherClient()
        self._case_events_topic = self._publisher.topic_path(
            settings.gcp_project_id,
            settings.pubsub_case_events_topic,
        )
        self._deadline_topic = self._publisher.topic_path(
            settings.gcp_project_id,
            settings.pubsub_deadline_alerts_topic,
        )

    def _publish(self, topic: str, event_type: str, data: dict[str, Any]) -> None:
        payload = {
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "source": "workflow-orchestrator",
            "data": data,
        }
        try:
            future = self._publisher.publish(
                topic,
                data=json.dumps(payload).encode("utf-8"),
                event_type=event_type,
            )
            future.result()  # block briefly to catch publish errors
            log.debug("pubsub_event_published", event_type=event_type, topic=topic)
        except Exception as exc:
            log.error("pubsub_publish_failed", event_type=event_type,
                      topic=topic, error=str(exc))

    # ------------------------------------------------------------------
    # Workflow events
    # ------------------------------------------------------------------

    def publish_workflow_triggered(self, case_id: str, workflow_type: str,
                                   execution_id: str) -> None:
        self._publish(self._case_events_topic, "workflow.triggered", {
            "case_id": case_id,
            "workflow_type": workflow_type,
            "execution_id": execution_id,
        })

    def publish_workflow_completed(self, case_id: str, workflow_type: str,
                                   execution_id: str, result: dict) -> None:
        self._publish(self._case_events_topic, "workflow.completed", {
            "case_id": case_id,
            "workflow_type": workflow_type,
            "execution_id": execution_id,
            "result": result,
        })

    def publish_workflow_failed(self, case_id: str, workflow_type: str,
                                execution_id: str, error: str) -> None:
        self._publish(self._case_events_topic, "workflow.failed", {
            "case_id": case_id,
            "workflow_type": workflow_type,
            "execution_id": execution_id,
            "error": error,
        })

    # ------------------------------------------------------------------
    # Task events
    # ------------------------------------------------------------------

    def publish_task_created(self, case_id: str, task_id: str,
                             task_type: str, assigned_to_role: str | None) -> None:
        self._publish(self._case_events_topic, "task.created", {
            "case_id": case_id,
            "task_id": task_id,
            "task_type": task_type,
            "assigned_to_role": assigned_to_role,
        })

    def publish_task_completed(self, case_id: str, task_id: str,
                               task_type: str, completed_by: str) -> None:
        self._publish(self._case_events_topic, "task.completed", {
            "case_id": case_id,
            "task_id": task_id,
            "task_type": task_type,
            "completed_by": completed_by,
        })

    def publish_task_overdue(self, case_id: str, task_id: str,
                             task_type: str, due_date: str) -> None:
        self._publish(self._case_events_topic, "task.overdue", {
            "case_id": case_id,
            "task_id": task_id,
            "task_type": task_type,
            "due_date": due_date,
        })

    # ------------------------------------------------------------------
    # Deadline alerts
    # ------------------------------------------------------------------

    def publish_deadline_approaching(self, case_id: str, deadline_type: str,
                                     deadline: str, days_remaining: int) -> None:
        self._publish(self._deadline_topic, "deadline.approaching", {
            "case_id": case_id,
            "deadline_type": deadline_type,
            "deadline": deadline,
            "days_remaining": days_remaining,
        })
