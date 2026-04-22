"""
Shared pytest fixtures for the Workflow Orchestrator test suite.

GCP clients are fully mocked — no real credentials or project needed.
Set the required env vars via the monkeypatch fixture or os.environ before
importing config-dependent modules.
"""

import os
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Force config env vars before any app module is imported
# ---------------------------------------------------------------------------
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("CLOUD_TASKS_SERVICE_URL", "https://test-service.run.app")
os.environ.setdefault("SERVICE_ACCOUNT_EMAIL", "test@test-project.iam.gserviceaccount.com")

from models.task import Task, TaskStatus, TaskType, TaskPriority
from models.workflow import WorkflowExecution, WorkflowType, WorkflowStatus


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_task() -> Task:
    return Task(
        id="task-001",
        case_id="case-abc",
        title="Review medical summary",
        task_type=TaskType.REVIEW_MEDICAL_SUMMARY,
        priority=TaskPriority.HIGH,
        assigned_to_role="paralegal",
        due_date=datetime.now(tz=timezone.utc) + timedelta(hours=24),
    )


@pytest.fixture
def overdue_task() -> Task:
    return Task(
        id="task-overdue",
        case_id="case-abc",
        title="Upload documents",
        task_type=TaskType.UPLOAD_DOCUMENTS,
        status=TaskStatus.PENDING,
        priority=TaskPriority.CRITICAL,
        assigned_to_role="client",
        due_date=datetime.now(tz=timezone.utc) - timedelta(hours=2),
    )


@pytest.fixture
def completed_task(sample_task) -> Task:
    t = sample_task.model_copy()
    t.status = TaskStatus.COMPLETED
    t.completed_at = datetime.utcnow()
    t.completed_by = "user-paralegal-1"
    return t


@pytest.fixture
def sample_execution() -> WorkflowExecution:
    return WorkflowExecution(
        id="exec-001",
        case_id="case-abc",
        workflow_type=WorkflowType.CLIENT_ONBOARDING,
        triggered_by="user-attorney-1",
        gcp_execution_name=(
            "projects/test-project/locations/us-east1"
            "/workflows/client-onboarding/executions/abc123"
        ),
        status=WorkflowStatus.RUNNING,
    )


# ---------------------------------------------------------------------------
# Mock GCP service fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_firestore():
    """Returns a fully mocked FirestoreService."""
    with patch("services.firestore_service.firestore") as mock_fs:
        mock_client = AsyncMock()
        mock_fs.AsyncClient.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_workflows_client():
    with patch("services.workflow_engine.workflows_v1") as mock_wf:
        yield mock_wf


@pytest.fixture
def mock_cloud_tasks_client():
    with patch("services.cloud_tasks_service.tasks_v2") as mock_ct:
        yield mock_ct


@pytest.fixture
def mock_pubsub_publisher():
    with patch("services.pubsub_service.pubsub_v1") as mock_ps:
        mock_publisher = MagicMock()
        mock_future = MagicMock()
        mock_future.result.return_value = "message-id-123"
        mock_publisher.PublisherClient.return_value.publish.return_value = mock_future
        mock_ps.PublisherClient = mock_publisher.PublisherClient
        yield mock_publisher
