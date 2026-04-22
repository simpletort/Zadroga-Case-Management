"""
pubsub_service.py — Pub/Sub event publishing for the Enrollment Workflow Service.

Events published (no PII in payload — only caseId + status metadata):
  enrollment-status-changes: WTC or VCF status transitions
  notification-requests:     Trigger downstream notification service
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from google.cloud import pubsub_v1

logger = logging.getLogger(__name__)

_publisher: pubsub_v1.PublisherClient | None = None


def _get_publisher() -> pubsub_v1.PublisherClient:
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def publish_enrollment_event(
    project_id: str,
    topic_name: str,
    case_id: str,
    event_type: str,
    old_status: str,
    new_status: str,
    workflow_type: str,          # "WTC" | "VCF"
    performed_by: str = "system",
    extra: dict | None = None,
) -> str | None:
    """
    Publish a WTC or VCF status-change event to Pub/Sub.
    Returns message ID on success, None on failure (non-fatal).
    """
    publisher = _get_publisher()
    topic_path = publisher.topic_path(project_id, topic_name)

    payload = {
        "caseId": case_id,
        "eventType": event_type,
        "workflowType": workflow_type,
        "oldStatus": old_status,
        "newStatus": new_status,
        "performedBy": performed_by,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)

    try:
        future = publisher.publish(
            topic_path,
            data=json.dumps(payload).encode("utf-8"),
            event_type=event_type,
            workflow_type=workflow_type,
        )
        message_id = future.result(timeout=10)
        logger.info(
            "pubsub_event_published caseId=%s event=%s topic=%s msgId=%s",
            case_id, event_type, topic_name, message_id,
        )
        return message_id
    except Exception as exc:
        logger.warning(
            "pubsub_publish_failed caseId=%s event=%s error=%s",
            case_id, event_type, exc,
        )
        return None


def publish_notification_request(
    project_id: str,
    topic_name: str,
    case_id: str,
    notification_type: str,
    recipient_ids: list[str],
    template_id: str,
    variables: dict | None = None,
) -> str | None:
    """
    Publish a notification request for downstream notification service.
    Returns message ID on success, None on failure (non-fatal).
    """
    publisher = _get_publisher()
    topic_path = publisher.topic_path(project_id, topic_name)

    payload = {
        "caseId": case_id,
        "notificationType": notification_type,
        "recipientIds": recipient_ids,
        "templateId": template_id,
        "variables": variables or {},
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }

    try:
        future = publisher.publish(
            topic_path,
            data=json.dumps(payload).encode("utf-8"),
            notification_type=notification_type,
        )
        message_id = future.result(timeout=10)
        logger.info(
            "notification_request_published caseId=%s type=%s msgId=%s",
            case_id, notification_type, message_id,
        )
        return message_id
    except Exception as exc:
        logger.warning(
            "notification_publish_failed caseId=%s type=%s error=%s",
            case_id, notification_type, exc,
        )
        return None
