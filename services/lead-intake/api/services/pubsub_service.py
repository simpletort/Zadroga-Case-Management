"""
api/services/pubsub_service.py — Publish Pub/Sub events.

Bug 3 fix: publisher.publish().result() is a blocking call. It is now
run via asyncio.get_event_loop().run_in_executor() to avoid blocking
the uvicorn event loop while waiting for the Pub/Sub ACK.
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
    case_id: str,
    partner_id: str,
    request_id: str,
    marketing_source: str,
) -> None:
    """
    Publish a lead-created event to Pub/Sub.
    The blocking future.result() call is offloaded to the thread pool.
    """
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

    # publish() returns a future; .result() blocks — run in executor
    loop = asyncio.get_event_loop()
    future = publisher.publish(topic_path, data=payload, caseId=case_id)
    await loop.run_in_executor(None, lambda: future.result(timeout=10))

    logger.info("pubsub_lead_created_published", case_id=case_id)
