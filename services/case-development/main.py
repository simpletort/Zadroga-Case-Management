"""
SimpleTort — Case Development Service
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
from app.routes import assignment, dashboard, communication, review, search, attorney_review, escalation, rejection, decision_audit, update, status_update, case_status_registry, timeline, case_profile, case_profile_fields, feature_flags

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
    logger.info("Case development service started — Firestore client initialised")
    yield
    logger.info("Case development service shutting down")


app = FastAPI(
    title="SimpleTort Case Development Service",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment == "dev" else None,
    redoc_url=None,
)

_ROUTE_PERMISSIONS: list[tuple[str, str, str]] = [
    # Assignment
    ("POST",   r"^/api/v1/cases/[^/]+/assign$",              "cases.write"),
    ("GET",    r"^/api/v1/cases/[^/]+/assignment$",           "cases.read"),
    ("GET",    r"^/api/v1/staff/paralegals/workload$",        "cases.read"),
    # Attorney review
    ("GET",    r"^/api/v1/attorney/review-queue$",            "cases.read"),
    ("POST",   r"^/api/v1/cases/[^/]+/approve-for-filing$",  "cases.approve"),
    ("POST",   r"^/api/v1/cases/bulk-approve$",               "cases.approve"),
    # Communications
    ("GET",    r"^/api/v1/cases/[^/]+/communications$",       "communications.read"),
    ("POST",   r"^/api/v1/cases/[^/]+/communications$",       "communications.write"),
    # Timeline
    ("GET",    r"^/api/v1/cases/[^/]+/timeline$",             "cases.read"),
    # Dashboard
    ("GET",    r"^/api/v1/dashboard/cases$",                  "cases.read"),
    ("GET",    r"^/api/v1/dashboard/cases/[^/]+$",            "cases.read"),
    # Decision audit
    ("GET",    r"^/api/v1/audit/",                            "auditLog.read"),
    ("GET",    r"^/api/v1/cases/[^/]+/audit/",               "auditLog.read"),
    # Escalation
    ("POST",   r"^/api/v1/cases/[^/]+/escalate$",            "cases.status.update"),
    ("GET",    r"^/api/v1/attorney/escalation-queue$",        "cases.read"),
    ("POST",   r"^/api/v1/cases/[^/]+/escalation-decision$", "cases.status.update"),
    # Rejection / resubmission
    ("POST",   r"^/api/v1/cases/[^/]+/reject$",              "cases.status.update"),
    ("POST",   r"^/api/v1/cases/[^/]+/resubmit$",            "cases.status.update"),
    # Paralegal review
    ("GET",    r"^/api/v1/cases/[^/]+/review-preflight$",    "cases.read"),
    ("POST",   r"^/api/v1/cases/[^/]+/submit-for-review$",   "cases.status.update"),
    # Search & presets
    ("GET",    r"^/api/v1/cases/search",                      "cases.read"),
    ("GET",    r"^/api/v1/search/presets",                    "cases.read"),
    ("POST",   r"^/api/v1/search/presets$",                   "cases.write"),
    ("PATCH",  r"^/api/v1/search/presets/[^/]+$",            "cases.write"),
    ("DELETE", r"^/api/v1/search/presets/[^/]+$",            "cases.delete"),
    # Case status registry (firmSettings)
    ("GET",    r"^/api/v1/settings/case-statuses$",            "cases.read"),
    ("POST",   r"^/api/v1/settings/case-statuses$",            "cases.status.update"),
    ("PATCH",  r"^/api/v1/settings/case-statuses/[^/]+$",      "cases.status.update"),
    ("DELETE", r"^/api/v1/settings/case-statuses/[^/]+$",      "cases.status.update"),
    # Feature flags (firmSettings) — PATCH is admin-only (senior_partner / system_admin)
    ("GET",    r"^/api/v1/settings/feature-flags$",             "settings.read"),
    ("PATCH",  r"^/api/v1/settings/feature-flags$",             "settings.write"),
    # Case profile PATCH
    ("PATCH",  r"^/api/v1/cases/[^/]+$",                      "cases.write"),
    # Case profile editable-fields config (firmSettings)
    ("GET",    r"^/api/v1/settings/case-profile-editable-fields$", "settings.read"),
    ("PATCH",  r"^/api/v1/settings/case-profile-editable-fields$", "settings.write"),
    # Case status (manual override)
    ("PATCH",  r"^/api/v1/cases/[^/]+/status$",               "cases.status.update"),
    # Case updates
    ("GET",    r"^/api/v1/cases/[^/]+/updates$",              "cases.read"),
    ("POST",   r"^/api/v1/cases/[^/]+/updates$",              "cases.write"),
    ("PATCH",  r"^/api/v1/cases/[^/]+/updates/[^/]+$",       "cases.write"),
    ("DELETE", r"^/api/v1/cases/[^/]+/updates/[^/]+$",       "cases.delete"),
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
    roles_firestore_database=settings.roles_firestore_database_id,
    trusted_service_accounts=[
        e.strip() for e in settings.trusted_service_accounts.split(",") if e.strip()
    ],
)
app.add_middleware(LoggingMiddleware)
app.add_middleware(ErrorHandlerMiddleware)


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok", "service": "case-development"}


app.include_router(assignment.router)
app.include_router(dashboard.router)
app.include_router(communication.router)
app.include_router(review.router)
app.include_router(search.router)
app.include_router(attorney_review.router)
app.include_router(escalation.router)
app.include_router(rejection.router)
app.include_router(decision_audit.router)
app.include_router(update.router)
app.include_router(status_update.router)
app.include_router(case_status_registry.router)
app.include_router(timeline.router)
app.include_router(case_profile.router)
app.include_router(case_profile_fields.router)
app.include_router(feature_flags.router)
