"""
app.py — FastAPI application for the Enrollment Workflow Service (Module 3).

Generic certification and registration workflow service. Internally uses
program-agnostic terminology; exposes both human-facing endpoints and
orchestrator-adapter endpoints that match the paths called by the
workflow-orchestrator's vcf-enrollment.yaml Cloud Workflow YAML.

Human-facing endpoints (generic terminology):
  POST /api/v1/enrollment/certification/trigger          Trigger certification workflow
  GET  /api/v1/enrollment/certification/{case_id}        Get certification status
  PUT  /api/v1/enrollment/certification/{case_id}/status Advance certification state
  POST /api/v1/enrollment/registration/initiate          Initiate registration workflow
  GET  /api/v1/enrollment/registration/{case_id}         Get registration status
  PUT  /api/v1/enrollment/registration/{case_id}/status  Advance registration state
  GET  /api/v1/enrollment/registration/{case_id}/prefill Get pre-filled form data

Orchestrator adapter endpoints (WTC/VCF terminology — called by vcf-enrollment.yaml):
  GET  /api/v1/enrollment/wtc-status?case_id={}          Check certification complete
  PUT  /api/v1/enrollment/wtc-status                     Trigger certification workflow
  GET  /api/v1/enrollment/vcf-status?case_id={}          Check registration complete
  PUT  /api/v1/enrollment/vcf-status                     Trigger registration workflow
  GET  /api/v1/enrollment/deadlines?case_id={}           Get deadline dates

Dashboard:
  GET  /api/v1/dashboard/enrollment     Enrollment pipeline dashboard
  GET  /api/v1/dashboard/deadlines      Deadline summary dashboard
  GET  /api/v1/dashboard/export         Export to CSV

  GET  /health                          Health probe
"""

from __future__ import annotations

import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.middlewares import AuthMiddleware, ErrorHandlerMiddleware, LoggingMiddleware
from shared.middlewares.cors import get_cors_origins

from config import settings

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "enrollment_workflow_service_starting",
        env=settings.app_env,
        project=settings.gcp_project_id,
    )
    yield
    log.info("enrollment_workflow_service_shutdown")


app = FastAPI(
    title="Enrollment Workflow Service",
    version="2.0.0",
    description=(
        "Generic certification and registration workflow service. "
        "Handles program enrollment, registration tracking, deadline monitoring, "
        "and paralegal task creation. Integrates with the Workflow Orchestrator "
        "via the /api/v1/enrollment/wtc-status and /vcf-status adapter endpoints."
    ),
    openapi_url="/openapi.json",
    docs_url="/docs",
    lifespan=lifespan,
)

# Orchestrator adapter paths are authenticated at the GCP infrastructure level
# (Cloud Workflows service account OIDC) — skip application-level auth for them.
_ORCHESTRATOR_SKIP_PATHS = [
    "/api/v1/enrollment/wtc-status",
    "/api/v1/enrollment/vcf-status",
    "/api/v1/enrollment/deadlines",
]

# No route-level permission keys needed — all human-facing endpoints require
# only a valid authenticated session (any staff role).
_ROUTE_PERMISSIONS: list[tuple[str, str, str]] = []

app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(
    AuthMiddleware,
    route_permissions=_ROUTE_PERMISSIONS,
    roles_firestore_project=settings.gcp_project_id,
    roles_firestore_database=settings.firestore_database_id,
    trusted_service_accounts=settings.trusted_service_accounts,
    skip_paths=["/health", "/"] + _ORCHESTRATOR_SKIP_PATHS,
    firebase_project_id=settings.gcp_project_id,
    app_env=settings.app_env,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(settings.app_env, settings.gcp_project_id),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "x-apigateway-api-userinfo"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
# Import here (after app creation) to avoid circular imports.

from routers.enrollment import router as enrollment_router        # noqa: E402
from routers.orchestrator import router as orchestrator_router    # noqa: E402
from routers.dashboard import router as dashboard_router          # noqa: E402

# Generic enrollment endpoints — used by the paralegal dashboard and case UI
app.include_router(enrollment_router)

# Orchestrator adapter endpoints — used by vcf-enrollment.yaml Cloud Workflow
# These share the /api/v1/enrollment prefix but expose WTC/VCF-named paths
# so the orchestrator does not need to change.
app.include_router(orchestrator_router)

# Dashboard and reporting endpoints
app.include_router(dashboard_router, prefix="/api/v1/dashboard", tags=["Dashboard"])


# ── Health / Root ─────────────────────────────────────────────────────────────

@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "healthy", "service": "enrollment-workflow", "version": "2.0.0"}


@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": "Enrollment Workflow Service",
        "version": "2.0.0",
        "docs": "/docs",
    }


# ── Local dev entrypoint ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True, log_level="debug")
