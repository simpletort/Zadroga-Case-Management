from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from app.models.task import TaskListResponse, TaskStatus
from app.services import task_service
from app.utils.auth import ROLE_HIERARCHY

router = APIRouter(tags=["tasks"])


@router.get("/users/{user_id}/tasks", response_model=TaskListResponse)
def list_user_tasks(
    user_id: str,
    request: Request,
    status: Optional[TaskStatus] = Query(default=None),
    overdue_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
):
    user = request.state.user
    # Staff can only query their own tasks; senior_partner+ can query any user
    if user_id != user.get("uid", ""):
        user_level = ROLE_HIERARCHY.get(user.get("role", ""), 0)
        if user_level < ROLE_HIERARCHY.get("senior_partner", 99):
            raise HTTPException(
                status_code=403,
                detail="Viewing another user's tasks requires at least 'senior_partner' access.",
            )

    return task_service.list_user_tasks(
        user_id,
        status_filter=status.value if status else None,
        overdue_only=overdue_only,
        limit=limit,
    )
