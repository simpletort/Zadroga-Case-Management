"""
SimpleTort — Task Management Service
Cloud Run | Python 3.11+ | FastAPI 0.110.x | Pydantic 2.x
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.middlewares.auth import AuthMiddleware
from shared.middlewares.cors import get_cors_origins
from shared.middlewares.error_handler import ErrorHandlerMiddleware
from shared.middlewares.logging import LoggingMiddleware

from app.config import get_settings
from app.routes import tasks, user_tasks, internal

settings = get_settings()

logging.basicConfig(
    stream=sys.stdout,
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.utils.firestore import get_firestore_client
    get_firestore_client()
    logger.info("Task management service started — Firestore client initialised")
    yield
    logger.info("Task management service shutting down")


app = FastAPI(
    title="SimpleTort Task Management Service",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

# Routes that require elevated permissions beyond basic auth.
# All other routes require only a valid authenticated session (any role).
_ROUTE_PERMISSIONS: list[tuple[str, str, str]] = [
    ("POST",   r"^/api/v1/tasks/[^/]+/assign$", "tasks.assign"),   # paralegal+
    ("POST",   r"^/api/v1/tasks/[^/]+/skip$",   "tasks.skip"),     # junior_partner+
    ("DELETE", r"^/api/v1/tasks/[^/]+$",         "tasks.delete"),   # senior_partner+
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(settings.environment),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "x-apigateway-api-userinfo"],
)
app.add_middleware(
    AuthMiddleware,
    route_permissions=_ROUTE_PERMISSIONS,
    roles_firestore_project=settings.gcp_project_id,
    roles_firestore_database=settings.firestore_database_id,
    trusted_service_accounts=settings.trusted_service_accounts,
    skip_paths=["/health", "/internal/reminders"],
    app_env=settings.environment,
)
app.add_middleware(LoggingMiddleware)
app.add_middleware(ErrorHandlerMiddleware)


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok", "service": "task-management"}


app.include_router(tasks.router, prefix="/api/v1")
app.include_router(user_tasks.router, prefix="/api/v1")
app.include_router(internal.router)
