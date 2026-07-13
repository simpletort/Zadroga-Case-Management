"""
Internal endpoint consumed by GCP Cloud Workflows at execution start.

GET /internal/workflow-step-config/{workflow_id}

Returns the configurable parameters for all steps in a workflow definition.
Cloud Workflow YAMLs fetch this at init time and use the returned values
instead of hardcoded thresholds and template IDs.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, status

from services.firestore_service import FirestoreService
from services.workflow_engine import _get_definition

log = structlog.get_logger()
router = APIRouter()


@router.get(
    "/{workflow_id}",
    summary="Fetch configurable step parameters for a workflow (called by Cloud Workflows)",
)
async def get_workflow_step_config(workflow_id: str):
    """
    Called by Cloud Workflow YAML at execution start to retrieve configurable
    step parameters without requiring a redeployment.

    Response shape:
      {
        "task_templates": { "<step_id>": { title, priority, due_offset_days, assigned_to_role } },
        "step_parameters": { "<step_id>": { param_name: param_value, ... } }
      }
    """
    db = FirestoreService()
    defn = await _get_definition(workflow_id, db)
    if not defn:
        log.warning("workflow_step_config_not_found", workflow_id=workflow_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow definition '{workflow_id}' not found",
        )

    task_templates = {
        t.step_id: {
            "title": t.title,
            "priority": t.priority,
            "due_offset_days": t.due_offset_days,
            "assigned_to_role": t.assigned_to_role,
        }
        for t in defn.task_templates
    }

    step_parameters = {
        s.step_id: s.parameters
        for s in defn.automated_steps
    }

    log.info(
        "workflow_step_config_served",
        workflow_id=workflow_id,
        task_template_count=len(task_templates),
        automated_step_count=len(step_parameters),
    )

    return {
        "task_templates": task_templates,
        "step_parameters": step_parameters,
    }
