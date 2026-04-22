"""
Unit tests for Task and WorkflowExecution models.

Covers:
  - Default field values (auto UUID, timestamps, status)
  - Firestore serialisation round-trip
  - Enum validation
  - Edge cases (missing optional fields, timezone handling)
"""

import pytest
from datetime import datetime, timezone
from models.task import Task, TaskStatus, TaskType, TaskPriority, CreateTaskRequest, CompleteTaskRequest
from models.workflow import WorkflowExecution, WorkflowType, WorkflowStatus, WORKFLOW_REGISTRY


# ---------------------------------------------------------------------------
# Task model
# ---------------------------------------------------------------------------

class TestTaskModel:

    def test_auto_generates_uuid(self):
        t1 = Task(case_id="case-1", title="Test")
        t2 = Task(case_id="case-1", title="Test")
        assert t1.id != t2.id
        assert len(t1.id) == 36  # UUID format

    def test_default_status_is_pending(self):
        t = Task(case_id="case-1", title="Test")
        assert t.status == TaskStatus.PENDING

    def test_default_priority_is_medium(self):
        t = Task(case_id="case-1", title="Test")
        assert t.priority == TaskPriority.MEDIUM

    def test_default_task_type_is_generic(self):
        t = Task(case_id="case-1", title="Test")
        assert t.task_type == TaskType.GENERIC

    def test_all_task_types_are_valid_enum_values(self):
        for task_type in TaskType:
            t = Task(case_id="case-1", title="Test", task_type=task_type)
            assert t.task_type == task_type

    def test_firestore_serialisation_round_trip(self, sample_task):
        data = sample_task.to_firestore()

        # Dates should be ISO strings
        assert isinstance(data["created_at"], str)
        assert isinstance(data["due_date"], str)
        assert data["completed_at"] is None

        # Round-trip
        restored = Task.from_firestore(sample_task.id, data)
        assert restored.id == sample_task.id
        assert restored.case_id == sample_task.case_id
        assert restored.task_type == sample_task.task_type
        assert restored.priority == sample_task.priority
        assert restored.assigned_to_role == sample_task.assigned_to_role

    def test_firestore_round_trip_preserves_due_date(self, sample_task):
        data = sample_task.to_firestore()
        restored = Task.from_firestore(sample_task.id, data)
        # Microseconds may differ slightly; compare to second
        assert abs((restored.due_date - sample_task.due_date).total_seconds()) < 1

    def test_firestore_round_trip_without_due_date(self):
        t = Task(case_id="case-1", title="No due date task")
        data = t.to_firestore()
        assert data["due_date"] is None
        restored = Task.from_firestore(t.id, data)
        assert restored.due_date is None

    def test_metadata_is_empty_dict_by_default(self):
        t = Task(case_id="case-1", title="Test")
        assert t.metadata == {}

    def test_metadata_can_store_arbitrary_data(self):
        t = Task(
            case_id="case-1",
            title="Test",
            metadata={"vtc_id": "VCF-12345", "score": 82.5, "flags": ["lien"]},
        )
        assert t.metadata["vtc_id"] == "VCF-12345"
        assert t.metadata["score"] == 82.5


class TestCreateTaskRequest:

    def test_valid_request(self):
        req = CreateTaskRequest(case_id="case-1", title="Do something")
        assert req.case_id == "case-1"
        assert req.task_type == TaskType.GENERIC

    def test_invalid_task_type_raises(self):
        with pytest.raises(Exception):
            CreateTaskRequest(case_id="case-1", title="Bad", task_type="not_a_type")


class TestCompleteTaskRequest:

    def test_requires_completed_by(self):
        with pytest.raises(Exception):
            CompleteTaskRequest()  # missing required field

    def test_optional_notes(self):
        req = CompleteTaskRequest(completed_by="user-1")
        assert req.completion_notes is None

    def test_with_notes(self):
        req = CompleteTaskRequest(completed_by="user-1", completion_notes="Reviewed and confirmed.")
        assert req.completion_notes == "Reviewed and confirmed."


# ---------------------------------------------------------------------------
# WorkflowExecution model
# ---------------------------------------------------------------------------

class TestWorkflowExecutionModel:

    def test_auto_generates_uuid(self):
        e1 = WorkflowExecution(case_id="c1", workflow_type=WorkflowType.SETTLEMENT, triggered_by="u1")
        e2 = WorkflowExecution(case_id="c1", workflow_type=WorkflowType.SETTLEMENT, triggered_by="u1")
        assert e1.id != e2.id

    def test_default_status_is_running(self):
        e = WorkflowExecution(case_id="c1", workflow_type=WorkflowType.LEAD_QUALIFICATION, triggered_by="u1")
        assert e.status == WorkflowStatus.RUNNING

    def test_firestore_serialisation_round_trip(self, sample_execution):
        data = sample_execution.to_firestore()
        assert isinstance(data["created_at"], str)
        assert data["completed_at"] is None

        restored = WorkflowExecution.from_firestore(sample_execution.id, data)
        assert restored.id == sample_execution.id
        assert restored.case_id == sample_execution.case_id
        assert restored.workflow_type == sample_execution.workflow_type
        assert restored.status == sample_execution.status
        assert restored.gcp_execution_name == sample_execution.gcp_execution_name

    def test_all_workflow_types_instantiate(self):
        for wf_type in WorkflowType:
            e = WorkflowExecution(case_id="c1", workflow_type=wf_type, triggered_by="u1")
            assert e.workflow_type == wf_type


# ---------------------------------------------------------------------------
# Workflow Registry
# ---------------------------------------------------------------------------

class TestWorkflowRegistry:

    def test_all_workflow_types_are_registered(self):
        for wf_type in WorkflowType:
            assert wf_type in WORKFLOW_REGISTRY, f"{wf_type} missing from WORKFLOW_REGISTRY"

    def test_registry_entries_have_required_fields(self):
        for wf_type, defn in WORKFLOW_REGISTRY.items():
            assert defn.gcp_workflow_id, f"{wf_type} missing gcp_workflow_id"
            assert defn.display_name, f"{wf_type} missing display_name"
            assert defn.description, f"{wf_type} missing description"

    def test_lead_qualification_requires_lead_id(self):
        defn = WORKFLOW_REGISTRY[WorkflowType.LEAD_QUALIFICATION]
        assert "lead_id" in defn.required_arguments

    def test_medical_processing_requires_document_ids(self):
        defn = WORKFLOW_REGISTRY[WorkflowType.MEDICAL_PROCESSING]
        assert "document_ids" in defn.required_arguments

    def test_settlement_requires_award_amount(self):
        defn = WORKFLOW_REGISTRY[WorkflowType.SETTLEMENT]
        assert "award_amount" in defn.required_arguments
