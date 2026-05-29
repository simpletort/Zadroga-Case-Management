import uuid
import logging
from typing import Optional
from datetime import timezone

from fastapi import HTTPException
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from app.models.task import (
    TaskStatus, TaskPriority, TaskType,
    CreateTaskRequest, UpdateTaskRequest, CompleteTaskRequest,
    AssignTaskRequest, TaskResponse, TaskListResponse,
)
from app.utils.firestore import get_firestore_client
from app.utils.date_helpers import now_utc, to_firestore_timestamp

logger = logging.getLogger(__name__)

# Valid status transitions — OVERDUE is only set by the internal reminder callback.
VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING:     {TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED, TaskStatus.SKIPPED, TaskStatus.OVERDUE},
    TaskStatus.IN_PROGRESS: {TaskStatus.COMPLETED, TaskStatus.SKIPPED, TaskStatus.OVERDUE},
    TaskStatus.OVERDUE:     {TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED, TaskStatus.SKIPPED},
    TaskStatus.COMPLETED:   set(),
    TaskStatus.SKIPPED:     set(),
}


def _tasks_ref(case_id: str):
    db = get_firestore_client()
    return db.collection("cases").document(case_id).collection("tasks")


def _validate_transition(current: TaskStatus, new: TaskStatus) -> None:
    if new not in VALID_TRANSITIONS.get(current, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Invalid transition: {current.value} → {new.value}",
        )


def _doc_to_response(doc) -> TaskResponse:
    data = doc.to_dict()
    if not data:
        raise HTTPException(status_code=404, detail="Task not found.")
    return TaskResponse.from_firestore(doc.id, data)


def get_task(task_id: str, case_id: Optional[str] = None) -> TaskResponse:
    db = get_firestore_client()

    if case_id:
        doc = _tasks_ref(case_id).document(task_id).get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Task not found.")
        return _doc_to_response(doc)

    # Fallback: collection-group query (slower; use only when caseId is unknown)
    results = list(
        db.collection_group("tasks")
        .where("taskId", "==", task_id)
        .limit(1)
        .stream()
    )
    if not results:
        raise HTTPException(status_code=404, detail="Task not found.")
    return _doc_to_response(results[0])


def create_task(req: CreateTaskRequest) -> TaskResponse:
    task_id = str(uuid.uuid4())
    now = now_utc()

    doc_data = {
        "taskId": task_id,
        "caseId": req.caseId,
        "workflowExecutionId": req.workflowExecutionId,
        "title": req.title,
        "description": req.description,
        "taskType": req.taskType.value,
        "status": TaskStatus.PENDING.value,
        "priority": req.priority.value,
        "assignedTo": req.assignedTo,
        "assignedToRole": req.assignedToRole,
        "dueAt": to_firestore_timestamp(req.dueAt) if req.dueAt else None,
        "reminderSentAt": None,
        "createdAt": SERVER_TIMESTAMP,
        "updatedAt": SERVER_TIMESTAMP,
        "completedAt": None,
        "completedBy": None,
        "completionNotes": None,
        "metadata": req.metadata,
    }

    _tasks_ref(req.caseId).document(task_id).set(doc_data)
    logger.info("task_created task_id=%s case_id=%s", task_id, req.caseId)

    # Read back to get resolved SERVER_TIMESTAMP values
    doc = _tasks_ref(req.caseId).document(task_id).get()
    return _doc_to_response(doc)


def update_task(task_id: str, case_id: str, req: UpdateTaskRequest) -> TaskResponse:
    ref = _tasks_ref(case_id).document(task_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Task not found.")

    updates: dict = {"updatedAt": SERVER_TIMESTAMP}
    if req.title is not None:
        updates["title"] = req.title
    if req.description is not None:
        updates["description"] = req.description
    if req.priority is not None:
        updates["priority"] = req.priority.value
    if req.dueAt is not None:
        updates["dueAt"] = to_firestore_timestamp(req.dueAt)
    if req.metadata is not None:
        updates["metadata"] = req.metadata

    ref.update(updates)
    return _doc_to_response(ref.get())


def start_task(task_id: str, case_id: str) -> TaskResponse:
    ref = _tasks_ref(case_id).document(task_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Task not found.")

    current = TaskStatus(doc.to_dict()["status"])
    _validate_transition(current, TaskStatus.IN_PROGRESS)

    ref.update({"status": TaskStatus.IN_PROGRESS.value, "updatedAt": SERVER_TIMESTAMP})
    return _doc_to_response(ref.get())


def complete_task(task_id: str, case_id: str, req: CompleteTaskRequest) -> TaskResponse:
    ref = _tasks_ref(case_id).document(task_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Task not found.")

    current = TaskStatus(doc.to_dict()["status"])
    _validate_transition(current, TaskStatus.COMPLETED)

    updates = {
        "status": TaskStatus.COMPLETED.value,
        "completedAt": to_firestore_timestamp(now_utc()),
        "completedBy": req.completedBy,
        "completionNotes": req.completionNotes,
        "updatedAt": SERVER_TIMESTAMP,
    }
    if req.metadata:
        existing_meta = doc.to_dict().get("metadata", {})
        updates["metadata"] = {**existing_meta, **req.metadata}

    ref.update(updates)
    return _doc_to_response(ref.get())


def skip_task(task_id: str, case_id: str, reason: str) -> TaskResponse:
    ref = _tasks_ref(case_id).document(task_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Task not found.")

    current = TaskStatus(doc.to_dict()["status"])
    _validate_transition(current, TaskStatus.SKIPPED)

    existing_meta = doc.to_dict().get("metadata", {})
    ref.update({
        "status": TaskStatus.SKIPPED.value,
        "metadata": {**existing_meta, "skipReason": reason},
        "updatedAt": SERVER_TIMESTAMP,
    })
    return _doc_to_response(ref.get())


def assign_task(task_id: str, case_id: str, req: AssignTaskRequest) -> TaskResponse:
    ref = _tasks_ref(case_id).document(task_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Task not found.")

    updates: dict = {"updatedAt": SERVER_TIMESTAMP}
    if req.assignedTo is not None:
        updates["assignedTo"] = req.assignedTo
    if req.assignedToRole is not None:
        updates["assignedToRole"] = req.assignedToRole

    ref.update(updates)
    return _doc_to_response(ref.get())


def mark_overdue(task_id: str, case_id: str) -> TaskResponse:
    """Called only by the internal /internal/reminders Cloud Tasks callback."""
    ref = _tasks_ref(case_id).document(task_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Task not found.")

    current = TaskStatus(doc.to_dict()["status"])
    if current in (TaskStatus.COMPLETED, TaskStatus.SKIPPED):
        return _doc_to_response(doc)   # no-op for terminal statuses

    _validate_transition(current, TaskStatus.OVERDUE)
    ref.update({
        "status": TaskStatus.OVERDUE.value,
        "reminderSentAt": to_firestore_timestamp(now_utc()),
        "updatedAt": SERVER_TIMESTAMP,
    })
    return _doc_to_response(ref.get())


def delete_task(task_id: str, case_id: str) -> None:
    ref = _tasks_ref(case_id).document(task_id)
    if not ref.get().exists:
        raise HTTPException(status_code=404, detail="Task not found.")
    ref.delete()


def list_case_tasks(
    case_id: str,
    status_filter: Optional[str] = None,
    priority_filter: Optional[str] = None,
    limit: int = 50,
) -> TaskListResponse:
    from google.cloud.firestore_v1.base_query import FieldFilter
    query = _tasks_ref(case_id)

    if status_filter:
        query = query.where(filter=FieldFilter("status", "==", status_filter))
    if priority_filter:
        query = query.where(filter=FieldFilter("priority", "==", priority_filter))

    query = query.order_by("createdAt").limit(min(limit, 200))
    docs = list(query.stream())
    tasks = [_doc_to_response(d) for d in docs]
    return TaskListResponse(tasks=tasks, count=len(tasks))


def list_user_tasks(
    user_id: str,
    status_filter: Optional[str] = None,
    overdue_only: bool = False,
    limit: int = 50,
) -> TaskListResponse:
    from google.cloud.firestore_v1.base_query import FieldFilter
    db = get_firestore_client()
    query = db.collection_group("tasks").where(filter=FieldFilter("assignedTo", "==", user_id))

    if overdue_only:
        query = query.where(filter=FieldFilter("status", "==", TaskStatus.OVERDUE.value))
    elif status_filter:
        query = query.where(filter=FieldFilter("status", "==", status_filter))

    query = query.order_by("dueAt").limit(min(limit, 200))
    docs = list(query.stream())
    tasks = [_doc_to_response(d) for d in docs]
    return TaskListResponse(tasks=tasks, count=len(tasks))
