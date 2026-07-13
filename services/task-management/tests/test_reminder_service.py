"""
Unit tests for reminder_service.py — Cloud Tasks scheduling and the
/internal/reminders callback endpoint.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task_response(
    task_id="task-abc",
    case_id="ZAD-2026-05-0001",
    due_at=None,
    status="pending",
):
    from app.models.task import TaskResponse, TaskStatus, TaskPriority, TaskType
    now = datetime.now(timezone.utc)
    return TaskResponse(
        taskId=task_id,
        caseId=case_id,
        title="File motion",
        taskType=TaskType.GENERIC,
        status=TaskStatus(status),
        priority=TaskPriority.MEDIUM,
        dueAt=due_at,
        createdAt=now,
        updatedAt=now,
    )


# ---------------------------------------------------------------------------
# schedule_reminder
# ---------------------------------------------------------------------------

class TestScheduleReminder:

    @patch("app.services.reminder_service.tasks_v2.CloudTasksClient")
    @patch("app.services.reminder_service.get_settings")
    def test_schedules_task_when_due_at_in_future(self, mock_settings, mock_client_cls):
        from app.services.reminder_service import schedule_reminder

        settings = MagicMock()
        settings.task_service_url = "https://task-management.run.app"
        settings.service_account_email = "sa@project.iam.gserviceaccount.com"
        settings.gcp_project_id = "simpletort-prod"
        settings.cloud_tasks_location = "us-east1"
        settings.cloud_tasks_queue = "task-reminders"
        settings.reminder_advance_hours = 24
        mock_settings.return_value = settings

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.queue_path.return_value = "projects/p/locations/l/queues/q"
        created_task = MagicMock()
        created_task.name = "projects/p/locations/l/queues/q/tasks/xyz"
        mock_client.create_task.return_value = created_task

        due_at = datetime.now(timezone.utc) + timedelta(days=3)
        task = _make_task_response(due_at=due_at)
        name = schedule_reminder(task)

        assert name == "projects/p/locations/l/queues/q/tasks/xyz"
        mock_client.create_task.assert_called_once()

        # Verify the HTTP request URL points to /internal/reminders
        create_call = mock_client.create_task.call_args[1]["task"]
        assert "/internal/reminders" in create_call.http_request.url

    @patch("app.services.reminder_service.get_settings")
    def test_returns_none_when_no_due_at(self, mock_settings):
        from app.services.reminder_service import schedule_reminder

        settings = MagicMock()
        settings.task_service_url = "https://task-management.run.app"
        settings.service_account_email = "sa@project.iam.gserviceaccount.com"
        mock_settings.return_value = settings

        task = _make_task_response(due_at=None)
        result = schedule_reminder(task)

        assert result is None

    @patch("app.services.reminder_service.tasks_v2.CloudTasksClient")
    @patch("app.services.reminder_service.get_settings")
    def test_returns_none_when_fire_time_in_past(self, mock_settings, mock_client_cls):
        from app.services.reminder_service import schedule_reminder

        settings = MagicMock()
        settings.task_service_url = "https://task-management.run.app"
        settings.service_account_email = "sa@project.iam.gserviceaccount.com"
        settings.reminder_advance_hours = 24
        mock_settings.return_value = settings

        # dueAt is 12h from now — fire_at would be dueAt - 24h = 12h in the past
        due_at = datetime.now(timezone.utc) + timedelta(hours=12)
        task = _make_task_response(due_at=due_at)
        result = schedule_reminder(task)

        assert result is None
        mock_client_cls.return_value.create_task.assert_not_called()

    @patch("app.services.reminder_service.get_settings")
    def test_returns_none_when_config_missing(self, mock_settings):
        from app.services.reminder_service import schedule_reminder

        settings = MagicMock()
        settings.task_service_url = ""   # not configured
        settings.service_account_email = ""
        mock_settings.return_value = settings

        due_at = datetime.now(timezone.utc) + timedelta(days=3)
        task = _make_task_response(due_at=due_at)
        result = schedule_reminder(task)

        assert result is None

    @patch("app.services.reminder_service.tasks_v2.CloudTasksClient")
    @patch("app.services.reminder_service.get_settings")
    def test_payload_contains_task_id_and_case_id(self, mock_settings, mock_client_cls):
        from app.services.reminder_service import schedule_reminder
        import json

        settings = MagicMock()
        settings.task_service_url = "https://task-management.run.app"
        settings.service_account_email = "sa@project.iam.gserviceaccount.com"
        settings.gcp_project_id = "simpletort-prod"
        settings.cloud_tasks_location = "us-east1"
        settings.cloud_tasks_queue = "task-reminders"
        settings.reminder_advance_hours = 24
        mock_settings.return_value = settings

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.queue_path.return_value = "projects/p/locations/l/queues/q"
        mock_client.create_task.return_value = MagicMock(name="task-name")

        due_at = datetime.now(timezone.utc) + timedelta(days=3)
        task = _make_task_response(task_id="task-xyz", case_id="ZAD-2026-05-0001", due_at=due_at)
        schedule_reminder(task)

        create_call = mock_client.create_task.call_args[1]["task"]
        body = json.loads(create_call.http_request.body)
        assert body["taskId"] == "task-xyz"
        assert body["caseId"] == "ZAD-2026-05-0001"

    @patch("app.services.reminder_service.tasks_v2.CloudTasksClient")
    @patch("app.services.reminder_service.get_settings")
    def test_oidc_token_uses_service_account(self, mock_settings, mock_client_cls):
        from app.services.reminder_service import schedule_reminder

        sa = "custom-sa@project.iam.gserviceaccount.com"
        settings = MagicMock()
        settings.task_service_url = "https://task-management.run.app"
        settings.service_account_email = sa
        settings.gcp_project_id = "simpletort-prod"
        settings.cloud_tasks_location = "us-east1"
        settings.cloud_tasks_queue = "task-reminders"
        settings.reminder_advance_hours = 24
        mock_settings.return_value = settings

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.queue_path.return_value = "projects/p/locations/l/queues/q"
        mock_client.create_task.return_value = MagicMock(name="task-name")

        due_at = datetime.now(timezone.utc) + timedelta(days=3)
        schedule_reminder(_make_task_response(due_at=due_at))

        create_call = mock_client.create_task.call_args[1]["task"]
        assert create_call.http_request.oidc_token.service_account_email == sa


# ---------------------------------------------------------------------------
# POST /internal/reminders endpoint
# ---------------------------------------------------------------------------

class TestInternalReminderEndpoint:

    @patch("app.routes.internal.task_service.mark_overdue")
    def test_reminder_callback_marks_task_overdue(self, mock_mark):
        from main import app
        from app.models.task import TaskResponse, TaskStatus, TaskPriority, TaskType

        now = datetime.now(timezone.utc)
        overdue_task = TaskResponse(
            taskId="task-abc",
            caseId="ZAD-2026-05-0001",
            title="Review",
            taskType=TaskType.GENERIC,
            status=TaskStatus.OVERDUE,
            priority=TaskPriority.MEDIUM,
            createdAt=now,
            updatedAt=now,
        )
        mock_mark.return_value = overdue_task

        # Bypass OIDC verification for tests
        with patch("app.routes.internal._verify_oidc_token", return_value=None):
            client = TestClient(app)
            resp = client.post("/internal/reminders", json={
                "taskId": "task-abc",
                "caseId": "ZAD-2026-05-0001",
                "dueAt": "2026-05-22T10:00:00Z",
            })

        assert resp.status_code == 200
        assert resp.json()["status"] == "overdue"
        mock_mark.assert_called_once_with("task-abc", "ZAD-2026-05-0001")

    @patch("app.routes.internal.task_service.mark_overdue")
    def test_reminder_callback_noop_when_already_completed(self, mock_mark):
        from main import app
        from app.models.task import TaskResponse, TaskStatus, TaskPriority, TaskType

        now = datetime.now(timezone.utc)
        completed_task = TaskResponse(
            taskId="task-abc",
            caseId="ZAD-2026-05-0001",
            title="Review",
            taskType=TaskType.GENERIC,
            status=TaskStatus.COMPLETED,
            priority=TaskPriority.MEDIUM,
            createdAt=now,
            updatedAt=now,
        )
        mock_mark.return_value = completed_task

        with patch("app.routes.internal._verify_oidc_token", return_value=None):
            client = TestClient(app)
            resp = client.post("/internal/reminders", json={
                "taskId": "task-abc",
                "caseId": "ZAD-2026-05-0001",
                "dueAt": "2026-05-22T10:00:00Z",
            })

        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_reminder_callback_missing_fields_returns_422(self):
        from main import app
        client = TestClient(app)
        resp = client.post("/internal/reminders", json={"taskId": "task-abc"})
        assert resp.status_code == 422

    @patch("app.routes.internal._verify_oidc_token")
    def test_reminder_callback_invalid_token_returns_401(self, mock_verify):
        from main import app
        from fastapi import HTTPException

        mock_verify.side_effect = HTTPException(status_code=401, detail="Invalid OIDC token.")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/internal/reminders", json={
            "taskId": "task-abc",
            "caseId": "ZAD-2026-05-0001",
            "dueAt": "2026-05-22T10:00:00Z",
        })
        assert resp.status_code == 401
