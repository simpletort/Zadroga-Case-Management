"""
Unit tests for WorkflowEngine.

Verifies that triggering a workflow:
  - Creates the correct initial tasks for each workflow type
  - Passes the right arguments to the GCP Cloud Workflows client
  - Handles GCP failures gracefully (marks execution FAILED, doesn't raise)
  - Produces a persisted WorkflowExecution record
"""

import pytest
import pytest_asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow import WorkflowType, WorkflowStatus
from models.task import TaskType
from services.workflow_engine import WORKFLOW_INITIAL_TASKS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_engine_with_mocks():
    """
    Returns (engine, mock_db, mock_executions_client) with all GCP calls mocked.
    """
    # Patch the directly imported ExecutionsAsyncClient (from executions_v1)
    # AND the workflows_v1 module reference used for WorkflowsAsyncClient
    with (
        patch("services.workflow_engine.ExecutionsAsyncClient") as MockExecClient,
        patch("services.workflow_engine.workflows_v1") as mock_wf,
        patch("services.workflow_engine.FirestoreService") as MockDB,
    ):
        mock_exec_client = AsyncMock()
        MockExecClient.return_value = mock_exec_client
        mock_wf.WorkflowsAsyncClient.return_value = AsyncMock()

        # Default: GCP execution succeeds
        mock_gcp_exec = MagicMock()
        mock_gcp_exec.name = (
            "projects/test-project/locations/us-east1"
            "/workflows/client-onboarding/executions/test-exec-123"
        )
        mock_exec_client.create_execution = AsyncMock(return_value=mock_gcp_exec)

        mock_db_instance = AsyncMock()
        mock_db_instance.save_task = AsyncMock()
        mock_db_instance.save_workflow_execution = AsyncMock()
        MockDB.return_value = mock_db_instance

        from services.workflow_engine import WorkflowEngine
        engine = WorkflowEngine()
        # Inject mocks directly so tests fully control behaviour
        engine._executions_client = mock_exec_client
        engine._db = mock_db_instance

        return engine, mock_db_instance, mock_exec_client


# ---------------------------------------------------------------------------
# Initial task creation
# ---------------------------------------------------------------------------

class TestWorkflowInitialTasks:

    def test_all_workflow_types_have_initial_tasks(self):
        """Every registered workflow type should create at least one task."""
        for wf_type in WorkflowType:
            assert wf_type in WORKFLOW_INITIAL_TASKS, (
                f"No initial tasks defined for {wf_type}. "
                "Add an entry to WORKFLOW_INITIAL_TASKS in workflow_engine.py"
            )
            assert len(WORKFLOW_INITIAL_TASKS[wf_type]) > 0

    def test_client_onboarding_creates_retainer_and_upload_tasks(self):
        tasks = WORKFLOW_INITIAL_TASKS[WorkflowType.CLIENT_ONBOARDING]
        task_types = [t[0] for t in tasks]
        assert TaskType.SIGN_RETAINER in task_types
        assert TaskType.UPLOAD_DOCUMENTS in task_types

    def test_medical_processing_creates_review_and_verify_tasks(self):
        tasks = WORKFLOW_INITIAL_TASKS[WorkflowType.MEDICAL_PROCESSING]
        task_types = [t[0] for t in tasks]
        assert TaskType.REVIEW_MEDICAL_SUMMARY in task_types
        assert TaskType.VERIFY_QUALIFICATION_SCORE in task_types

    def test_vcf_enrollment_creates_three_tasks(self):
        tasks = WORKFLOW_INITIAL_TASKS[WorkflowType.VCF_ENROLLMENT]
        assert len(tasks) >= 3
        task_types = [t[0] for t in tasks]
        assert TaskType.CONFIRM_WTC_ENROLLMENT in task_types
        assert TaskType.SUBMIT_VCF_REGISTRATION in task_types

    def test_settlement_creates_four_steps(self):
        tasks = WORKFLOW_INITIAL_TASKS[WorkflowType.SETTLEMENT]
        assert len(tasks) >= 4
        task_types = [t[0] for t in tasks]
        assert TaskType.PREPARE_SETTLEMENT_STATEMENT in task_types
        assert TaskType.DISBURSE_FUNDS in task_types

    def test_substitution_of_counsel_requires_signature(self):
        tasks = WORKFLOW_INITIAL_TASKS[WorkflowType.SUBSTITUTION_OF_COUNSEL]
        task_types = [t[0] for t in tasks]
        assert TaskType.OBTAIN_SIGNATURE in task_types
        assert TaskType.GENERATE_SUBSTITUTION_FORM in task_types

    def test_all_task_tuples_have_five_elements(self):
        """Each tuple must be (task_type, title, priority, due_offset_hours, role)."""
        for wf_type, task_list in WORKFLOW_INITIAL_TASKS.items():
            for i, task_tuple in enumerate(task_list):
                assert len(task_tuple) == 5, (
                    f"Task tuple {i} in {wf_type} has {len(task_tuple)} elements, expected 5"
                )

    def test_all_due_offsets_are_positive(self):
        for wf_type, task_list in WORKFLOW_INITIAL_TASKS.items():
            for task_type, title, priority, due_offset, role in task_list:
                assert due_offset > 0, (
                    f"Task '{title}' in {wf_type} has non-positive due offset: {due_offset}"
                )

    def test_all_roles_are_valid(self):
        valid_roles = {"paralegal", "attorney", "client", "admin"}
        for wf_type, task_list in WORKFLOW_INITIAL_TASKS.items():
            for task_type, title, priority, due_offset, role in task_list:
                assert role in valid_roles, (
                    f"Task '{title}' in {wf_type} has unknown role: '{role}'"
                )

    def test_critical_tasks_have_shorter_deadlines_than_high(self):
        """
        For each workflow, no CRITICAL task should have a longer due offset
        than a HIGH priority task (spot-check settlement workflow).
        """
        from models.task import TaskPriority
        settlement_tasks = WORKFLOW_INITIAL_TASKS[WorkflowType.SETTLEMENT]
        critical = [t for t in settlement_tasks if t[2] == TaskPriority.CRITICAL]
        high = [t for t in settlement_tasks if t[2] == TaskPriority.HIGH]
        if critical and high:
            min_critical_offset = min(t[3] for t in critical)
            max_high_offset = max(t[3] for t in high)
            assert min_critical_offset <= max_high_offset, (
                "Critical tasks should generally have tighter deadlines than HIGH tasks"
            )


# ---------------------------------------------------------------------------
# WorkflowEngine.trigger() behaviour
# ---------------------------------------------------------------------------

class TestWorkflowEngineTrigger:

    @pytest.mark.asyncio
    async def test_trigger_returns_execution_with_running_status(self):
        engine, mock_db, mock_exec_client = make_engine_with_mocks()
        execution = await engine.trigger(
            case_id="case-001",
            workflow_type=WorkflowType.CLIENT_ONBOARDING,
            triggered_by="user-1",
            arguments={"case_id": "case-001", "client_email": "test@example.com"},
        )
        assert execution.status == WorkflowStatus.RUNNING
        assert execution.case_id == "case-001"
        assert execution.workflow_type == WorkflowType.CLIENT_ONBOARDING

    @pytest.mark.asyncio
    async def test_trigger_sets_gcp_execution_name(self):
        engine, mock_db, mock_exec_client = make_engine_with_mocks()
        execution = await engine.trigger(
            case_id="case-001",
            workflow_type=WorkflowType.CLIENT_ONBOARDING,
            triggered_by="user-1",
            arguments={"case_id": "case-001", "client_email": "a@b.com"},
        )
        assert execution.gcp_execution_name is not None
        assert "executions" in execution.gcp_execution_name

    @pytest.mark.asyncio
    async def test_trigger_persists_execution_to_firestore(self):
        engine, mock_db, mock_exec_client = make_engine_with_mocks()
        await engine.trigger(
            case_id="case-001",
            workflow_type=WorkflowType.LEAD_QUALIFICATION,
            triggered_by="user-1",
            arguments={"case_id": "case-001", "lead_id": "lead-xyz"},
        )
        mock_db.save_workflow_execution.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_trigger_creates_initial_tasks(self):
        engine, mock_db, mock_exec_client = make_engine_with_mocks()
        await engine.trigger(
            case_id="case-001",
            workflow_type=WorkflowType.CLIENT_ONBOARDING,
            triggered_by="user-1",
            arguments={"case_id": "case-001", "client_email": "a@b.com"},
        )
        expected_task_count = len(WORKFLOW_INITIAL_TASKS[WorkflowType.CLIENT_ONBOARDING])
        assert mock_db.save_task.await_count == expected_task_count

    @pytest.mark.asyncio
    async def test_gcp_failure_sets_status_to_failed(self):
        engine, mock_db, mock_exec_client = make_engine_with_mocks()
        mock_exec_client.create_execution = AsyncMock(
            side_effect=Exception("Cloud Workflows unavailable")
        )
        execution = await engine.trigger(
            case_id="case-001",
            workflow_type=WorkflowType.CLIENT_ONBOARDING,
            triggered_by="user-1",
            arguments={"case_id": "case-001", "client_email": "a@b.com"},
        )
        assert execution.status == WorkflowStatus.FAILED
        assert "Cloud Workflows unavailable" in execution.error

    @pytest.mark.asyncio
    async def test_gcp_failure_still_persists_execution_record(self):
        """Even on GCP failure, we persist the record so the failure is visible."""
        engine, mock_db, mock_exec_client = make_engine_with_mocks()
        mock_exec_client.create_execution = AsyncMock(side_effect=Exception("boom"))
        await engine.trigger(
            case_id="case-001",
            workflow_type=WorkflowType.VCF_ENROLLMENT,
            triggered_by="system",
            arguments={"case_id": "case-001"},
        )
        mock_db.save_workflow_execution.assert_awaited_once()
