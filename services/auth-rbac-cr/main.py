"""
SimpleTort — Auth-RBAC Service (Cloud Run)
==========================================
FastAPI replacement for the Firebase Cloud Functions auth-rbac service.
Handles user authentication, session management, role-based access control,
user management, and audit logging.

Public endpoints (skip AuthMiddleware): /register, /session, /password-reset
All other endpoints require a Firebase JWT or OIDC token.
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import auth, users, roles, audit
from shared.middlewares import (
    AuthMiddleware,
    ErrorHandlerMiddleware,
    LoggingMiddleware,
    get_cors_origins,
)

settings = get_settings()

logging.basicConfig(
    stream=sys.stdout,
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Routes where AuthMiddleware skips authentication entirely.
# These endpoints handle their own validation (invite tokens, rate limits, etc.)
# ---------------------------------------------------------------------------
_PUBLIC_PATHS = [
    "/health",
    "/api/v1/auth/register",
    "/api/v1/auth/session",
    "/api/v1/auth/password-reset",
]

# ---------------------------------------------------------------------------
# Route permission map — (HTTP method, path regex, Firestore permission key)
# AuthMiddleware resolves permission from the caller's role in Firestore.
# Routes NOT listed here pass through once authenticated (e.g. /logout).
# ---------------------------------------------------------------------------
ROUTE_PERMISSIONS: list[tuple[str, str, str]] = [
    ("POST",   r"^/api/v1/auth/invite$",          "staff.invite"),
    ("POST",   r"^/api/v1/users$",                "staff.manage"),
    ("GET",    r"^/api/v1/users$",                "staff.manage"),
    # GET/PUT /users/{uid} omitted: own-uid access must pass through; route
    # handlers enforce staff.manage OR uid == caller uid themselves.
    ("DELETE", r"^/api/v1/users/[^/]+$",          "staff.manage"),
    ("GET",    r"^/api/v1/roles$",                "staff.manage"),
    ("POST",   r"^/api/v1/roles$",                "system.admin"),
    ("PUT",    r"^/api/v1/roles/[^/]+$",          "system.admin"),
    ("DELETE", r"^/api/v1/roles/[^/]+$",          "system.admin"),
    ("GET",    r"^/api/v1/permissions$",          "staff.manage"),
    ("PUT",    r"^/api/v1/permissions$",          "system.admin"),
    ("POST",   r"^/api/v1/permissions/seed$",     "system.admin"),
    ("GET",    r"^/api/v1/audit-log$",            "auditLog.read"),
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.utils.firestore import get_firestore_client
    get_firestore_client()
    logger.info("Auth-RBAC-CR service started — Firestore client initialised")
    yield
    logger.info("Auth-RBAC-CR service shutting down")


app = FastAPI(
    title="SimpleTort Auth-RBAC Service",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

# Middleware stack — added in innermost-first order; last added = outermost.
# https://simpletort.web.app is only in get_cors_origins()'s dev list, not
# prod — appended here (scoped to this service only) so the frontend's
# auth/user/role/permission/audit-log calls stop failing CORS in production
# without touching the shared origin list that case-development, notification,
# lead-intake, task-management, settlement-financial, and storage-gateway
# also depend on. See commit a4a236a for the same fix on settlement-financial.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(settings.environment) + ["https://simpletort.web.app"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "x-apigateway-api-userinfo"],
)
app.add_middleware(
    AuthMiddleware,
    route_permissions=ROUTE_PERMISSIONS,
    roles_firestore_project=settings.gcp_project_id,
    roles_firestore_database=settings.firestore_database_id,
    trusted_service_accounts=settings.trusted_service_accounts,
    skip_paths=_PUBLIC_PATHS,
)
app.add_middleware(LoggingMiddleware)
app.add_middleware(ErrorHandlerMiddleware)


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok", "service": "auth-rbac-cr"}


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(audit.router)
