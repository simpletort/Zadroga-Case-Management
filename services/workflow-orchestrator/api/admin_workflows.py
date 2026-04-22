"""
Admin API for managing configurable workflow definitions.

Routes (all under /api/v1/admin/workflows):
  GET    /                          — list all definitions
  GET    /{workflow_id}             — get single definition
  PATCH  /{workflow_id}             — update metadata (display_name, description, etc.)
  PATCH  /{workflow_id}/task-steps/{step_id}      — edit a task template's properties
  PATCH  /{workflow_id}/automated-steps/{step_id} — edit an automated step's parameters
  POST   /{workflow_id}/activate    — set is_active=True
  POST   /{workflow_id}/deactivate  — set is_active=False
  POST   /seed                      — run the idempotent seeder

These endpoints are intended for non-technical users (paralegals, senior partners)
via the React admin UI. No authentication middleware is added here — access control
is enforced at the Cloud Run ingress layer via the /admin/ path prefix.
"""

from __future__ import annotations

import structlog
from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from models.workflow import (
    WorkflowDefinitionConfig,
    UpdateWorkflowDefinitionRequest,
)
from services.firestore_service import FirestoreService
from services.workflow_engine import _invalidate_cache

log = structlog.get_logger()
router = APIRouter(tags=["admin-workflows"])


# ---------------------------------------------------------------------------
# Request models for step-level PATCH endpoints
# ---------------------------------------------------------------------------

class UpdateTaskStepRequest(BaseModel):
    """Editable fields on a TaskTemplateConfig."""
    title: Optional[str] = None
    priority: Optional[str] = None       # low | medium | high | critical
    due_offset_days: Optional[int] = None
    assigned_to_role: Optional[str] = None  # paralegal | attorney | client


class UpdateAutomatedStepRequest(BaseModel):
    """Replaces the parameters dict on an AutomatedStepConfig."""
    parameters: dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_or_404(db: FirestoreService, workflow_id: str) -> WorkflowDefinitionConfig:
    defn = await db.get_workflow_definition(workflow_id)
    if not defn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow definition '{workflow_id}' not found",
        )
    return defn


def _validate_parameters(
    parameters: dict[str, Any],
    step: Any,
) -> None:
    """
    Validate incoming parameter values against the step's parameter_schema.
    Enforces min_value, max_value, and options constraints.
    """
    schema_by_name = {p.name: p for p in step.parameter_schema}
    for name, value in parameters.items():
        param_def = schema_by_name.get(name)
        if not param_def:
            continue  # unknown parameters are silently ignored (forward compatibility)
        if param_def.min_value is not None and isinstance(value, (int, float)):
            if value < param_def.min_value:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Parameter '{name}' must be >= {param_def.min_value}",
                )
        if param_def.max_value is not None and isinstance(value, (int, float)):
            if value > param_def.max_value:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Parameter '{name}' must be <= {param_def.max_value}",
                )
        if param_def.options and isinstance(value, str):
            if value not in param_def.options:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Parameter '{name}' must be one of {param_def.options}",
                )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/seed",
    summary="Seed all 7 workflow definitions into Firestore (idempotent)",
)
async def seed_definitions():
    """
    Writes the 7 hardcoded workflow definitions to Firestore if they don't already exist.
    Safe to call multiple times — existing documents are never overwritten.
    """
    from services.seed_service import seed_workflow_definitions
    db = FirestoreService()
    result = await seed_workflow_definitions(db)
    log.info("admin_seed_complete", **result)
    return result


@router.get(
    "/",
    response_model=list[WorkflowDefinitionConfig],
    summary="List all workflow definitions",
)
async def list_definitions(
    active_only: bool = Query(default=False, description="Return only active workflows"),
):
    db = FirestoreService()
    return await db.list_workflow_definitions(active_only=active_only)


@router.get(
    "/{workflow_id}",
    response_model=WorkflowDefinitionConfig,
    summary="Get a single workflow definition",
)
async def get_definition(workflow_id: str):
    db = FirestoreService()
    return await _get_or_404(db, workflow_id)


@router.patch(
    "/{workflow_id}",
    response_model=WorkflowDefinitionConfig,
    summary="Update workflow metadata (display_name, description, estimated_duration)",
)
async def update_definition(workflow_id: str, body: UpdateWorkflowDefinitionRequest):
    db = FirestoreService()
    await _get_or_404(db, workflow_id)  # 404 if not found

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields provided to update",
        )

    await db.update_workflow_definition(workflow_id, updates)
    _invalidate_cache(workflow_id)
    log.info("admin_workflow_updated", workflow_id=workflow_id, fields=list(updates.keys()))
    return await db.get_workflow_definition(workflow_id)


@router.patch(
    "/{workflow_id}/task-steps/{step_id}",
    response_model=WorkflowDefinitionConfig,
    summary="Edit a task template step (title, priority, due_offset_days, assigned_to_role)",
)
async def update_task_step(
    workflow_id: str,
    step_id: str,
    body: UpdateTaskStepRequest,
):
    db = FirestoreService()
    defn = await _get_or_404(db, workflow_id)

    # Find the task template by step_id
    template = next((t for t in defn.task_templates if t.step_id == step_id), None)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task step '{step_id}' not found in workflow '{workflow_id}'",
        )

    # Apply non-None changes to the template
    changes = body.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(template, field, value)

    # Save the full document back (embedded array must be fully rewritten)
    await db.save_workflow_definition(defn)
    _invalidate_cache(workflow_id)
    log.info(
        "admin_task_step_updated",
        workflow_id=workflow_id,
        step_id=step_id,
        fields=list(changes.keys()),
    )
    return defn


@router.patch(
    "/{workflow_id}/automated-steps/{step_id}",
    response_model=WorkflowDefinitionConfig,
    summary="Edit an automated step's configurable parameters",
)
async def update_automated_step(
    workflow_id: str,
    step_id: str,
    body: UpdateAutomatedStepRequest,
):
    db = FirestoreService()
    defn = await _get_or_404(db, workflow_id)

    # Find the automated step by step_id
    step = next((s for s in defn.automated_steps if s.step_id == step_id), None)
    if not step:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Automated step '{step_id}' not found in workflow '{workflow_id}'",
        )

    # Validate incoming parameters against the step's schema
    _validate_parameters(body.parameters, step)

    # Merge new parameters with existing (allows partial parameter updates)
    step.parameters.update(body.parameters)

    # Save the full document back
    await db.save_workflow_definition(defn)
    _invalidate_cache(workflow_id)
    log.info(
        "admin_automated_step_updated",
        workflow_id=workflow_id,
        step_id=step_id,
        parameters=body.parameters,
    )
    return defn


@router.post(
    "/{workflow_id}/activate",
    response_model=WorkflowDefinitionConfig,
    summary="Activate a workflow (set is_active=True)",
)
async def activate_workflow(workflow_id: str):
    db = FirestoreService()
    await _get_or_404(db, workflow_id)
    await db.update_workflow_definition(workflow_id, {"is_active": True})
    _invalidate_cache(workflow_id)
    log.info("admin_workflow_activated", workflow_id=workflow_id)
    return await db.get_workflow_definition(workflow_id)


@router.post(
    "/{workflow_id}/deactivate",
    response_model=WorkflowDefinitionConfig,
    summary="Deactivate a workflow (set is_active=False)",
)
async def deactivate_workflow(workflow_id: str):
    db = FirestoreService()
    await _get_or_404(db, workflow_id)
    await db.update_workflow_definition(workflow_id, {"is_active": False})
    _invalidate_cache(workflow_id)
    log.info("admin_workflow_deactivated", workflow_id=workflow_id)
    return await db.get_workflow_definition(workflow_id)
