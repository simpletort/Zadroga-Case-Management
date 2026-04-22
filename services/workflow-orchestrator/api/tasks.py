"""
GET /api/v1/tasks/active
PUT /api/v1/tasks/{task_id}/complete
GET /api/v1/tasks/{task_id}
GET /api/v1/cases/{case_id}/tasks
"""

import structlog
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from models import Task, CompleteTaskRequest, CreateTaskRequest, TaskStatus
from services.firestore_service import FirestoreService
from services.cloud_tasks_service import CloudTasksService

log = structlog.get_logger()
router = APIRouter(tags=["Tasks"])


async def get_firestore() -> FirestoreService:
    return FirestoreService()


async def get_cloud_tasks() -> CloudTasksService:
    return CloudTasksService()


# ---------------------------------------------------------------------------
# Active tasks (cross-case view — used by paralegal / attorney dashboards)
# ---------------------------------------------------------------------------

@router.get(
    "/tasks/active",
    response_model=list[Task],
    summary="List all active tasks across all cases",
)
async def get_active_tasks(
    assigned_to: Optional[str] = Query(None, description="Filter by assignee UID"),
    assigned_to_role: Optional[str] = Query(None, description="Filter by role (paralegal, attorney, client)"),
    case_id: Optional[str] = Query(None, description="Scope to a specific case"),
    limit: int = Query(50, le=200),
    db: FirestoreService = Depends(get_firestore),
):
    """
    Returns tasks with status PENDING or IN_PROGRESS.
    Optionally filtered by assignee, role, or case.
    """
    tasks = await db.list_active_tasks(
        assigned_to=assigned_to,
        assigned_to_role=assigned_to_role,
        case_id=case_id,
        limit=limit,
    )
    return tasks


# ---------------------------------------------------------------------------
# Case-scoped task list
# ---------------------------------------------------------------------------

@router.get(
    "/cases/{case_id}/tasks",
    response_model=list[Task],
    summary="List all tasks for a specific case",
)
async def get_case_tasks(
    case_id: str,
    status_filter: Optional[TaskStatus] = Query(None, alias="status"),
    db: FirestoreService = Depends(get_firestore),
):
    tasks = await db.list_case_tasks(case_id=case_id, status_filter=status_filter)
    return tasks


# ---------------------------------------------------------------------------
# Single task detail
# ---------------------------------------------------------------------------

@router.get(
    "/tasks/{task_id}",
    response_model=Task,
    summary="Get a single task by ID",
)
async def get_task(
    task_id: str,
    case_id: Optional[str] = Query(None, description="Required to look up the task in Firestore sub-collection"),
    db: FirestoreService = Depends(get_firestore),
):
    if not case_id:
        # Fallback: collection group query (slightly more expensive)
        task = await db.get_task_by_id(task_id)
    else:
        task = await db.get_task(case_id=case_id, task_id=task_id)

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found.",
        )
    return task


# ---------------------------------------------------------------------------
# Complete a task
# ---------------------------------------------------------------------------

@router.put(
    "/tasks/{task_id}/complete",
    response_model=Task,
    summary="Mark a task as completed",
)
async def complete_task(
    task_id: str,
    body: CompleteTaskRequest,
    case_id: Optional[str] = Query(None),
    db: FirestoreService = Depends(get_firestore),
):
    """
    Marks a task COMPLETED, records completion metadata, and publishes
    a task.completed event to Pub/Sub so downstream workflows can advance.
    """
    # Resolve the task
    task = (
        await db.get_task(case_id=case_id, task_id=task_id)
        if case_id
        else await db.get_task_by_id(task_id)
    )
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found.",
        )

    if task.status == TaskStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task is already completed.",
        )

    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.utcnow()
    task.completed_by = body.completed_by
    task.completion_notes = body.completion_notes
    task.updated_at = datetime.utcnow()
    if body.metadata:
        task.metadata.update(body.metadata)

    await db.save_task(task)

    log.info("task_completed", task_id=task_id, case_id=task.case_id,
             completed_by=body.completed_by)
    return task


# ---------------------------------------------------------------------------
# Create a task (internal / admin use)
# ---------------------------------------------------------------------------

@router.post(
    "/tasks",
    response_model=Task,
    status_code=status.HTTP_201_CREATED,
    summary="Manually create a task for a case",
)
async def create_task(
    body: CreateTaskRequest,
    db: FirestoreService = Depends(get_firestore),
    cloud_tasks_svc: CloudTasksService = Depends(get_cloud_tasks),
):
    task = Task(**body.model_dump())
    await db.save_task(task)

    # If a due date is set, schedule a Cloud Tasks reminder
    if task.due_date:
        await cloud_tasks_svc.schedule_deadline_reminder(task)

    log.info("task_created", task_id=task.id, case_id=task.case_id,
             task_type=task.task_type)
    return task
