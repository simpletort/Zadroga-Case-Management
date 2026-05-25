"""
HTTP layer tests — exercises FastAPI routes with mocked business logic and auth.

All task_service functions are mocked so these tests cover:
  - Correct HTTP status codes
  - Request body validation
  - Role enforcement (via inline ROLE_HIERARCHY checks in route handlers)
  - Query parameter handling
"""

import pytest
from unittest.mock import patch, AsyncMock
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.models.task import (
    TaskResponse, TaskListResponse, TaskStatus, TaskPriority, TaskType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task_response(
    task_id="task-abc",
    case_id="ZAD-2026-05-0001",
    status=TaskStatus.PENDING,
) -> TaskResponse:
    now = datetime.now(timezone.utc)
    return TaskResponse(
        taskId=task_id,
        caseId=case_id,
        title="Review medical records",
        taskType=TaskType.GENERIC,
        status=status,
        priority=TaskPriority.MEDIUM,
        createdAt=now,
        updatedAt=now,
    )


def _make_bypass(role: str, uid: str):
    """Return an async method that injects request.state.user and skips real auth."""
    async def bypass(self, request, call_next):
        request.state.user = {"uid": uid, "role": role}
        return await call_next(request)
    return bypass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    from main import app
    with patch("shared.middlewares.auth.AuthMiddleware.dispatch", _make_bypass("admin_staff", "uid-test")):
        app.middleware_stack = None  # force rebuild with patched dispatch
        yield TestClient(app)


@pytest.fixture
def paralegal_client():
    from main import app
    with patch("shared.middlewares.auth.AuthMiddleware.dispatch", _make_bypass("paralegal", "uid-para")):
        app.middleware_stack = None
        yield TestClient(app)


@pytest.fixture
def partner_client():
    from main import app
    with patch("shared.middlewares.auth.AuthMiddleware.dispatch", _make_bypass("junior_partner", "uid-partner")):
        app.middleware_stack = None
        yield TestClient(app)


@pytest.fixture
def senior_client():
    from main import app
    with patch("shared.middlewares.auth.AuthMiddleware.dispatch", _make_bypass("senior_partner", "uid-senior")):
        app.middleware_stack = None
        yield TestClient(app)


# ---------------------------------------------------------------------------
# POST /api/v1/tasks
# ---------------------------------------------------------------------------

class TestCreateTaskRoute:

    @patch("app.routes.tasks.task_service.create_task")
    @patch("app.routes.tasks.reminder_service.schedule_reminder")
    def test_create_task_returns_201(self, mock_reminder, mock_create, client):
        task = _make_task_response()
        mock_create.return_value = task
        mock_reminder.return_value = None

        resp = client.post("/api/v1/tasks", json={
            "caseId": "ZAD-2026-05-0001",
            "title": "Review medical records",
        })

        assert resp.status_code == 201
        assert resp.json()["taskId"] == "task-abc"
        mock_create.assert_called_once()

    @patch("app.routes.tasks.task_service.create_task")
    @patch("app.routes.tasks.reminder_service.schedule_reminder")
    def test_create_task_schedules_reminder_when_due_at_set(self, mock_reminder, mock_create, client):
        task = _make_task_response()
        task.dueAt = datetime(2026, 7, 1, tzinfo=timezone.utc)
        mock_create.return_value = task

        client.post("/api/v1/tasks", json={
            "caseId": "ZAD-2026-05-0001",
            "title": "File motion",
            "dueAt": "2026-07-01T00:00:00Z",
        })

        mock_reminder.assert_called_once_with(task)

    @patch("app.routes.tasks.task_service.create_task")
    @patch("app.routes.tasks.reminder_service.schedule_reminder")
    def test_create_task_no_reminder_without_due_at(self, mock_reminder, mock_create, client):
        task = _make_task_response()
        task.dueAt = None
        mock_create.return_value = task

        client.post("/api/v1/tasks", json={
            "caseId": "ZAD-2026-05-0001",
            "title": "Generic task",
        })

        mock_reminder.assert_not_called()

    def test_create_task_missing_case_id_returns_422(self, client):
        resp = client.post("/api/v1/tasks", json={"title": "No case"})
        assert resp.status_code == 422

    def test_create_task_missing_title_returns_422(self, client):
        resp = client.post("/api/v1/tasks", json={"caseId": "ZAD-2026-05-0001"})
        assert resp.status_code == 422

    def test_create_task_unauthenticated_returns_401(self):
        from main import app
        # No middleware bypass — real middleware returns 401 for missing auth
        bare_client = TestClient(app, raise_server_exceptions=False)
        resp = bare_client.post("/api/v1/tasks", json={
            "caseId": "ZAD-2026-05-0001",
            "title": "Task",
        })
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /api/v1/tasks/{task_id}
# ---------------------------------------------------------------------------

class TestGetTaskRoute:

    @patch("app.routes.tasks.task_service.get_task")
    def test_get_task_returns_200(self, mock_get, client):
        mock_get.return_value = _make_task_response()
        resp = client.get("/api/v1/tasks/task-abc?caseId=ZAD-2026-05-0001")
        assert resp.status_code == 200
        assert resp.json()["taskId"] == "task-abc"

    @patch("app.routes.tasks.task_service.get_task")
    def test_get_task_passes_case_id(self, mock_get, client):
        mock_get.return_value = _make_task_response()
        client.get("/api/v1/tasks/task-abc?caseId=ZAD-2026-05-0001")
        mock_get.assert_called_once_with("task-abc", "ZAD-2026-05-0001")

    @patch("app.routes.tasks.task_service.get_task")
    def test_get_task_without_case_id_passes_none(self, mock_get, client):
        mock_get.return_value = _make_task_response()
        client.get("/api/v1/tasks/task-abc")
        mock_get.assert_called_once_with("task-abc", None)

    @patch("app.routes.tasks.task_service.get_task")
    def test_get_task_404_propagates(self, mock_get, client):
        from fastapi import HTTPException
        mock_get.side_effect = HTTPException(status_code=404, detail="Task not found.")
        resp = client.get("/api/v1/tasks/missing?caseId=ZAD-2026-05-0001")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/v1/tasks/{task_id}
# ---------------------------------------------------------------------------

class TestUpdateTaskRoute:

    @patch("app.routes.tasks.task_service.update_task")
    @patch("app.routes.tasks.reminder_service.schedule_reminder")
    def test_update_task_returns_200(self, mock_reminder, mock_update, client):
        mock_update.return_value = _make_task_response()
        resp = client.patch(
            "/api/v1/tasks/task-abc?caseId=ZAD-2026-05-0001",
            json={"title": "Updated title"},
        )
        assert resp.status_code == 200

    @patch("app.routes.tasks.task_service.update_task")
    @patch("app.routes.tasks.reminder_service.schedule_reminder")
    def test_update_task_reschedules_reminder_when_due_at_changes(
        self, mock_reminder, mock_update, client
    ):
        updated = _make_task_response()
        updated.dueAt = datetime(2026, 8, 1, tzinfo=timezone.utc)
        mock_update.return_value = updated

        client.patch(
            "/api/v1/tasks/task-abc?caseId=ZAD-2026-05-0001",
            json={"dueAt": "2026-08-01T00:00:00Z"},
        )
        mock_reminder.assert_called_once_with(updated)

    def test_update_task_missing_case_id_returns_422(self, client):
        resp = client.patch("/api/v1/tasks/task-abc", json={"title": "X"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/tasks/{task_id}/start
# ---------------------------------------------------------------------------

class TestStartTaskRoute:

    @patch("app.routes.tasks.task_service.start_task")
    def test_start_task_returns_200(self, mock_start, client):
        mock_start.return_value = _make_task_response(status=TaskStatus.IN_PROGRESS)
        resp = client.post("/api/v1/tasks/task-abc/start?caseId=ZAD-2026-05-0001")
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

    @patch("app.routes.tasks.task_service.start_task")
    def test_start_task_409_propagates(self, mock_start, client):
        from fastapi import HTTPException
        mock_start.side_effect = HTTPException(
            status_code=409, detail="Invalid transition: completed → in_progress"
        )
        resp = client.post("/api/v1/tasks/task-abc/start?caseId=ZAD-2026-05-0001")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST /api/v1/tasks/{task_id}/complete
# ---------------------------------------------------------------------------

class TestCompleteTaskRoute:

    @patch("app.routes.tasks.task_service.complete_task")
    def test_complete_task_returns_200(self, mock_complete, client):
        mock_complete.return_value = _make_task_response(status=TaskStatus.COMPLETED)
        resp = client.post(
            "/api/v1/tasks/task-abc/complete?caseId=ZAD-2026-05-0001",
            json={"completedBy": "uid-para-1"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_complete_task_missing_completed_by_returns_422(self, client):
        resp = client.post(
            "/api/v1/tasks/task-abc/complete?caseId=ZAD-2026-05-0001",
            json={},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/tasks/{task_id}/skip
# ---------------------------------------------------------------------------

class TestSkipTaskRoute:

    @patch("app.routes.tasks.task_service.skip_task")
    def test_skip_requires_junior_partner(self, mock_skip, client):
        # client has admin_staff role (level 1) — should be 403
        mock_skip.return_value = _make_task_response(status=TaskStatus.SKIPPED)
        resp = client.post(
            "/api/v1/tasks/task-abc/skip?caseId=ZAD-2026-05-0001",
            json={"reason": "Not applicable"},
        )
        assert resp.status_code == 403

    @patch("app.routes.tasks.task_service.skip_task")
    def test_skip_succeeds_for_junior_partner(self, mock_skip, partner_client):
        mock_skip.return_value = _make_task_response(status=TaskStatus.SKIPPED)
        resp = partner_client.post(
            "/api/v1/tasks/task-abc/skip?caseId=ZAD-2026-05-0001",
            json={"reason": "Not applicable"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"

    @patch("app.routes.tasks.task_service.skip_task")
    def test_skip_missing_reason_returns_422(self, mock_skip, partner_client):
        resp = partner_client.post(
            "/api/v1/tasks/task-abc/skip?caseId=ZAD-2026-05-0001",
            json={},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/tasks/{task_id}/assign
# ---------------------------------------------------------------------------

class TestAssignTaskRoute:

    @patch("app.routes.tasks.task_service.assign_task")
    def test_assign_self_succeeds_for_paralegal(self, mock_assign, paralegal_client):
        mock_assign.return_value = _make_task_response()
        resp = paralegal_client.post(
            "/api/v1/tasks/task-abc/assign?caseId=ZAD-2026-05-0001",
            json={"assignedTo": "uid-para"},   # same uid as paralegal_client fixture
        )
        assert resp.status_code == 200

    @patch("app.routes.tasks.task_service.assign_task")
    def test_assign_other_user_requires_junior_partner(self, mock_assign, paralegal_client):
        mock_assign.return_value = _make_task_response()
        resp = paralegal_client.post(
            "/api/v1/tasks/task-abc/assign?caseId=ZAD-2026-05-0001",
            json={"assignedTo": "uid-someone-else"},
        )
        assert resp.status_code == 403

    @patch("app.routes.tasks.task_service.assign_task")
    def test_assign_other_user_succeeds_for_junior_partner(self, mock_assign, partner_client):
        mock_assign.return_value = _make_task_response()
        resp = partner_client.post(
            "/api/v1/tasks/task-abc/assign?caseId=ZAD-2026-05-0001",
            json={"assignedTo": "uid-someone-else"},
        )
        assert resp.status_code == 200

    def test_assign_missing_both_fields_returns_422(self, paralegal_client):
        resp = paralegal_client.post(
            "/api/v1/tasks/task-abc/assign?caseId=ZAD-2026-05-0001",
            json={},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /api/v1/tasks/{task_id}
# ---------------------------------------------------------------------------

class TestDeleteTaskRoute:

    @patch("app.routes.tasks.task_service.delete_task")
    def test_delete_requires_senior_partner(self, mock_delete, client):
        resp = client.delete("/api/v1/tasks/task-abc?caseId=ZAD-2026-05-0001")
        assert resp.status_code == 403
        mock_delete.assert_not_called()

    @patch("app.routes.tasks.task_service.delete_task")
    def test_delete_succeeds_for_senior_partner(self, mock_delete, senior_client):
        mock_delete.return_value = None
        resp = senior_client.delete("/api/v1/tasks/task-abc?caseId=ZAD-2026-05-0001")
        assert resp.status_code == 204
        mock_delete.assert_called_once_with("task-abc", "ZAD-2026-05-0001")


# ---------------------------------------------------------------------------
# GET /api/v1/cases/{case_id}/tasks
# ---------------------------------------------------------------------------

class TestListCaseTasksRoute:

    @patch("app.routes.tasks.task_service.list_case_tasks")
    def test_list_case_tasks_returns_200(self, mock_list, client):
        mock_list.return_value = TaskListResponse(
            tasks=[_make_task_response()], count=1
        )
        resp = client.get("/api/v1/cases/ZAD-2026-05-0001/tasks")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    @patch("app.routes.tasks.task_service.list_case_tasks")
    def test_list_case_tasks_passes_filters(self, mock_list, client):
        mock_list.return_value = TaskListResponse(tasks=[], count=0)
        client.get("/api/v1/cases/ZAD-2026-05-0001/tasks?status=pending&priority=high&limit=10")
        mock_list.assert_called_once_with(
            "ZAD-2026-05-0001",
            status_filter="pending",
            priority_filter="high",
            limit=10,
        )

    @patch("app.routes.tasks.task_service.list_case_tasks")
    def test_list_case_tasks_invalid_status_returns_422(self, mock_list, client):
        resp = client.get("/api/v1/cases/ZAD-2026-05-0001/tasks?status=invalid_status")
        assert resp.status_code == 422

    @patch("app.routes.tasks.task_service.list_case_tasks")
    def test_list_case_tasks_limit_capped_at_200(self, mock_list, client):
        mock_list.return_value = TaskListResponse(tasks=[], count=0)
        resp = client.get("/api/v1/cases/ZAD-2026-05-0001/tasks?limit=999")
        assert resp.status_code == 422  # ge=1, le=200 validator


# ---------------------------------------------------------------------------
# GET /api/v1/users/{user_id}/tasks
# ---------------------------------------------------------------------------

class TestListUserTasksRoute:

    @patch("app.routes.user_tasks.task_service.list_user_tasks")
    def test_list_own_tasks_returns_200(self, mock_list, client):
        mock_list.return_value = TaskListResponse(
            tasks=[_make_task_response()], count=1
        )
        resp = client.get("/api/v1/users/uid-test/tasks")
        assert resp.status_code == 200

    @patch("app.routes.user_tasks.task_service.list_user_tasks")
    def test_list_other_users_tasks_requires_senior_partner(self, mock_list, client):
        # client fixture has admin_staff role
        resp = client.get("/api/v1/users/uid-someone-else/tasks")
        assert resp.status_code == 403

    @patch("app.routes.user_tasks.task_service.list_user_tasks")
    def test_list_other_users_tasks_succeeds_for_senior_partner(self, mock_list, senior_client):
        mock_list.return_value = TaskListResponse(tasks=[], count=0)
        resp = senior_client.get("/api/v1/users/uid-someone-else/tasks")
        assert resp.status_code == 200

    @patch("app.routes.user_tasks.task_service.list_user_tasks")
    def test_list_user_tasks_overdue_only_filter(self, mock_list, client):
        mock_list.return_value = TaskListResponse(tasks=[], count=0)
        client.get("/api/v1/users/uid-test/tasks?overdue_only=true")
        mock_list.assert_called_once_with(
            "uid-test",
            status_filter=None,
            overdue_only=True,
            limit=50,
        )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class TestHealth:

    def test_health_returns_ok(self):
        from main import app
        bare_client = TestClient(app)
        resp = bare_client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "service": "task-management"}
