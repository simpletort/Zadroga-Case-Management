from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi import status as http_status

from app.models.task import (
    CreateTaskRequest, UpdateTaskRequest, CompleteTaskRequest,
    AssignTaskRequest, SkipTaskRequest, TaskResponse, TaskListResponse,
    TaskStatus, TaskPriority,
)
from app.services import task_service, reminder_service
from app.utils.auth import require_min_role, ROLE_HIERARCHY

router = APIRouter(tags=["tasks"])


@router.post("/tasks", response_model=TaskResponse, status_code=http_status.HTTP_201_CREATED)
def create_task(
    body: CreateTaskRequest,
    user: dict = Depends(require_min_role("task_create")),
):
    task = task_service.create_task(body)
    if task.dueAt:
        reminder_service.schedule_reminder(task)
    return task


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: str,
    caseId: Optional[str] = Query(default=None),
    user: dict = Depends(require_min_role("task_read")),
):
    return task_service.get_task(task_id, caseId)


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: str,
    body: UpdateTaskRequest,
    caseId: str = Query(...),
    user: dict = Depends(require_min_role("task_update")),
):
    task = task_service.update_task(task_id, caseId, body)
    # Reschedule reminder if dueAt was updated
    if body.dueAt is not None and task.dueAt:
        reminder_service.schedule_reminder(task)
    return task


@router.post("/tasks/{task_id}/start", response_model=TaskResponse)
def start_task(
    task_id: str,
    caseId: str = Query(...),
    user: dict = Depends(require_min_role("task_start")),
):
    return task_service.start_task(task_id, caseId)


@router.post("/tasks/{task_id}/complete", response_model=TaskResponse)
def complete_task(
    task_id: str,
    body: CompleteTaskRequest,
    caseId: str = Query(...),
    user: dict = Depends(require_min_role("task_complete")),
):
    return task_service.complete_task(task_id, caseId, body)


@router.post("/tasks/{task_id}/assign", response_model=TaskResponse)
def assign_task(
    task_id: str,
    body: AssignTaskRequest,
    caseId: str = Query(...),
    user: dict = Depends(require_min_role("task_assign")),
):
    # Assigning to another user requires junior_partner+
    if body.assignedTo and body.assignedTo != user.get("uid"):
        user_level = ROLE_HIERARCHY.get(user.get("role", ""), 0)
        required_level = ROLE_HIERARCHY.get("junior_partner", 99)
        if user_level < required_level:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=403,
                detail="Assigning tasks to other users requires at least 'junior_partner' access.",
            )
    return task_service.assign_task(task_id, caseId, body)


@router.post("/tasks/{task_id}/skip", response_model=TaskResponse)
def skip_task(
    task_id: str,
    body: SkipTaskRequest,
    caseId: str = Query(...),
    user: dict = Depends(require_min_role("task_skip")),
):
    return task_service.skip_task(task_id, caseId, body.reason)


@router.delete("/tasks/{task_id}", status_code=http_status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: str,
    caseId: str = Query(...),
    user: dict = Depends(require_min_role("task_delete")),
):
    task_service.delete_task(task_id, caseId)


@router.get("/cases/{case_id}/tasks", response_model=TaskListResponse)
def list_case_tasks(
    case_id: str,
    status: Optional[TaskStatus] = Query(default=None),
    priority: Optional[TaskPriority] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(require_min_role("task_list_case")),
):
    return task_service.list_case_tasks(
        case_id,
        status_filter=status.value if status else None,
        priority_filter=priority.value if priority else None,
        limit=limit,
    )
