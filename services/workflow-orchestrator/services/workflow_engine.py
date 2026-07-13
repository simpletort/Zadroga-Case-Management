"""
WorkflowEngine — bridges this service with GCP Cloud Workflows.

Responsibilities:
  1. Execute a Cloud Workflows execution for the given workflow type.
  2. Persist the WorkflowExecution record to Firestore.
  3. Sync execution status back from GCP on demand.
  4. Create the initial batch of Tasks for a workflow.
"""

from __future__ import annotations

import json
import structlog
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from google.cloud import workflows_v1
from google.cloud.workflows.executions_v1 import ExecutionsAsyncClient, Execution

from config import settings
from models import WorkflowExecution, WorkflowStatus, WorkflowType, Task, TaskType, TaskPriority
from models.workflow import WORKFLOW_REGISTRY, WorkflowDefinitionConfig
from services.firestore_service import FirestoreService

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Module-level TTL cache for workflow definitions
# ---------------------------------------------------------------------------
# Avoids a Firestore round-trip on every trigger() call. Admin API writes
# call _invalidate_cache() to clear the entry immediately after updating.

@dataclass
class _CacheEntry:
    definition: WorkflowDefinitionConfig
    fetched_at: datetime

_definition_cache: dict[str, _CacheEntry] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


async def _get_definition(
    workflow_id: str, db: FirestoreService
) -> Optional[WorkflowDefinitionConfig]:
    """
    Return a WorkflowDefinitionConfig from the TTL cache or Firestore.
    Used by WorkflowEngine and the config_handler internal endpoint.
    """
    entry = _definition_cache.get(workflow_id)
    if entry and (datetime.utcnow() - entry.fetched_at).seconds < _CACHE_TTL_SECONDS:
        return entry.definition
    defn = await db.get_workflow_definition(workflow_id)
    if defn:
        _definition_cache[workflow_id] = _CacheEntry(
            definition=defn, fetched_at=datetime.utcnow()
        )
    return defn


def _invalidate_cache(workflow_id: str) -> None:
    """Remove a workflow definition from the cache (called after admin writes)."""
    _definition_cache.pop(workflow_id, None)


# ---------------------------------------------------------------------------
# Initial task templates per workflow type
# ---------------------------------------------------------------------------
# Format: (TaskType, title, TaskPriority, due_offset_hours, assigned_to_role)
# - due_offset_hours is relative to trigger time (now), not a fixed deadline
# - assigned_to_role auto-assigns to staff matching this role; use assigned_to for specific staff
#
# HOW TO EDIT:
#   - Add step: insert new tuple in the workflow's list
#   - Change deadline: modify due_offset_hours (in hours)
#   - Change owner: update assigned_to_role to "paralegal" | "attorney" | "client"
#   - Remove step: delete the tuple line
#   - Add new workflow: add new WorkflowType entry with task list to this dict
# ---------------------------------------------------------------------------

WORKFLOW_INITIAL_TASKS: dict[WorkflowType, list[tuple]] = {
    WorkflowType.LEAD_QUALIFICATION: [
        # Paralegal must complete eligibility intake before any onboarding
        (TaskType.COMPLETE_QUESTIONNAIRE, "Complete lead qualification questionnaire",
         TaskPriority.HIGH, 24, "paralegal"),
    ],
    WorkflowType.CLIENT_ONBOARDING: [
        # CRITICAL: retainer must be signed before we can proceed with the case
        (TaskType.SIGN_RETAINER, "Sign retainer agreement (DocuSign)",
         TaskPriority.CRITICAL, 48, "client"),
        # Client docs are needed for medical review and VCF processing
        (TaskType.UPLOAD_DOCUMENTS, "Upload required identification documents",
         TaskPriority.HIGH, 72, "client"),
    ],
    WorkflowType.MEDICAL_PROCESSING: [
        # Paralegal QA-checks the AI summary before attorney sign-off
        (TaskType.REVIEW_MEDICAL_SUMMARY, "Review AI-generated medical summary",
         TaskPriority.HIGH, 24, "paralegal"),
        # Attorney final decision: is the client actually eligible for VCF/WTC?
        (TaskType.VERIFY_QUALIFICATION_SCORE, "Verify AI qualification score",
         TaskPriority.HIGH, 48, "attorney"),
    ],
    WorkflowType.VCF_ENROLLMENT: [
        # Must confirm WTC coverage is active before submitting to VCF (blocks claim eligibility)
        (TaskType.CONFIRM_WTC_ENROLLMENT, "Confirm WTC Health Program enrollment",
         TaskPriority.CRITICAL, 72, "paralegal"),
        # VCF registration is time-sensitive; don't miss the deadline
        (TaskType.SUBMIT_VCF_REGISTRATION, "Submit VCF registration",
         TaskPriority.CRITICAL, 168, "paralegal"),  # 7 days
        # Trigger deadline check system to send reminder tasks at key milestones (90/60/30/14/7 days)
        (TaskType.CHECK_ENROLLMENT_DEADLINE, "Check and set enrollment deadline alerts",
         TaskPriority.HIGH, 24, "paralegal"),
    ],
    WorkflowType.SUBSTITUTION_OF_COUNSEL: [
        # Generate the formal court substitution form before requesting signatures
        (TaskType.GENERATE_SUBSTITUTION_FORM, "Generate substitution of counsel form",
         TaskPriority.HIGH, 24, "paralegal"),
        # Request prior files in parallel; may take time to retrieve
        (TaskType.REQUEST_PRIOR_FILES, "Request case files from prior attorney",
         TaskPriority.HIGH, 72, "paralegal"),
        # Client signature is CRITICAL for court filing; cannot proceed without it
        (TaskType.OBTAIN_SIGNATURE, "Obtain client signature via DocuSign",
         TaskPriority.CRITICAL, 48, "client"),
    ],
    WorkflowType.CLAIM_SUBMISSION: [
        # Attorney final QA: is the package complete and compliant before submission?
        (TaskType.REVIEW_CASE_FILE, "Final review of claim package",
         TaskPriority.CRITICAL, 24, "attorney"),
        # Don't submit without attorney approval; paralegal handles the actual submission
        (TaskType.SUBMIT_VCF_CLAIM, "Submit VCF claim",
         TaskPriority.CRITICAL, 48, "paralegal"),
    ],
    WorkflowType.SETTLEMENT: [
        # Paralegal calculates settlement amounts and drafts statement
        (TaskType.PREPARE_SETTLEMENT_STATEMENT, "Prepare settlement statement",
         TaskPriority.HIGH, 48, "paralegal"),
        # Attorney must approve terms before client signature (fiduciary duty)
        (TaskType.ATTORNEY_APPROVAL, "Attorney approval of settlement terms",
         TaskPriority.CRITICAL, 72, "attorney"),
        # Client signs after attorney sign-off; no signature = no valid settlement
        (TaskType.OBTAIN_SIGNATURE, "Client signature on settlement agreement",
         TaskPriority.CRITICAL, 96, "client"),
        # Final step: disburse after all approvals and signatures collected
        (TaskType.DISBURSE_FUNDS, "Disburse funds via QuickBooks",
         TaskPriority.HIGH, 120, "paralegal"),
    ],
}


class WorkflowEngine:
    def __init__(self):
        # _workflows_client: manages Cloud Workflows definitions (read-only in this service)
        self._workflows_client = workflows_v1.WorkflowsAsyncClient()
        # _executions_client: manages execution lifecycle (create, get status, cancel)
        self._executions_client = ExecutionsAsyncClient()
        # _db: only Firestore access point; all persistence goes through here
        self._db = FirestoreService()

    def _workflow_parent(self, workflow_id: str) -> str:
        # GCP resource name format: projects/{project}/locations/{region}/workflows/{id}
        # Used for gcloud Workflows API calls to identify which workflow to execute
        return (
            f"projects/{settings.gcp_project_id}"
            f"/locations/{settings.workflows_location}"
            f"/workflows/{workflow_id}"
        )

    async def trigger(
        self,
        case_id: str,
        workflow_type: str,
        triggered_by: str,
        arguments: dict[str, Any],
    ) -> WorkflowExecution:
        # Resolve definition from Firestore (via TTL cache).
        # Falls back to WORKFLOW_REGISTRY for backward compatibility during migration.
        defn = await _get_definition(str(workflow_type), self._db)
        if defn:
            gcp_workflow_id = defn.gcp_workflow_id
        else:
            # Fallback: use WORKFLOW_REGISTRY for known WorkflowType enum values
            registry_entry = WORKFLOW_REGISTRY.get(workflow_type)  # type: ignore[arg-type]
            if not registry_entry:
                raise ValueError(f"Unknown workflow type: {workflow_type}")
            gcp_workflow_id = registry_entry.gcp_workflow_id

        execution_record = WorkflowExecution(
            case_id=case_id,
            workflow_type=workflow_type,
            triggered_by=triggered_by,
            arguments=arguments,
            status=WorkflowStatus.RUNNING,
        )

        # STEP 1: Launch GCP Cloud Workflow execution
        try:
            gcp_execution = await self._executions_client.create_execution(
                parent=self._workflow_parent(gcp_workflow_id),
                execution=Execution(
                    argument=json.dumps(arguments),
                    call_log_level=Execution.CallLogLevel.LOG_ERRORS_ONLY,
                ),
            )
            execution_record.gcp_execution_name = gcp_execution.name
            log.info(
                "gcp_workflow_execution_created",
                gcp_execution_name=gcp_execution.name,
                case_id=case_id,
                workflow_type=workflow_type,
            )
        except Exception as exc:
            # Catch errors but don't raise: record the failure in Firestore so we have audit trail.
            # Caller will see status=FAILED in the returned execution_record.
            log.error("gcp_workflow_execution_failed", error=str(exc),
                      case_id=case_id, workflow_type=workflow_type)
            execution_record.status = WorkflowStatus.FAILED
            execution_record.error = str(exc)

        # STEP 2: Persist execution record to Firestore (before or after GCP failure).
        # Done early so we have a record even if subsequent steps fail.
        await self._db.save_workflow_execution(execution_record)

        # STEP 3: Create initial tasks for this workflow (linked to execution via execution_id).
        # These show up on the paralegal dashboard and drive the case forward.
        await self._create_initial_tasks(
            case_id=case_id,
            workflow_type=workflow_type,
            execution_id=execution_record.id,
        )

        return execution_record

    async def _create_initial_tasks(
        self,
        case_id: str,
        workflow_type: str,
        execution_id: str,
    ) -> None:
        now = datetime.now(tz=timezone.utc)

        # Try Firestore-based task templates first (new configurable path)
        defn = await _get_definition(str(workflow_type), self._db)
        if defn and defn.task_templates:
            for template in sorted(defn.task_templates, key=lambda t: t.order):
                task = Task(
                    case_id=case_id,
                    workflow_execution_id=execution_id,
                    title=template.title,
                    task_type=template.task_type,
                    priority=template.priority,
                    assigned_to_role=template.assigned_to_role,
                    # due_offset_days × 24 converts days → hours for timedelta
                    due_date=now + timedelta(hours=template.due_offset_days * 24),
                )
                await self._db.save_task(task)
                log.debug("initial_task_created", task_id=task.id,
                          task_type=template.task_type, case_id=case_id)
            return

        # Fallback: use hardcoded WORKFLOW_INITIAL_TASKS for backward compatibility
        # (used when Firestore definitions haven't been seeded yet)
        task_templates = WORKFLOW_INITIAL_TASKS.get(workflow_type, [])  # type: ignore[arg-type]
        for task_type, title, priority, due_offset_hours, role in task_templates:
            task = Task(
                case_id=case_id,
                # workflow_execution_id links this task to its execution; used to track progress.
                # Allows queries like "show me all tasks for execution X" and "did execution Y complete?"
                workflow_execution_id=execution_id,
                title=title,
                task_type=task_type,
                priority=priority,
                assigned_to_role=role,
                # due_date is relative to NOW (when trigger() was called), not a fixed date.
                # This ensures 24-hour deadlines are truly 24 hours from now, not from a reference point.
                due_date=now + timedelta(hours=due_offset_hours),
            )
            await self._db.save_task(task)
            log.debug("initial_task_created", task_id=task.id,
                      task_type=task_type, case_id=case_id)

    async def sync_execution_status(
        self,
        execution: WorkflowExecution,
    ) -> WorkflowExecution:
        """Pull current status from GCP and update Firestore."""
        try:
            gcp_exec = await self._executions_client.get_execution(
                name=execution.gcp_execution_name
            )
            # state_map translates GCP Execution.State enum to our WorkflowStatus enum.
            # Covers ACTIVE→RUNNING, terminal states, plus default to RUNNING for unknown states.
            state_map = {
                Execution.State.ACTIVE: WorkflowStatus.RUNNING,
                Execution.State.SUCCEEDED: WorkflowStatus.SUCCEEDED,
                Execution.State.FAILED: WorkflowStatus.FAILED,
                Execution.State.CANCELLED: WorkflowStatus.CANCELLED,
            }
            execution.status = state_map.get(gcp_exec.state, WorkflowStatus.RUNNING)
            execution.updated_at = datetime.utcnow()

            if gcp_exec.state == Execution.State.SUCCEEDED and gcp_exec.result:
                # gcp_exec.result is a JSON string returned from the workflow; parse it into a dict.
                # If parsing fails (malformed output), store raw JSON under "raw" key for debugging.
                import json as _json
                try:
                    execution.result = _json.loads(gcp_exec.result)
                except Exception:
                    execution.result = {"raw": gcp_exec.result}
                execution.completed_at = datetime.utcnow()

            elif gcp_exec.state == Execution.State.FAILED:
                execution.error = gcp_exec.error.message if gcp_exec.error else "Unknown error"
                execution.completed_at = datetime.utcnow()

            await self._db.update_workflow_execution_status(execution)

        except Exception as exc:
            # GCP errors are swallowed: log but don't raise. This prevents a transient API error
            # from cascading. Caller will see execution unchanged and can retry or notify manually.
            log.error("sync_execution_status_failed",
                      execution_id=execution.id, error=str(exc))

        return execution
