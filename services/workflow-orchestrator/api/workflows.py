"""
POST /api/v1/workflows/trigger
GET  /api/v1/workflows/{execution_id}
GET  /api/v1/workflows/definitions
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from models import WorkflowTriggerRequest, WorkflowExecution
from services.workflow_engine import WorkflowEngine, _get_definition
from services.firestore_service import FirestoreService

log = structlog.get_logger()
router = APIRouter(prefix="/workflows", tags=["Workflows"])


async def get_workflow_engine() -> WorkflowEngine:
    return WorkflowEngine()


async def get_firestore() -> FirestoreService:
    return FirestoreService()


@router.post(
    "/trigger",
    response_model=WorkflowExecution,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger a workflow for a case",
)
async def trigger_workflow(
    request: WorkflowTriggerRequest,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    db: FirestoreService = Depends(get_firestore),
):
    """
    Triggers a named Cloud Workflow for the given case.
    Creates a WorkflowExecution record in Firestore and returns it.
    The actual GCP Cloud Workflow runs asynchronously.
    """
    # Look up definition from Firestore (via TTL cache); fall back to WORKFLOW_REGISTRY
    definition = await _get_definition(request.workflow_type, db)
    if not definition:
        # Fallback: check the legacy WORKFLOW_REGISTRY for known WorkflowType enum values
        from models.workflow import WORKFLOW_REGISTRY
        legacy = WORKFLOW_REGISTRY.get(request.workflow_type)  # type: ignore[arg-type]
        if not legacy:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Workflow '{request.workflow_type}' not found or inactive",
            )
        required_arguments = legacy.required_arguments
    else:
        if not definition.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Workflow '{request.workflow_type}' is not active",
            )
        required_arguments = definition.required_arguments

    # Validate required arguments are present
    missing = [
        arg for arg in required_arguments
        if arg not in request.arguments and arg != "case_id"
    ]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Missing required workflow arguments: {missing}",
        )

    # Inject case_id into workflow arguments
    arguments = {**request.arguments, "case_id": request.case_id}

    try:
        execution = await engine.trigger(
            case_id=request.case_id,
            workflow_type=request.workflow_type,
            triggered_by=request.triggered_by,
            arguments=arguments,
        )
    except Exception as exc:
        log.error("workflow_trigger_failed", case_id=request.case_id,
                  workflow_type=request.workflow_type, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to trigger workflow. See server logs.",
        )

    return execution


@router.get(
    "/definitions",
    response_model=list[dict],
    summary="List all available workflow definitions",
)
async def list_workflow_definitions(db: FirestoreService = Depends(get_firestore)):
    """
    Returns workflow definitions from Firestore (active only).
    Falls back to the static WORKFLOW_REGISTRY if Firestore returns no results.
    """
    try:
        definitions = await db.list_workflow_definitions(active_only=True)
        if definitions:
            return [d.model_dump() for d in definitions]
    except Exception as exc:
        log.warning("list_definitions_firestore_failed", error=str(exc))

    # Fallback to hardcoded registry (before seeding or on Firestore error)
    from models.workflow import WORKFLOW_REGISTRY
    return [defn.model_dump() for defn in WORKFLOW_REGISTRY.values()]


@router.get(
    "/{execution_id}",
    response_model=WorkflowExecution,
    summary="Get the status of a workflow execution",
)
async def get_workflow_execution(
    execution_id: str,
    db: FirestoreService = Depends(get_firestore),
    engine: WorkflowEngine = Depends(get_workflow_engine),
):
    """
    Returns the current state of a workflow execution.
    Syncs status from GCP Cloud Workflows before responding.
    """
    try:
        execution = await db.get_workflow_execution(execution_id)
    except Exception as exc:
        log.error("get_execution_failed", execution_id=execution_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to reach database. Check GCP credentials.",
        )

    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow execution {execution_id} not found.",
        )

    # Refresh status from GCP if still running
    if execution.gcp_execution_name and execution.status.value == "running":
        try:
            execution = await engine.sync_execution_status(execution)
        except Exception as exc:
            log.warning("sync_status_failed", execution_id=execution_id, error=str(exc))

    return execution
