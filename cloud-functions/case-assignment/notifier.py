"""
Pub/Sub notifier — publishes a case-assignment event.

Downstream consumers (the Notification Service) subscribe to the
'assignment-notifications' topic and send an email/SMS to the assigned paralegal.

Message schema (JSON):
{
  "caseId":       "ZAD-2024-01-0001",
  "paralegalId":  "uid-...",
  "assignedAt":   "2024-01-15T12:34:56Z"
}
"""

import json
import logging
from datetime import datetime

from google.cloud import pubsub_v1

logger = logging.getLogger(__name__)

_publisher: pubsub_v1.PublisherClient | None = None


def _get_publisher() -> pubsub_v1.PublisherClient:
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def publish_assignment_notification(
    project_id: str,
    topic_name: str,
    case_id: str,
    paralegal_id: str,
    assigned_at: datetime,
) -> None:
    """
    Publish a case-assignment notification to the configured Pub/Sub topic.
    Errors are logged but never re-raised — a failed notification must not
    cause the overall assignment workflow to fail.
    """
    topic_path = _get_publisher().topic_path(project_id, topic_name)

    payload = {
        "caseId":      case_id,
        "paralegalId": paralegal_id,
        "assignedAt":  assigned_at.isoformat(),
    }

    try:
        future = _get_publisher().publish(
            topic_path,
            data=json.dumps(payload).encode("utf-8"),
        )
        message_id = future.result(timeout=10)
        logger.info(
            "assignment-notification published: messageId=%s caseId=%s paralegalId=%s",
            message_id, case_id, paralegal_id,
        )
    except Exception as exc:
        logger.error(
            "Failed to publish assignment notification for caseId=%s: %s",
            case_id, exc,
        )
