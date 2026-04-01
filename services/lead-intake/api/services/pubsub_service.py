"""
api/services/pubsub_service.py — Publish Pub/Sub events.

Events published by lead-intake:
  lead-created  (topic: pubsub_lead_created_topic)
    → audit trail / future subscribers
    → NOTE: VCF screening is now INLINE (no longer triggered by this event)

  lead-screened (topic: pubsub_lead_screened_topic)
    → consumed by the Notification Dispatcher service to send staff alerts
    → eligibility + score + flags included so dispatcher can act immediately

Blocking future.result() runs in a thread executor to avoid blocking the uvicorn event loop.
"""
from __future__ import annotations

import asyncio
import json

from google.cloud import pubsub_v1

from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)
_publisher: pubsub_v1.PublisherClient | None = None


def _get_publisher() -> pubsub_v1.PublisherClient:
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


async def publish_lead_created(
    case_id:          str,
    partner_id:       str,
    request_id:       str,
    marketing_source: str,
) -> None:
    """
    Publish a lead-created event to Pub/Sub.
    Kept for audit trail purposes. VCF screening no longer triggers from this event.
    """
    settings   = get_settings()
    publisher  = _get_publisher()
    topic_path = publisher.topic_path(settings.gcp_project_id, settings.pubsub_lead_created_topic)

    payload = json.dumps({
        "eventType":       "lead-created",
        "caseId":          case_id,
        "partnerId":       partner_id,
        "requestId":       request_id,
        "marketingSource": marketing_source,
    }).encode("utf-8")

    loop   = asyncio.get_event_loop()
    future = publisher.publish(topic_path, data=payload, caseId=case_id)
    await loop.run_in_executor(None, lambda: future.result(timeout=10))
    logger.info("pubsub_lead_created_published", case_id=case_id)


async def publish_lead_screened(
    case_id:     str,
    eligibility: str,
    score:       int,
    flags:       list[str],
    new_status:  str,
    request_id:  str,
) -> None:
    """
    Publish a lead-screened event to Pub/Sub.
    This is the primary trigger for the Notification Dispatcher service.

    The Notification Dispatcher subscribes to this topic and:
      ELIGIBLE     → notify assigned paralegal
      INELIGIBLE   → notify admin staff
      NEEDS_REVIEW → create review task, notify paralegal with flag summary
    """
    settings   = get_settings()
    publisher  = _get_publisher()
    topic_path = publisher.topic_path(settings.gcp_project_id, settings.pubsub_lead_screened_topic)

    payload = json.dumps({
        "eventType":   "lead-screened",
        "caseId":      case_id,
        "eligibility": eligibility,
        "score":       score,
        "flags":       flags,
        "newStatus":   new_status,
        "requestId":   request_id,
    }).encode("utf-8")

    loop   = asyncio.get_event_loop()
    future = publisher.publish(
        topic_path,
        data=payload,
        caseId=case_id,
        eligibility=eligibility,
    )
    await loop.run_in_executor(None, lambda: future.result(timeout=10))
    logger.info("pubsub_lead_screened_published", case_id=case_id, eligibility=eligibility)
