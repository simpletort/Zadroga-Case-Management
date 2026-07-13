from fastapi import APIRouter
from .workflows import router as workflows_router
from .tasks import router as tasks_router
from .admin_workflows import router as admin_workflows_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(workflows_router)
api_router.include_router(tasks_router)
api_router.include_router(admin_workflows_router, prefix="/admin/workflows")

__all__ = ["api_router"]
