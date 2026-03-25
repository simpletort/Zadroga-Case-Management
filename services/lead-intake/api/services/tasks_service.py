"""
api/services/tasks_service.py — Cloud Tasks enqueue for 48-hour follow-up.

Bug 3 fix: the sync CloudTasksClient.create_task() call is now run via
asyncio.get_event_loop().run_in_executor() so it never blocks the uvicorn
event loop. The sync client is still used (there is no official async Tasks
client in the Python SDK) but offloaded to the default thread pool.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2

from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)
_client: tasks_v2.CloudTasksClient | None = None


def _get_client() -> tasks_v2.CloudTasksClient:
    global _client
    if _client is None:
        _client = tasks_v2.CloudTasksClient()
    return _client


async def create_followup_task(
    case_id: str,
    service_account_email: str,
) -> str:
    """
    Enqueue an HTTP task to /internal/tasks/followup scheduled for
    settings.followup_delay_hours from now.

    The sync gRPC call is offloaded to a thread executor so it does not
    block the asyncio event loop.
    """
    settings = get_settings()
    client = _get_client()

    parent = client.queue_path(
        settings.gcp_project_id,
        settings.cloud_tasks_location,
        settings.cloud_tasks_queue,
    )

    payload = json.dumps({"caseId": case_id}).encode()
    handler_url = f"{settings.cloud_tasks_handler_url}/api/v1/leads/internal/tasks/followup"

    schedule_time = datetime.utcnow() + timedelta(hours=settings.followup_delay_hours)
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(schedule_time)

    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": handler_url,
            "headers": {"Content-Type": "application/json"},
            "body": payload,
            "oidc_token": {
                "service_account_email": service_account_email,
                "audience": handler_url,
            },
        },
        "schedule_time": timestamp,
    }

    # Run blocking gRPC call in thread pool to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.create_task(request={"parent": parent, "task": task}),
    )

    logger.info("cloud_task_created", case_id=case_id, task_name=response.name)
    return response.name
