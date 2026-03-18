"""
api/services/pubsub_service.py — Publish Pub/Sub events.
"""
from __future__ import annotations
import json
from google.cloud import pubsub_v1
from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)
_publisher = None


def _get_publisher() -> pubsub_v1.PublisherClient:
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


async def publish_lead_created(
    case_id: str,
    partner_id: str,
    request_id: str,
    marketing_source: str,
) -> None:
    settings = get_settings()
    publisher = _get_publisher()
    topic_path = publisher.topic_path(settings.gcp_project_id, settings.pubsub_lead_created_topic)
    payload = json.dumps({
        "eventType": "lead-created",
        "caseId": case_id,
        "partnerId": partner_id,
        "requestId": request_id,
        "marketingSource": marketing_source,
    }).encode("utf-8")
    future = publisher.publish(topic_path, data=payload, caseId=case_id)
    future.result(timeout=10)
    logger.info("pubsub_lead_created_published", case_id=case_id)
