from .event_handler import router as internal_router
from .config_handler import router as config_router

# Register the config endpoint under /internal/workflow-step-config/{workflow_id}
internal_router.include_router(config_router, prefix="/workflow-step-config")

__all__ = ["internal_router"]
