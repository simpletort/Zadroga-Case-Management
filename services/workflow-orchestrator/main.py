"""
SimpleTort – Workflow Orchestrator Service
Entry point for Cloud Run.
"""

import structlog
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from config import settings
from api import api_router
from handlers import internal_router


# ---------------------------------------------------------------------------
# Structured logging setup
# ---------------------------------------------------------------------------

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.getLevelName(settings.log_level)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("workflow_orchestrator_starting",
             environment=settings.environment,
             project=settings.gcp_project_id)

    if settings.auto_seed_definitions:
        try:
            from services.seed_service import seed_workflow_definitions
            from services.firestore_service import FirestoreService
            result = await seed_workflow_definitions(FirestoreService())
            log.info("workflow_definitions_seeded", **result)
        except Exception as exc:
            # Non-fatal: log and continue. Service starts even if seeding fails.
            log.error("workflow_definitions_seed_failed", error=str(exc))

    yield
    log.info("workflow_orchestrator_stopped")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SimpleTort – Workflow Orchestrator Service",
    description=(
        "Orchestrates multi-step litigation workflows, manages case tasks, "
        "schedules deadline alerts, and reacts to domain events via Pub/Sub."
    ),
    version="1.0.0",
    lifespan=lifespan,
    # Hide docs in production
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
)

# Public API routes
app.include_router(api_router)

# Internal routes (Cloud Tasks + Pub/Sub callbacks)
app.include_router(internal_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Health"], include_in_schema=False)
async def health():
    return {"status": "ok", "service": "workflow-orchestrator"}


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Let FastAPI's built-in 422 behaviour through — do not swallow it
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal error occurred."},
    )


# ---------------------------------------------------------------------------
# Local development entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.environment == "development",
        log_level=settings.log_level.lower(),
    )
