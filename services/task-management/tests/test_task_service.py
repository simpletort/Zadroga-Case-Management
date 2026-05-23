import pytest
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task_data(
    task_id="task-abc",
    case_id="ZAD-2026-05-0001",
    status="pending",
    priority="medium",
    task_type="generic",
    assigned_to="uid-para-1",
    due_at=None,
    metadata=None,
) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "taskId": task_id,
        "caseId": case_id,
        "workflowExecutionId": None,
        "title": "Review medical records",
        "description": None,
        "taskType": task_type,
        "status": status,
        "priority": priority,
        "assignedTo": assigned_to,
        "assignedToRole": None,
        "dueAt": due_at,
        "reminderSentAt": None,
        "createdAt": now,
        "updatedAt": now,
        "completedAt": None,
        "completedBy": None,
        "completionNotes": None,
        "metadata": metadata or {},
    }


def _make_mock_doc(data: dict, task_id: str = "task-abc", exists: bool = True) -> MagicMock:
    doc = MagicMock()
    doc.exists = exists
    doc.id = task_id
    doc.to_dict.return_value = data
    return doc


def _mock_tasks_ref(mock_db, doc=None):
    """
    Wire up the Firestore chain:
      db.collection("cases").document(case_id).collection("tasks")
    Returns the mock collection reference so tests can configure it further.
    """
    mock_col = mock_db.collection.return_value.document.return_value.collection.return_value
    if doc is not None:
        mock_col.document.return_value.get.return_value = doc
    return mock_col


# ---------------------------------------------------------------------------
# get_task
# ---------------------------------------------------------------------------

class TestGetTask:

    @patch("app.services.task_service.get_firestore_client")
    def test_get_task_with_case_id_returns_task(self, mock_get_db):
        from app.services.task_service import get_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data()
        doc = _make_mock_doc(data)
        _mock_tasks_ref(mock_db, doc)

        result = get_task("task-abc", "ZAD-2026-05-0001")

        assert result.taskId == "task-abc"
        assert result.status.value == "pending"
        assert result.caseId == "ZAD-2026-05-0001"

    @patch("app.services.task_service.get_firestore_client")
    def test_get_task_not_found_raises_404(self, mock_get_db):
        from app.services.task_service import get_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        doc = _make_mock_doc({}, exists=False)
        _mock_tasks_ref(mock_db, doc)

        with pytest.raises(HTTPException) as exc:
            get_task("task-abc", "ZAD-2026-05-0001")
        assert exc.value.status_code == 404

    @patch("app.services.task_service.get_firestore_client")
    def test_get_task_without_case_id_uses_collection_group(self, mock_get_db):
        from app.services.task_service import get_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data()
        doc = _make_mock_doc(data)

        mock_db.collection_group.return_value.where.return_value.limit.return_value.stream.return_value = [doc]

        result = get_task("task-abc")

        mock_db.collection_group.assert_called_once_with("tasks")
        assert result.taskId == "task-abc"

    @patch("app.services.task_service.get_firestore_client")
    def test_get_task_without_case_id_not_found_raises_404(self, mock_get_db):
        from app.services.task_service import get_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.collection_group.return_value.where.return_value.limit.return_value.stream.return_value = []

        with pytest.raises(HTTPException) as exc:
            get_task("missing-task")
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------

class TestCreateTask:

    @patch("app.services.task_service.get_firestore_client")
    def test_create_task_writes_to_correct_path(self, mock_get_db):
        from app.services.task_service import create_task
        from app.models.task import CreateTaskRequest

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        # The read-back after set()
        data = _make_task_data()
        doc = _make_mock_doc(data)
        mock_col = _mock_tasks_ref(mock_db, doc)

        req = CreateTaskRequest(
            caseId="ZAD-2026-05-0001",
            title="Review medical records",
            assignedTo="uid-para-1",
        )
        result = create_task(req)

        mock_col.document.return_value.set.assert_called_once()
        assert result.caseId == "ZAD-2026-05-0001"
        assert result.status.value == "pending"

    @patch("app.services.task_service.get_firestore_client")
    def test_create_task_generates_unique_task_id(self, mock_get_db):
        from app.services.task_service import create_task
        from app.models.task import CreateTaskRequest

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data()
        doc = _make_mock_doc(data)
        _mock_tasks_ref(mock_db, doc)

        req = CreateTaskRequest(caseId="ZAD-2026-05-0001", title="Task 1")
        create_task(req)

        set_call_kwargs = mock_db.collection.return_value.document.return_value \
            .collection.return_value.document.return_value.set.call_args[0][0]
        task_id = set_call_kwargs["taskId"]
        assert len(task_id) == 36  # UUID4 format

    @patch("app.services.task_service.get_firestore_client")
    def test_create_task_stores_due_at_as_timestamp(self, mock_get_db):
        from app.services.task_service import create_task
        from app.models.task import CreateTaskRequest

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data()
        doc = _make_mock_doc(data)
        _mock_tasks_ref(mock_db, doc)

        due = datetime(2026, 7, 1, tzinfo=timezone.utc)
        req = CreateTaskRequest(caseId="ZAD-2026-05-0001", title="File motion", dueAt=due)
        create_task(req)

        set_call_kwargs = mock_db.collection.return_value.document.return_value \
            .collection.return_value.document.return_value.set.call_args[0][0]
        assert set_call_kwargs["dueAt"] == due


# ---------------------------------------------------------------------------
# update_task
# ---------------------------------------------------------------------------

class TestUpdateTask:

    @patch("app.services.task_service.get_firestore_client")
    def test_update_task_only_patches_provided_fields(self, mock_get_db):
        from app.services.task_service import update_task
        from app.models.task import UpdateTaskRequest

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data()
        doc = _make_mock_doc(data)
        mock_col = _mock_tasks_ref(mock_db, doc)

        req = UpdateTaskRequest(title="Updated title")
        update_task("task-abc", "ZAD-2026-05-0001", req)

        update_call = mock_col.document.return_value.update.call_args[0][0]
        assert "title" in update_call
        assert update_call["title"] == "Updated title"
        assert "priority" not in update_call
        assert "description" not in update_call

    @patch("app.services.task_service.get_firestore_client")
    def test_update_task_not_found_raises_404(self, mock_get_db):
        from app.services.task_service import update_task
        from app.models.task import UpdateTaskRequest

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        doc = _make_mock_doc({}, exists=False)
        _mock_tasks_ref(mock_db, doc)

        with pytest.raises(HTTPException) as exc:
            update_task("task-abc", "ZAD-2026-05-0001", UpdateTaskRequest(title="X"))
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------

class TestStatusTransitions:

    @patch("app.services.task_service.get_firestore_client")
    def test_start_task_pending_to_in_progress(self, mock_get_db):
        from app.services.task_service import start_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data(status="pending")
        doc = _make_mock_doc(data)
        mock_col = _mock_tasks_ref(mock_db, doc)

        start_task("task-abc", "ZAD-2026-05-0001")

        update_call = mock_col.document.return_value.update.call_args[0][0]
        assert update_call["status"] == "in_progress"

    @patch("app.services.task_service.get_firestore_client")
    def test_start_task_overdue_to_in_progress(self, mock_get_db):
        from app.services.task_service import start_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data(status="overdue")
        doc = _make_mock_doc(data)
        mock_col = _mock_tasks_ref(mock_db, doc)

        start_task("task-abc", "ZAD-2026-05-0001")

        update_call = mock_col.document.return_value.update.call_args[0][0]
        assert update_call["status"] == "in_progress"

    @patch("app.services.task_service.get_firestore_client")
    def test_start_task_completed_raises_409(self, mock_get_db):
        from app.services.task_service import start_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data(status="completed")
        doc = _make_mock_doc(data)
        _mock_tasks_ref(mock_db, doc)

        with pytest.raises(HTTPException) as exc:
            start_task("task-abc", "ZAD-2026-05-0001")
        assert exc.value.status_code == 409
        assert "completed" in exc.value.detail

    @patch("app.services.task_service.get_firestore_client")
    def test_start_task_skipped_raises_409(self, mock_get_db):
        from app.services.task_service import start_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data(status="skipped")
        doc = _make_mock_doc(data)
        _mock_tasks_ref(mock_db, doc)

        with pytest.raises(HTTPException) as exc:
            start_task("task-abc", "ZAD-2026-05-0001")
        assert exc.value.status_code == 409

    @patch("app.services.task_service.get_firestore_client")
    def test_complete_task_from_pending(self, mock_get_db):
        from app.services.task_service import complete_task
        from app.models.task import CompleteTaskRequest

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data(status="pending")
        doc = _make_mock_doc(data)
        mock_col = _mock_tasks_ref(mock_db, doc)

        req = CompleteTaskRequest(completedBy="uid-atty-1", completionNotes="Done")
        complete_task("task-abc", "ZAD-2026-05-0001", req)

        update_call = mock_col.document.return_value.update.call_args[0][0]
        assert update_call["status"] == "completed"
        assert update_call["completedBy"] == "uid-atty-1"
        assert update_call["completionNotes"] == "Done"
        assert update_call["completedAt"] is not None

    @patch("app.services.task_service.get_firestore_client")
    def test_complete_task_from_in_progress(self, mock_get_db):
        from app.services.task_service import complete_task
        from app.models.task import CompleteTaskRequest

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data(status="in_progress")
        doc = _make_mock_doc(data)
        mock_col = _mock_tasks_ref(mock_db, doc)

        req = CompleteTaskRequest(completedBy="uid-para-1")
        complete_task("task-abc", "ZAD-2026-05-0001", req)

        update_call = mock_col.document.return_value.update.call_args[0][0]
        assert update_call["status"] == "completed"

    @patch("app.services.task_service.get_firestore_client")
    def test_complete_already_completed_raises_409(self, mock_get_db):
        from app.services.task_service import complete_task
        from app.models.task import CompleteTaskRequest

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data(status="completed")
        doc = _make_mock_doc(data)
        _mock_tasks_ref(mock_db, doc)

        with pytest.raises(HTTPException) as exc:
            complete_task("task-abc", "ZAD-2026-05-0001", CompleteTaskRequest(completedBy="uid"))
        assert exc.value.status_code == 409

    @patch("app.services.task_service.get_firestore_client")
    def test_skip_task_records_reason_in_metadata(self, mock_get_db):
        from app.services.task_service import skip_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data(status="pending", metadata={"existingKey": "val"})
        doc = _make_mock_doc(data)
        mock_col = _mock_tasks_ref(mock_db, doc)

        skip_task("task-abc", "ZAD-2026-05-0001", "Client withdrew")

        update_call = mock_col.document.return_value.update.call_args[0][0]
        assert update_call["status"] == "skipped"
        assert update_call["metadata"]["skipReason"] == "Client withdrew"
        assert update_call["metadata"]["existingKey"] == "val"  # existing metadata preserved

    @patch("app.services.task_service.get_firestore_client")
    def test_skip_completed_task_raises_409(self, mock_get_db):
        from app.services.task_service import skip_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data(status="completed")
        doc = _make_mock_doc(data)
        _mock_tasks_ref(mock_db, doc)

        with pytest.raises(HTTPException) as exc:
            skip_task("task-abc", "ZAD-2026-05-0001", "reason")
        assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# assign_task
# ---------------------------------------------------------------------------

class TestAssignTask:

    @patch("app.services.task_service.get_firestore_client")
    def test_assign_to_user(self, mock_get_db):
        from app.services.task_service import assign_task
        from app.models.task import AssignTaskRequest

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data()
        doc = _make_mock_doc(data)
        mock_col = _mock_tasks_ref(mock_db, doc)

        req = AssignTaskRequest(assignedTo="uid-new-para")
        assign_task("task-abc", "ZAD-2026-05-0001", req)

        update_call = mock_col.document.return_value.update.call_args[0][0]
        assert update_call["assignedTo"] == "uid-new-para"

    @patch("app.services.task_service.get_firestore_client")
    def test_assign_to_role(self, mock_get_db):
        from app.services.task_service import assign_task
        from app.models.task import AssignTaskRequest

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data()
        doc = _make_mock_doc(data)
        mock_col = _mock_tasks_ref(mock_db, doc)

        req = AssignTaskRequest(assignedToRole="paralegal")
        assign_task("task-abc", "ZAD-2026-05-0001", req)

        update_call = mock_col.document.return_value.update.call_args[0][0]
        assert update_call["assignedToRole"] == "paralegal"

    def test_assign_request_requires_at_least_one_field(self):
        from app.models.task import AssignTaskRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AssignTaskRequest()  # neither assignedTo nor assignedToRole


# ---------------------------------------------------------------------------
# mark_overdue
# ---------------------------------------------------------------------------

class TestMarkOverdue:

    @patch("app.services.task_service.get_firestore_client")
    def test_mark_overdue_from_pending(self, mock_get_db):
        from app.services.task_service import mark_overdue

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data(status="pending")
        doc = _make_mock_doc(data)
        mock_col = _mock_tasks_ref(mock_db, doc)

        mark_overdue("task-abc", "ZAD-2026-05-0001")

        update_call = mock_col.document.return_value.update.call_args[0][0]
        assert update_call["status"] == "overdue"
        assert update_call["reminderSentAt"] is not None

    @patch("app.services.task_service.get_firestore_client")
    def test_mark_overdue_noop_when_completed(self, mock_get_db):
        from app.services.task_service import mark_overdue

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data(status="completed")
        doc = _make_mock_doc(data)
        mock_col = _mock_tasks_ref(mock_db, doc)

        mark_overdue("task-abc", "ZAD-2026-05-0001")

        # update() should NOT be called — it's a no-op for terminal statuses
        mock_col.document.return_value.update.assert_not_called()

    @patch("app.services.task_service.get_firestore_client")
    def test_mark_overdue_noop_when_skipped(self, mock_get_db):
        from app.services.task_service import mark_overdue

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data(status="skipped")
        doc = _make_mock_doc(data)
        mock_col = _mock_tasks_ref(mock_db, doc)

        mark_overdue("task-abc", "ZAD-2026-05-0001")

        mock_col.document.return_value.update.assert_not_called()

    @patch("app.services.task_service.get_firestore_client")
    def test_mark_overdue_from_in_progress(self, mock_get_db):
        from app.services.task_service import mark_overdue

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        data = _make_task_data(status="in_progress")
        doc = _make_mock_doc(data)
        mock_col = _mock_tasks_ref(mock_db, doc)

        mark_overdue("task-abc", "ZAD-2026-05-0001")

        update_call = mock_col.document.return_value.update.call_args[0][0]
        assert update_call["status"] == "overdue"


# ---------------------------------------------------------------------------
# delete_task
# ---------------------------------------------------------------------------

class TestDeleteTask:

    @patch("app.services.task_service.get_firestore_client")
    def test_delete_task(self, mock_get_db):
        from app.services.task_service import delete_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        doc = _make_mock_doc(_make_task_data())
        mock_col = _mock_tasks_ref(mock_db, doc)

        delete_task("task-abc", "ZAD-2026-05-0001")

        mock_col.document.return_value.delete.assert_called_once()

    @patch("app.services.task_service.get_firestore_client")
    def test_delete_task_not_found_raises_404(self, mock_get_db):
        from app.services.task_service import delete_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        doc = _make_mock_doc({}, exists=False)
        _mock_tasks_ref(mock_db, doc)

        with pytest.raises(HTTPException) as exc:
            delete_task("task-abc", "ZAD-2026-05-0001")
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# list_case_tasks / list_user_tasks
# ---------------------------------------------------------------------------

class TestListTasks:

    @patch("app.services.task_service.get_firestore_client")
    def test_list_case_tasks_returns_all(self, mock_get_db):
        from app.services.task_service import list_case_tasks

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        docs = [
            _make_mock_doc(_make_task_data(task_id=f"task-{i}", status="pending"), task_id=f"task-{i}")
            for i in range(3)
        ]

        (mock_db.collection.return_value.document.return_value.collection.return_value
         .order_by.return_value.limit.return_value.stream.return_value) = docs

        result = list_case_tasks("ZAD-2026-05-0001")
        assert result.count == 3
        assert len(result.tasks) == 3

    @patch("app.services.task_service.get_firestore_client")
    def test_list_case_tasks_with_status_filter(self, mock_get_db):
        from app.services.task_service import list_case_tasks

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        (mock_db.collection.return_value.document.return_value.collection.return_value
         .where.return_value.order_by.return_value.limit.return_value.stream.return_value) = []

        result = list_case_tasks("ZAD-2026-05-0001", status_filter="pending")

        where_call = (mock_db.collection.return_value.document.return_value
                      .collection.return_value.where.call_args)
        assert where_call[0] == ("status", "==", "pending")
        assert result.count == 0

    @patch("app.services.task_service.get_firestore_client")
    def test_list_user_tasks_uses_collection_group(self, mock_get_db):
        from app.services.task_service import list_user_tasks

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        docs = [_make_mock_doc(_make_task_data(assigned_to="uid-para-1"))]
        (mock_db.collection_group.return_value.where.return_value
         .order_by.return_value.limit.return_value.stream.return_value) = docs

        result = list_user_tasks("uid-para-1")

        mock_db.collection_group.assert_called_once_with("tasks")
        assert result.count == 1

    @patch("app.services.task_service.get_firestore_client")
    def test_list_user_tasks_overdue_only_filters_by_status(self, mock_get_db):
        from app.services.task_service import list_user_tasks

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        (mock_db.collection_group.return_value.where.return_value.where.return_value
         .order_by.return_value.limit.return_value.stream.return_value) = []

        list_user_tasks("uid-para-1", overdue_only=True)

        # First where: assignedTo filter, second where: status == overdue
        second_where = (mock_db.collection_group.return_value.where.return_value
                        .where.call_args[0])
        assert second_where == ("status", "==", "overdue")


# ---------------------------------------------------------------------------
# Valid transition matrix — exhaustive
# ---------------------------------------------------------------------------

class TestTransitionMatrix:
    """
    Verify VALID_TRANSITIONS matches the spec exactly:
      pending     → in_progress, completed, skipped, overdue
      in_progress → completed, skipped, overdue
      overdue     → in_progress, completed, skipped
      completed   → (nothing)
      skipped     → (nothing)
    """

    def test_valid_transitions_are_complete(self):
        from app.services.task_service import VALID_TRANSITIONS
        from app.models.task import TaskStatus

        assert VALID_TRANSITIONS[TaskStatus.PENDING] == {
            TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED,
            TaskStatus.SKIPPED, TaskStatus.OVERDUE,
        }
        assert VALID_TRANSITIONS[TaskStatus.IN_PROGRESS] == {
            TaskStatus.COMPLETED, TaskStatus.SKIPPED, TaskStatus.OVERDUE,
        }
        assert VALID_TRANSITIONS[TaskStatus.OVERDUE] == {
            TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED, TaskStatus.SKIPPED,
        }
        assert VALID_TRANSITIONS[TaskStatus.COMPLETED] == set()
        assert VALID_TRANSITIONS[TaskStatus.SKIPPED] == set()

    @pytest.mark.parametrize("current,target", [
        ("completed", "pending"),
        ("completed", "in_progress"),
        ("completed", "overdue"),
        ("completed", "skipped"),
        ("skipped", "pending"),
        ("skipped", "in_progress"),
        ("skipped", "completed"),
        ("in_progress", "pending"),
    ])
    def test_invalid_transitions_raise_409(self, current, target):
        from app.services.task_service import _validate_transition
        from app.models.task import TaskStatus

        with pytest.raises(HTTPException) as exc:
            _validate_transition(TaskStatus(current), TaskStatus(target))
        assert exc.value.status_code == 409
