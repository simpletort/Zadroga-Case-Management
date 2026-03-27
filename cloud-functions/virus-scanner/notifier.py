"""
Pub/Sub notifier — publishes a virus-detected event.

Downstream consumers (e.g. a notification service) subscribe to the
'virus-detected' topic and route alerts to staff via email / Slack.

Message schema (JSON):
{
  "fileId":       "uuid-...",
  "caseId":       "ZAD-2024-01-0001" | null,
  "fileName":     "records.pdf",
  "category":     "medical_records",
  "uploadedBy":   "staff@simpletort.com",
  "stagingPath":  "staging/{fileId}/records.pdf",
  "quarantinePath": "quarantine/...",
  "threat":       "Eicar-Signature",
  "detectedAt":   "2024-01-15T12:34:56Z"
}
"""

import json
import logging
import os
from datetime import datetime, timezone

from google.cloud import pubsub_v1

logger = logging.getLogger(__name__)

_publisher: pubsub_v1.PublisherClient | None = None


def _get_publisher() -> pubsub_v1.PublisherClient:
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def publish_virus_detected(
    project_id: str,
    topic_name: str,
    file_id: str,
    case_id: str | None,
    file_name: str,
    category: str,
    uploaded_by: str,
    staging_path: str,
    quarantine_path: str,
    threat: str,
) -> None:
    """
    Publish a virus-detected notification to the configured Pub/Sub topic.
    Errors are logged but never re-raised — a failed notification must not
    cause the overall scan workflow to fail.
    """
    topic_path = _get_publisher().topic_path(project_id, topic_name)

    payload = {
        "fileId": file_id,
        "caseId": case_id,
        "fileName": file_name,
        "category": category,
        "uploadedBy": uploaded_by,
        "stagingPath": staging_path,
        "quarantinePath": quarantine_path,
        "threat": threat,
        "detectedAt": datetime.now(tz=timezone.utc).isoformat(),
    }

    try:
        future = _get_publisher().publish(
            topic_path,
            data=json.dumps(payload).encode("utf-8"),
        )
        message_id = future.result(timeout=10)
        logger.info(
            "virus-detected published: messageId=%s fileId=%s threat=%s",
            message_id, file_id, threat,
        )
    except Exception as exc:
        logger.error(
            "Failed to publish virus-detected for fileId=%s: %s",
            file_id, exc,
        )
