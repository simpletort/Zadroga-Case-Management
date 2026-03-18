"""
api/services/tasks_service.py — Cloud Tasks enqueue for 48-hour follow-up.
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2
from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)
_client = None


def _get_client() -> tasks_v2.CloudTasksClient:
    global _client
    if _client is None:
        _client = tasks_v2.CloudTasksClient()
    return _client


async def create_followup_task(
    case_id: str,
    service_account_email: str,
) -> str:
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

    response = client.create_task(request={"parent": parent, "task": task})
    logger.info("cloud_task_created", case_id=case_id, task_name=response.name)
    return response.name
