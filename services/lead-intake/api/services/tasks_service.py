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


def _bulk_import_queue_path(client: tasks_v2.CloudTasksClient) -> str:
    settings = get_settings()
    return client.queue_path(
        settings.gcp_project_id,
        settings.cloud_tasks_location,
        settings.cloud_tasks_bulk_import_queue,
    )


async def _enqueue_bulk_import_task(handler_path: str, payload: dict, service_account_email: str, delay_seconds: int) -> str:
    settings = get_settings()
    client   = _get_client()
    parent   = _bulk_import_queue_path(client)

    body        = json.dumps(payload).encode()
    handler_url = f"{settings.cloud_tasks_handler_url}{handler_path}"

    schedule_time = datetime.utcnow() + timedelta(seconds=delay_seconds)
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(schedule_time)

    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": handler_url,
            "headers": {"Content-Type": "application/json"},
            "body": body,
            "oidc_token": {
                "service_account_email": service_account_email,
                "audience": handler_url,
            },
        },
        "schedule_time": timestamp,
    }

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.create_task(request={"parent": parent, "task": task}),
    )
    return response.name


async def create_scan_check_task(
    job_id: str,
    service_account_email: str,
    delay_seconds: int = 5,
) -> str:
    """
    Enqueue an HTTP task to /internal/tasks/bulk-import-scan-check, polling
    storage-gateway's virus-scan status for a bulk-import job. Re-enqueued by
    the handler itself (with the same delay) while the scan is still pending.
    """
    task_name = await _enqueue_bulk_import_task(
        handler_path="/api/v1/leads/internal/tasks/bulk-import-scan-check",
        payload={"jobId": job_id},
        service_account_email=service_account_email,
        delay_seconds=delay_seconds,
    )
    logger.info("bulk_import_scan_check_task_created", job_id=job_id, task_name=task_name)
    return task_name


async def create_bulk_import_chunk_task(
    job_id: str,
    row_start: int,
    row_end: int,
    service_account_email: str,
) -> str:
    """
    Enqueue an HTTP task to /internal/tasks/bulk-import to process rows
    [row_start, row_end) of a bulk-import job. Scheduled immediately (no
    delay) — the scan-check stage already gated on the file being clean.
    """
    task_name = await _enqueue_bulk_import_task(
        handler_path="/api/v1/leads/internal/tasks/bulk-import",
        payload={"jobId": job_id, "rowStart": row_start, "rowEnd": row_end},
        service_account_email=service_account_email,
        delay_seconds=0,
    )
    logger.info("bulk_import_chunk_task_created", job_id=job_id, row_start=row_start, row_end=row_end, task_name=task_name)
    return task_name
