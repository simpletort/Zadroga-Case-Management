"""
api/services/pubsub_service.py — Publish Pub/Sub events.

lead-intake publishes three event types. The notification service subscribes
to two of them via Pub/Sub push subscriptions and handles all SMS from there.
lead-intake does NOT call the notification service directly.

Events:
  lead-created  → notification service /pubsub/lead-created → welcome_sms
  lead-screened → audit trail + staff Firestore notification (no SMS)
  lead-followup → notification service /pubsub/lead-followup → followup_sms

Payload schemas are the source of truth — the notification service reads
these exact fields. Do not rename fields without updating both sides.
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


async def _publish(topic_path: str, payload: dict, **attributes: str) -> None:
    """Publish a JSON payload to a Pub/Sub topic (non-blocking)."""
    publisher = _get_publisher()
    data      = json.dumps(payload).encode("utf-8")
    loop      = asyncio.get_event_loop()
    future    = publisher.publish(topic_path, data=data, **attributes)
    await loop.run_in_executor(None, lambda: future.result(timeout=10))


async def publish_lead_created(
    case_id:          str,
    partner_id:       str,
    request_id:       str,
    marketing_source: str,
    first_name:       str,
    last_name:        str,
    phone:            str,
) -> None:
    """
    Publish a lead-created event.

    The notification service subscribes to this topic and sends welcome_sms.
    phone and name are included so the notification service can dispatch
    without making a Firestore lookup.

    Schema (notification service reads these exact keys):
      eventType      : "lead-created"
      caseId         : str
      partnerId      : str
      requestId      : str
      marketingSource: str
      firstName      : str
      lastName       : str
      phone          : str   ← E.164, required for welcome_sms
    """
    settings   = get_settings()
    publisher  = _get_publisher()
    topic_path = publisher.topic_path(
        settings.gcp_project_id,
        settings.pubsub_lead_created_topic,
    )
    payload = {
        "eventType":       "lead-created",
        "caseId":          case_id,
        "partnerId":       partner_id,
        "requestId":       request_id,
        "marketingSource": marketing_source,
        "firstName":       first_name,
        "lastName":        last_name,
        "phone":           phone,
    }
    await _publish(topic_path, payload, caseId=case_id)
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
    Publish a lead-screened event.

    Used for audit trail and to trigger staff in-app notifications
    (written to Firestore by case_service.write_staff_screening_notification).
    No SMS is triggered from this event — staff alerts are in-app only.

    Schema:
      eventType  : "lead-screened"
      caseId     : str
      eligibility: "eligible" | "ineligible" | "needs_review"
      score      : int
      flags      : list[str]
      newStatus  : str
      requestId  : str
    """
    settings   = get_settings()
    publisher  = _get_publisher()
    topic_path = publisher.topic_path(
        settings.gcp_project_id,
        settings.pubsub_lead_screened_topic,
    )
    payload = {
        "eventType":   "lead-screened",
        "caseId":      case_id,
        "eligibility": eligibility,
        "score":       score,
        "flags":       flags,
        "newStatus":   new_status,
        "requestId":   request_id,
    }
    await _publish(topic_path, payload, caseId=case_id, eligibility=eligibility)
    logger.info("pubsub_lead_screened_published", case_id=case_id, eligibility=eligibility)


async def publish_lead_followup(
    case_id:    str,
    first_name: str,
    phone:      str,
    request_id: str,
) -> None:
    """
    Publish a lead-followup event.

    Called from /internal/tasks/followup (48h Cloud Task handler) after the
    Admin Staff Firestore task is created.
    The notification service subscribes to this topic and sends followup_sms.

    Schema (notification service reads these exact keys):
      eventType : "lead-followup"
      caseId    : str
      firstName : str
      phone     : str   ← E.164, required for followup_sms
      requestId : str
    """
    settings   = get_settings()
    publisher  = _get_publisher()
    topic_path = publisher.topic_path(
        settings.gcp_project_id,
        settings.pubsub_lead_followup_topic,
    )
    payload = {
        "eventType": "lead-followup",
        "caseId":    case_id,
        "firstName": first_name,
        "phone":     phone,
        "requestId": request_id,
    }
    await _publish(topic_path, payload, caseId=case_id)
    logger.info("pubsub_lead_followup_published", case_id=case_id)
