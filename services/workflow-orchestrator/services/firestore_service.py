"""
Firestore data-access layer for the Workflow Orchestrator.

Collections used:
  cases/{caseId}/tasks/{taskId}
  cases/{caseId}/workflow_executions/{executionId}
  workflow_executions/{executionId}   <- top-level index for cross-case queries
"""

from __future__ import annotations

import structlog
from typing import Optional
from google.cloud import firestore
from google.cloud.firestore_v1.async_client import AsyncClient
from google.api_core import retry as api_retry

from config import settings
from models import Task, TaskStatus, WorkflowExecution
from models.workflow import WorkflowDefinitionConfig

log = structlog.get_logger()

# Fail fast in local/dev environments — default is 300s which hangs the server
_FIRESTORE_RETRY = api_retry.AsyncRetry(deadline=5.0)


class FirestoreService:
    def __init__(self):
        self._client: AsyncClient = firestore.AsyncClient(
            project=settings.gcp_project_id,
            database=settings.firestore_database,
        )

    # ------------------------------------------------------------------
    # Task operations
    # ------------------------------------------------------------------

    async def save_task(self, task: Task) -> None:
        """Create or overwrite a task document."""
        ref = (
            self._client
            .collection("cases")
            .document(task.case_id)
            .collection("tasks")
            .document(task.id)
        )
        # set() overwrites the entire document (not a merge). Used for both create and update.
        # If you only want to update specific fields, use update() instead.
        await ref.set(task.to_firestore())
        log.debug("task_saved", task_id=task.id, case_id=task.case_id)

    async def get_task(self, case_id: str, task_id: str) -> Optional[Task]:
        ref = (
            self._client
            .collection("cases")
            .document(case_id)
            .collection("tasks")
            .document(task_id)
        )
        snap = await ref.get()
        if not snap.exists:
            return None
        return Task.from_firestore(snap.id, snap.to_dict())

    async def get_task_by_id(self, task_id: str) -> Optional[Task]:
        # Collection-group query: searches "tasks" across all cases (slower but case_id is unknown).
        # If case_id is known, prefer get_task() which uses direct subcollection path (faster).
        # Requires Firestore composite index on tasks(id) across all collections.
        query = (
            self._client
            .collection_group("tasks")
            .where("id", "==", task_id)
            .limit(1)
        )
        async for snap in query.stream():
            return Task.from_firestore(snap.id, snap.to_dict())
        return None

    async def list_active_tasks(
        self,
        assigned_to: Optional[str] = None,
        assigned_to_role: Optional[str] = None,
        case_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[Task]:
        # active_statuses: only return tasks that need work (exclude COMPLETED, SKIPPED, OVERDUE).
        # Allows dashboard to show tasks in progress.
        active_statuses = [TaskStatus.PENDING.value, TaskStatus.IN_PROGRESS.value]

        if case_id:
            base_query = (
                self._client
                .collection("cases")
                .document(case_id)
                .collection("tasks")
            )
        else:
            base_query = self._client.collection_group("tasks")

        query = base_query.where("status", "in", active_statuses)

        # assigned_to and assigned_to_role are mutually exclusive filters.
        # assigned_to: specific staff member by UID (direct assignment).
        # assigned_to_role: any staff member in that role can pick it up (team queue).
        if assigned_to:
            query = query.where("assigned_to", "==", assigned_to)
        elif assigned_to_role:
            query = query.where("assigned_to_role", "==", assigned_to_role)

        # order_by("due_date") requires Firestore composite index on (status, due_date).
        # Index must exist in firestore.indexes.json or will fail at query time.
        query = query.order_by("due_date").limit(limit)

        tasks: list[Task] = []
        async for snap in query.stream():
            tasks.append(Task.from_firestore(snap.id, snap.to_dict()))
        return tasks

    async def list_case_tasks(
        self,
        case_id: str,
        status_filter: Optional[TaskStatus] = None,
    ) -> list[Task]:
        query = (
            self._client
            .collection("cases")
            .document(case_id)
            .collection("tasks")
        )
        if status_filter:
            query = query.where("status", "==", status_filter.value)
        query = query.order_by("created_at")

        tasks: list[Task] = []
        async for snap in query.stream():
            tasks.append(Task.from_firestore(snap.id, snap.to_dict()))
        return tasks

    # ------------------------------------------------------------------
    # Workflow execution operations
    # ------------------------------------------------------------------

    async def save_workflow_execution(self, execution: WorkflowExecution) -> None:
        data = execution.to_firestore()
        # Dual-write pattern: write to BOTH locations:
        # 1. Top-level: workflow_executions/{id} — supports cross-case queries (e.g., "all FAILED executions").
        # 2. Case scoped: cases/{caseId}/workflow_executions/{id} — supports case-specific queries and reads.
        # Slightly higher cost but eliminates need for expensive collection-group queries.
        # Write to top-level collection for cross-case queries
        await self._client.collection("workflow_executions").document(execution.id).set(data)
        # Also write to the case sub-collection for case-scoped access
        await (
            self._client
            .collection("cases")
            .document(execution.case_id)
            .collection("workflow_executions")
            .document(execution.id)
            .set(data)
        )
        log.debug("workflow_execution_saved", execution_id=execution.id,
                  case_id=execution.case_id)

    async def get_workflow_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        snap = await (
            self._client
            .collection("workflow_executions")
            .document(execution_id)
            .get()
        )
        if not snap.exists:
            return None
        return WorkflowExecution.from_firestore(snap.id, snap.to_dict())

    # ------------------------------------------------------------------
    # Workflow definition operations (configurable definitions in Firestore)
    # ------------------------------------------------------------------

    async def get_workflow_definition(self, workflow_id: str) -> Optional[WorkflowDefinitionConfig]:
        """Fetch a single configurable workflow definition by its string ID."""
        doc = await (
            self._client
            .collection("workflow_definitions")
            .document(workflow_id)
            .get()
        )
        if not doc.exists:
            return None
        return WorkflowDefinitionConfig.from_firestore(doc.id, doc.to_dict())

    async def list_workflow_definitions(
        self, active_only: bool = False
    ) -> list[WorkflowDefinitionConfig]:
        """List all workflow definitions; optionally filter to active ones only."""
        query = self._client.collection("workflow_definitions")
        if active_only:
            query = query.where("is_active", "==", True)
        definitions: list[WorkflowDefinitionConfig] = []
        async for snap in query.stream():
            definitions.append(WorkflowDefinitionConfig.from_firestore(snap.id, snap.to_dict()))
        return definitions

    async def save_workflow_definition(self, defn: WorkflowDefinitionConfig) -> None:
        """Create or fully overwrite a workflow definition document."""
        await (
            self._client
            .collection("workflow_definitions")
            .document(defn.id)
            .set(defn.to_firestore())
        )
        log.debug("workflow_definition_saved", workflow_id=defn.id)

    async def update_workflow_definition(
        self, workflow_id: str, updates: dict
    ) -> None:
        """Partial update — always bumps updated_at."""
        from datetime import datetime
        updates = dict(updates)
        updates["updated_at"] = datetime.utcnow().isoformat()
        await (
            self._client
            .collection("workflow_definitions")
            .document(workflow_id)
            .update(updates)
        )
        log.debug("workflow_definition_updated", workflow_id=workflow_id)

    async def delete_workflow_definition(self, workflow_id: str) -> None:
        """Hard delete a workflow definition document."""
        await (
            self._client
            .collection("workflow_definitions")
            .document(workflow_id)
            .delete()
        )
        log.debug("workflow_definition_deleted", workflow_id=workflow_id)

    async def update_workflow_execution_status(
        self,
        execution: WorkflowExecution,
    ) -> None:
        # Partial update (not full set()) — only touches mutable status fields.
        # Avoids overwriting immutable fields like created_at and arguments that were set at creation.
        # If a field is not in update_data, it is left unchanged in Firestore.
        """Partial update — only writes mutable status fields."""
        update_data = {
            "status": execution.status.value,
            "updated_at": execution.updated_at.isoformat(),
            "gcp_execution_name": execution.gcp_execution_name,
        }
        if execution.completed_at:
            update_data["completed_at"] = execution.completed_at.isoformat()
        if execution.result:
            update_data["result"] = execution.result
        if execution.error:
            update_data["error"] = execution.error

        # Update both locations (dual-write pattern for consistency)
        top_ref = self._client.collection("workflow_executions").document(execution.id)
        case_ref = (
            self._client
            .collection("cases")
            .document(execution.case_id)
            .collection("workflow_executions")
            .document(execution.id)
        )
        await top_ref.update(update_data)
        await case_ref.update(update_data)
