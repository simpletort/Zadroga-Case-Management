"""
Unit tests for the API layer.

Uses FastAPI's TestClient with all GCP dependencies mocked.
Tests cover routing, request validation, response shapes, and error handling.
"""

import importlib
import sys
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from models.task import Task, TaskStatus, TaskType, TaskPriority
from models.workflow import WorkflowExecution, WorkflowType, WorkflowStatus, WORKFLOW_REGISTRY


# ---------------------------------------------------------------------------
# App fixture — patch GCP clients before importing main
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """
    TestClient with all GCP service constructors patched so the app
    starts without real credentials.
    """
    with (
        patch("google.cloud.firestore.AsyncClient"),
        patch("google.cloud.workflows_v1.WorkflowsAsyncClient"),
        patch("google.cloud.workflows.executions_v1.ExecutionsAsyncClient"),
        patch("google.cloud.tasks_v2.CloudTasksAsyncClient"),
        patch("google.cloud.pubsub_v1.PublisherClient"),
    ):
        # Force reload so each test gets a fresh app with patches active
        for mod in ["main", "api", "api.workflows", "api.tasks",
                    "services", "services.firestore_service",
                    "services.workflow_engine", "services.pubsub_service",
                    "services.cloud_tasks_service", "handlers", "handlers.event_handler"]:
            sys.modules.pop(mod, None)
        from main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["service"] == "workflow-orchestrator"


# ---------------------------------------------------------------------------
# GET /api/v1/workflows/definitions
# ---------------------------------------------------------------------------

class TestWorkflowDefinitions:
    def test_returns_all_registered_workflows(self, client):
        resp = client.get("/api/v1/workflows/definitions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == len(WORKFLOW_REGISTRY)

    def test_each_definition_has_required_fields(self, client):
        resp = client.get("/api/v1/workflows/definitions")
        for defn in resp.json():
            assert "workflow_type" in defn
            assert "display_name" in defn
            assert "gcp_workflow_id" in defn
            assert "description" in defn


# ---------------------------------------------------------------------------
# POST /api/v1/workflows/trigger
# ---------------------------------------------------------------------------

class TestTriggerWorkflow:

    def _make_engine_mock(self, execution: WorkflowExecution):
        mock_engine = MagicMock()
        mock_engine.trigger = AsyncMock(return_value=execution)
        return mock_engine

    def test_trigger_lead_qualification_returns_202(self, client, sample_execution):
        sample_execution.workflow_type = WorkflowType.LEAD_QUALIFICATION
        with patch("api.workflows.WorkflowEngine") as MockEngine:
            MockEngine.return_value = self._make_engine_mock(sample_execution)
            resp = client.post("/api/v1/workflows/trigger", json={
                "case_id": "case-abc",
                "workflow_type": "lead-qualification",
                "triggered_by": "user-1",
                "arguments": {"lead_id": "lead-xyz"},
            })
        assert resp.status_code == 202

    def test_trigger_returns_execution_record(self, client, sample_execution):
        with patch("api.workflows.WorkflowEngine") as MockEngine:
            MockEngine.return_value = self._make_engine_mock(sample_execution)
            resp = client.post("/api/v1/workflows/trigger", json={
                "case_id": "case-abc",
                "workflow_type": "client-onboarding",
                "triggered_by": "user-1",
                "arguments": {"client_email": "test@example.com"},
            })
        data = resp.json()
        assert data["id"] == sample_execution.id
        assert data["case_id"] == "case-abc"

    def test_unknown_workflow_type_returns_400(self, client):
        resp = client.post("/api/v1/workflows/trigger", json={
            "case_id": "case-abc",
            "workflow_type": "not-a-real-workflow",
            "triggered_by": "user-1",
            "arguments": {},
        })
        assert resp.status_code == 422  # Pydantic enum validation

    def test_missing_required_argument_returns_422(self, client, sample_execution):
        # medical-processing requires document_ids
        with patch("api.workflows.WorkflowEngine") as MockEngine:
            MockEngine.return_value = self._make_engine_mock(sample_execution)
            resp = client.post("/api/v1/workflows/trigger", json={
                "case_id": "case-abc",
                "workflow_type": "medical-processing",
                "triggered_by": "user-1",
                "arguments": {},  # missing document_ids
            })
        assert resp.status_code == 422

    def test_missing_case_id_returns_422(self, client):
        resp = client.post("/api/v1/workflows/trigger", json={
            "workflow_type": "client-onboarding",
            "triggered_by": "user-1",
        })
        assert resp.status_code == 422

    def test_engine_failure_returns_500(self, client):
        with patch("api.workflows.WorkflowEngine") as MockEngine:
            mock_engine = MagicMock()
            mock_engine.trigger = AsyncMock(side_effect=Exception("GCP unavailable"))
            MockEngine.return_value = mock_engine
            resp = client.post("/api/v1/workflows/trigger", json={
                "case_id": "case-abc",
                "workflow_type": "client-onboarding",
                "triggered_by": "user-1",
                "arguments": {"client_email": "a@b.com"},
            })
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/v1/tasks/active
# ---------------------------------------------------------------------------

class TestGetActiveTasks:

    def test_returns_list(self, client, sample_task):
        with patch("api.tasks.FirestoreService") as MockDB:
            MockDB.return_value.list_active_tasks = AsyncMock(return_value=[sample_task])
            resp = client.get("/api/v1/tasks/active")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) == 1

    def test_returns_empty_list_when_no_tasks(self, client):
        with patch("api.tasks.FirestoreService") as MockDB:
            MockDB.return_value.list_active_tasks = AsyncMock(return_value=[])
            resp = client.get("/api/v1/tasks/active")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_filter_by_role_passes_to_service(self, client):
        with patch("api.tasks.FirestoreService") as MockDB:
            MockDB.return_value.list_active_tasks = AsyncMock(return_value=[])
            resp = client.get("/api/v1/tasks/active?assigned_to_role=paralegal")
        assert resp.status_code == 200
        MockDB.return_value.list_active_tasks.assert_awaited_once_with(
            assigned_to=None,
            assigned_to_role="paralegal",
            case_id=None,
            limit=50,
        )

    def test_limit_cap_at_200(self, client):
        with patch("api.tasks.FirestoreService") as MockDB:
            MockDB.return_value.list_active_tasks = AsyncMock(return_value=[])
            resp = client.get("/api/v1/tasks/active?limit=500")
        # FastAPI should reject limit > 200
        assert resp.status_code == 422

    def test_task_fields_in_response(self, client, sample_task):
        with patch("api.tasks.FirestoreService") as MockDB:
            MockDB.return_value.list_active_tasks = AsyncMock(return_value=[sample_task])
            resp = client.get("/api/v1/tasks/active")
        task_data = resp.json()[0]
        assert task_data["id"] == sample_task.id
        assert task_data["case_id"] == sample_task.case_id
        assert task_data["status"] == TaskStatus.PENDING.value
        assert task_data["task_type"] == TaskType.REVIEW_MEDICAL_SUMMARY.value


# ---------------------------------------------------------------------------
# PUT /api/v1/tasks/{task_id}/complete
# ---------------------------------------------------------------------------

class TestCompleteTask:

    def test_completes_pending_task(self, client, sample_task):
        with (
            patch("api.tasks.FirestoreService") as MockDB,
        ):
            MockDB.return_value.get_task_by_id = AsyncMock(return_value=sample_task)
            MockDB.return_value.save_task = AsyncMock()
            resp = client.put(
                f"/api/v1/tasks/{sample_task.id}/complete",
                json={"completed_by": "paralegal-user-1", "completion_notes": "Done."},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == TaskStatus.COMPLETED.value
        assert data["completed_by"] == "paralegal-user-1"
        assert data["completion_notes"] == "Done."

    def test_completing_already_completed_task_returns_409(self, client, completed_task):
        with patch("api.tasks.FirestoreService") as MockDB:
            MockDB.return_value.get_task_by_id = AsyncMock(return_value=completed_task)
            resp = client.put(
                f"/api/v1/tasks/{completed_task.id}/complete",
                json={"completed_by": "someone"},
            )
        assert resp.status_code == 409

    def test_completing_nonexistent_task_returns_404(self, client):
        with patch("api.tasks.FirestoreService") as MockDB:
            MockDB.return_value.get_task_by_id = AsyncMock(return_value=None)
            resp = client.put(
                "/api/v1/tasks/does-not-exist/complete",
                json={"completed_by": "user-1"},
            )
        assert resp.status_code == 404

    def test_missing_completed_by_returns_422(self, client):
        resp = client.put(
            "/api/v1/tasks/task-001/complete",
            json={"completion_notes": "forgot who did it"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/cases/{case_id}/tasks
# ---------------------------------------------------------------------------

class TestGetCaseTasks:

    def test_returns_tasks_for_case(self, client, sample_task):
        with patch("api.tasks.FirestoreService") as MockDB:
            MockDB.return_value.list_case_tasks = AsyncMock(return_value=[sample_task])
            resp = client.get("/api/v1/cases/case-abc/tasks")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["case_id"] == "case-abc"

    def test_status_filter_is_passed_through(self, client):
        with patch("api.tasks.FirestoreService") as MockDB:
            MockDB.return_value.list_case_tasks = AsyncMock(return_value=[])
            resp = client.get("/api/v1/cases/case-abc/tasks?status=completed")
        assert resp.status_code == 200
        MockDB.return_value.list_case_tasks.assert_awaited_once_with(
            case_id="case-abc",
            status_filter=TaskStatus.COMPLETED,
        )


# ---------------------------------------------------------------------------
# POST /api/v1/tasks (manual task creation)
# ---------------------------------------------------------------------------

class TestCreateTask:

    def test_creates_task_without_due_date(self, client):
        with (
            patch("api.tasks.FirestoreService") as MockDB,
            patch("api.tasks.CloudTasksService") as MockCT,
        ):
            MockDB.return_value.save_task = AsyncMock()
            MockCT.return_value.schedule_deadline_reminder = AsyncMock()
            resp = client.post("/api/v1/tasks", json={
                "case_id": "case-abc",
                "title": "Manual task",
                "task_type": "generic",
            })
        assert resp.status_code == 201
        # No due_date → scheduler should NOT have been called
        MockCT.return_value.schedule_deadline_reminder.assert_not_awaited()

    def test_creates_task_with_due_date_schedules_reminder(self, client):
        future = (datetime.now(tz=timezone.utc) + timedelta(days=3)).isoformat()
        with (
            patch("api.tasks.FirestoreService") as MockDB,
            patch("api.tasks.CloudTasksService") as MockCT,
        ):
            MockDB.return_value.save_task = AsyncMock()
            MockCT.return_value.schedule_deadline_reminder = AsyncMock(return_value="ct-task-name")
            resp = client.post("/api/v1/tasks", json={
                "case_id": "case-abc",
                "title": "Deadline task",
                "due_date": future,
            })
        assert resp.status_code == 201
        MockCT.return_value.schedule_deadline_reminder.assert_awaited_once()
