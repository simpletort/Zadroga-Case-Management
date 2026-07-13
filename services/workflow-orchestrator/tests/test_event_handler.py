"""
Unit tests for the internal event handler (Cloud Tasks callbacks + Pub/Sub).

Covers:
  - /internal/reminders  → overdue detection, reminder publishing
  - /internal/deadline-alerts → deadline task creation
  - /internal/pubsub/case-events → auto-trigger logic
"""

import base64
import json
import sys
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from models.task import Task, TaskStatus, TaskType, TaskPriority


@pytest.fixture
def client():
    with (
        patch("google.cloud.firestore.AsyncClient"),
        patch("google.cloud.workflows_v1.WorkflowsAsyncClient"),
        patch("google.cloud.workflows.executions_v1.ExecutionsAsyncClient"),
        patch("google.cloud.tasks_v2.CloudTasksAsyncClient"),
        patch("google.cloud.pubsub_v1.PublisherClient"),
    ):
        for mod in ["main", "api", "api.workflows", "api.tasks",
                    "services", "services.firestore_service",
                    "services.workflow_engine", "services.pubsub_service",
                    "services.cloud_tasks_service", "handlers", "handlers.event_handler"]:
            sys.modules.pop(mod, None)
        from main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


def _pubsub_body(event_type: str, data: dict) -> dict:
    payload = {
        "event_type": event_type,
        "timestamp": datetime.utcnow().isoformat(),
        "source": "test",
        "data": data,
    }
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return {
        "message": {"data": encoded, "messageId": "test-msg-1"},
        "subscription": "projects/test/subscriptions/test-sub",
    }


# ---------------------------------------------------------------------------
# POST /internal/reminders
# ---------------------------------------------------------------------------

class TestReminderHandler:

    def test_pending_task_past_due_becomes_overdue(self, client):
        due = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()
        pending_task = Task(
            id="task-001", case_id="case-abc",
            title="Upload docs", task_type=TaskType.UPLOAD_DOCUMENTS,
            status=TaskStatus.PENDING,
        )
        with (
            patch("handlers.event_handler.FirestoreService") as MockDB,
            patch("handlers.event_handler.PubSubService") as MockPubSub,
        ):
            MockDB.return_value.get_task = AsyncMock(return_value=pending_task)
            MockDB.return_value.save_task = AsyncMock()
            MockPubSub.return_value.publish_task_overdue = MagicMock()

            resp = client.post("/internal/reminders", json={
                "task_id": "task-001",
                "case_id": "case-abc",
                "task_type": "upload_documents",
                "due_date": due,
            })

        assert resp.status_code == 200
        # Task should have been saved with OVERDUE status
        saved_task = MockDB.return_value.save_task.call_args[0][0]
        assert saved_task.status == TaskStatus.OVERDUE

    def test_already_completed_task_is_skipped(self, client):
        due = (datetime.now(tz=timezone.utc) + timedelta(hours=12)).isoformat()
        completed_task = Task(
            id="task-001", case_id="case-abc",
            title="Done", status=TaskStatus.COMPLETED,
        )
        with patch("handlers.event_handler.FirestoreService") as MockDB:
            MockDB.return_value.get_task = AsyncMock(return_value=completed_task)
            resp = client.post("/internal/reminders", json={
                "task_id": "task-001",
                "case_id": "case-abc",
                "task_type": "generic",
                "due_date": due,
            })
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"

    def test_nonexistent_task_is_skipped_gracefully(self, client):
        with patch("handlers.event_handler.FirestoreService") as MockDB:
            MockDB.return_value.get_task = AsyncMock(return_value=None)
            resp = client.post("/internal/reminders", json={
                "task_id": "ghost-task",
                "case_id": "case-abc",
                "task_type": "generic",
                "due_date": datetime.utcnow().isoformat(),
            })
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"


# ---------------------------------------------------------------------------
# POST /internal/deadline-alerts
# ---------------------------------------------------------------------------

class TestDeadlineAlertHandler:

    def test_creates_reminder_task_in_firestore(self, client):
        deadline = (datetime.now(tz=timezone.utc) + timedelta(days=30)).isoformat()
        with (
            patch("handlers.event_handler.FirestoreService") as MockDB,
            patch("handlers.event_handler.PubSubService") as MockPubSub,
        ):
            MockDB.return_value.save_task = AsyncMock()
            MockPubSub.return_value.publish_deadline_approaching = MagicMock()

            resp = client.post("/internal/deadline-alerts", json={
                "case_id": "case-abc",
                "deadline_type": "vcf",
                "deadline": deadline,
                "days_remaining": 30,
            })

        assert resp.status_code == 200
        assert "task_id" in resp.json()
        MockDB.return_value.save_task.assert_awaited_once()

    def test_publishes_deadline_approaching_event(self, client):
        deadline = (datetime.now(tz=timezone.utc) + timedelta(days=14)).isoformat()
        with (
            patch("handlers.event_handler.FirestoreService") as MockDB,
            patch("handlers.event_handler.PubSubService") as MockPubSub,
        ):
            MockDB.return_value.save_task = AsyncMock()
            MockPubSub.return_value.publish_deadline_approaching = MagicMock()

            client.post("/internal/deadline-alerts", json={
                "case_id": "case-abc",
                "deadline_type": "wtc",
                "deadline": deadline,
                "days_remaining": 14,
            })

        MockPubSub.return_value.publish_deadline_approaching.assert_called_once_with(
            case_id="case-abc",
            deadline_type="wtc",
            deadline=deadline,
            days_remaining=14,
        )

    def test_14_day_alert_creates_critical_priority_task(self, client):
        deadline = (datetime.now(tz=timezone.utc) + timedelta(days=14)).isoformat()
        saved_tasks = []
        with (
            patch("handlers.event_handler.FirestoreService") as MockDB,
            patch("handlers.event_handler.PubSubService") as MockPubSub,
        ):
            async def capture_task(t):
                saved_tasks.append(t)
            MockDB.return_value.save_task = capture_task
            MockPubSub.return_value.publish_deadline_approaching = MagicMock()

            client.post("/internal/deadline-alerts", json={
                "case_id": "case-abc",
                "deadline_type": "vcf",
                "deadline": deadline,
                "days_remaining": 14,
            })

        assert len(saved_tasks) == 1
        assert saved_tasks[0].priority == TaskPriority.CRITICAL

    def test_90_day_alert_creates_high_priority_task(self, client):
        deadline = (datetime.now(tz=timezone.utc) + timedelta(days=90)).isoformat()
        saved_tasks = []
        with (
            patch("handlers.event_handler.FirestoreService") as MockDB,
            patch("handlers.event_handler.PubSubService") as MockPubSub,
        ):
            async def capture_task(t):
                saved_tasks.append(t)
            MockDB.return_value.save_task = capture_task
            MockPubSub.return_value.publish_deadline_approaching = MagicMock()

            client.post("/internal/deadline-alerts", json={
                "case_id": "case-abc",
                "deadline_type": "wtc",
                "deadline": deadline,
                "days_remaining": 90,
            })

        assert saved_tasks[0].priority == TaskPriority.HIGH


# ---------------------------------------------------------------------------
# POST /internal/pubsub/case-events
# ---------------------------------------------------------------------------

class TestPubSubCaseEventHandler:

    def test_lead_qualified_triggers_client_onboarding(self, client):
        body = _pubsub_body("lead.qualified", {
            "case_id": "case-abc",
            "client_email": "client@example.com",
        })
        with patch("handlers.event_handler.WorkflowEngine") as MockEngine:
            MockEngine.return_value.trigger = AsyncMock()
            resp = client.post("/internal/pubsub/case-events", json=body)

        assert resp.status_code == 200
        MockEngine.return_value.trigger.assert_awaited_once()
        call_kwargs = MockEngine.return_value.trigger.call_args.kwargs
        assert call_kwargs["workflow_type"] == "client-onboarding"
        assert call_kwargs["case_id"] == "case-abc"

    def test_documents_uploaded_triggers_medical_processing(self, client):
        body = _pubsub_body("documents.uploaded", {
            "case_id": "case-abc",
            "document_ids": ["doc-1", "doc-2"],
        })
        with patch("handlers.event_handler.WorkflowEngine") as MockEngine:
            MockEngine.return_value.trigger = AsyncMock()
            resp = client.post("/internal/pubsub/case-events", json=body)

        assert resp.status_code == 200
        call_kwargs = MockEngine.return_value.trigger.call_args.kwargs
        assert call_kwargs["workflow_type"] == "medical-processing"

    def test_award_letter_received_triggers_settlement(self, client):
        body = _pubsub_body("award_letter.received", {
            "case_id": "case-abc",
            "award_amount": 500000,
        })
        with patch("handlers.event_handler.WorkflowEngine") as MockEngine:
            MockEngine.return_value.trigger = AsyncMock()
            client.post("/internal/pubsub/case-events", json=body)

        call_kwargs = MockEngine.return_value.trigger.call_args.kwargs
        assert call_kwargs["workflow_type"] == "settlement"
        assert call_kwargs["arguments"]["award_amount"] == 500000

    def test_unknown_event_type_returns_200_and_ignores(self, client):
        """Unknown events should be silently ignored, not cause errors."""
        body = _pubsub_body("some.unknown.event", {"case_id": "case-abc"})
        with patch("handlers.event_handler.WorkflowEngine") as MockEngine:
            MockEngine.return_value.trigger = AsyncMock()
            resp = client.post("/internal/pubsub/case-events", json=body)
        assert resp.status_code == 200
        MockEngine.return_value.trigger.assert_not_awaited()

    def test_malformed_pubsub_message_returns_200(self, client):
        """Malformed messages return 200 to prevent Pub/Sub from redelivering."""
        resp = client.post("/internal/pubsub/case-events", json={"bad": "payload"})
        assert resp.status_code == 200
