"""
api/main.py — FastAPI entrypoint for Cloud Run.

Auth flow for staff (frontend → API Gateway → this service):
  API Gateway decodes the Firebase JWT and forwards claims in the
  x-apigateway-api-userinfo header.  AuthMiddleware decodes that header,
  looks up the role's permissions in Firestore, and writes
  request.state.user = {uid, role, email} before the route handler runs.

Auth flow for marketing partners (direct API key):
  X-API-Key header is handled by the get_partner() dependency in
  middleware/auth.py which calls partner_auth.verify_api_key() and writes
  request.state.partner.  The routes use Depends(get_partner) to read it.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from config import get_settings
from logging_config import setup_logging, get_logger
from middleware.rate_limiter import limiter, rate_limit_exceeded_handler
from shared.middlewares.auth import AuthMiddleware
from shared.middlewares.cors import get_cors_origins
from routers import leads, partners
from routers import settings as settings_router


# ---------------------------------------------------------------------------
# Route permission map
# ---------------------------------------------------------------------------
# Tuple layout: (HTTP_METHOD, url_regex, permission_key)
#
# permission_key is matched against the `permissions` array in the
# `roles/{role}` Firestore document (simpletort-dev database).
#
# Routes NOT in this list pass through once the caller is authenticated.
# Routes in this list require the caller's role to have that permission key.
#
# URL patterns are Python regexes. [^/]+ = single path segment.
# ---------------------------------------------------------------------------

_ROUTE_PERMISSIONS: list[tuple[str, str, str]] = [
    # Public
    ("GET",    r"^/health$",                                         "public"),
    ("GET",    r"^/$",                                               "public"),

    # Leads — create
    ("POST",   r"^/api/v1/leads$",                                   "cases.write"),

    # Leads — read
    ("GET",    r"^/api/v1/leads$",                                   "cases.read"),
    ("GET",    r"^/api/v1/leads/[^/]+$",                             "cases.read"),

    # Leads — write
    ("PATCH",  r"^/api/v1/leads/[^/]+/status$",                      "cases.write"),
    ("POST",   r"^/api/v1/leads/bulk-assign$",                       "cases.write"),

    # Leads — export
    ("GET",    r"^/api/v1/leads/export/csv$",                        "cases.read"),

    # Internal Cloud Tasks webhook (OIDC; skipped in development)
    ("POST",   r"^/api/v1/leads/internal/tasks/followup$",           "tasks.internal"),

    # Admin — partner management (senior_partner / system_admin only)
    ("POST",   r"^/api/v1/admin/partners$",                          "staff.write"),
    ("GET",    r"^/api/v1/admin/partners$",                          "staff.read"),
    ("POST",   r"^/api/v1/admin/partners/[^/]+/keys$",               "staff.write"),
    ("DELETE", r"^/api/v1/admin/partners/[^/]+/keys/[^/]+$",         "staff.write"),
    ("GET",    r"^/api/v1/admin/partners/[^/]+/stats$",              "staff.read"),

    # Admin — firm settings (senior_partner / system_admin only)
    ("GET",    r"^/api/v1/admin/settings/case-id-prefix$",           "staff.read"),
    ("PATCH",  r"^/api/v1/admin/settings/case-id-prefix$",           "staff.write"),
    ("GET",    r"^/api/v1/admin/settings/max-file-size$",            "staff.read"),
    ("PATCH",  r"^/api/v1/admin/settings/max-file-size$",            "staff.write"),

    # Admin — screening rules CRUD
    ("GET",    r"^/api/v1/admin/settings/screening-rules$",          "staff.read"),
    ("POST",   r"^/api/v1/admin/settings/screening-rules$",          "staff.write"),
    ("GET",    r"^/api/v1/admin/settings/screening-rules/[^/]+$",    "staff.read"),
    ("PUT",    r"^/api/v1/admin/settings/screening-rules/[^/]+$",    "staff.write"),
    ("DELETE", r"^/api/v1/admin/settings/screening-rules/[^/]+$",    "staff.write"),
]


# ---------------------------------------------------------------------------
# App lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger = get_logger("startup")
    settings = get_settings()
    logger.info("app_starting env=%s project=%s", settings.app_env, settings.gcp_project_id)
    yield
    get_logger("shutdown").info("app_shutdown")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

settings = get_settings()

app = FastAPI(
    title="ZAD Lead Intake API",
    version="2.0.0",
    description="Lead Intake, VCF Screening & Partner Management — Module 1",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ---------------------------------------------------------------------------
# Auth middleware
#
# Middleware executes in REVERSE registration order (last-added runs first).
# CORSMiddleware is added last so it runs first — CORS preflight OPTIONS
# always gets the correct headers even before auth runs.
#
# Execution order on a real request:
#   CORSMiddleware → AuthMiddleware → SlowAPIMiddleware → route handler
# ---------------------------------------------------------------------------

# FIX: Only pass the 5 kwargs that AuthMiddleware.__init__ actually accepts.
# The previous version passed 6 extra kwargs (partners_collection,
# request_logs_collection, gcp_project_id, hmac_max_age_seconds,
# firebase_project_id, app_env) which caused a TypeError at import time,
# crashing Cloud Run before it could serve any request.
#
# FIX: settings.trusted_service_accounts is a comma-separated str.
# Passing the raw string to AuthMiddleware causes set(str) to iterate over
# individual characters.  Split into list[str] first.
app.add_middleware(
    AuthMiddleware,
    route_permissions        = _ROUTE_PERMISSIONS,
    roles_firestore_project  = settings.gcp_project_id,
    roles_firestore_database = settings.firestore_database,
    trusted_service_accounts = [
        e.strip()
        for e in settings.trusted_service_accounts.split(",")
        if e.strip()
    ],
    skip_paths = [
        "/health",
        "/",
        "/api/v1/docs",
        "/api/v1/redoc",
        "/api/v1/openapi.json",
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = get_cors_origins(settings.app_env, settings.gcp_project_id),
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ---------------------------------------------------------------------------
# Request-ID passthrough
# ---------------------------------------------------------------------------

@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def pydantic_validation_handler(request: Request, exc: RequestValidationError):
    details = []
    for err in exc.errors():
        field = ".".join(str(loc) for loc in err["loc"] if loc != "body")
        details.append({"field": field, "code": err["type"].upper(), "message": err["msg"]})
    return JSONResponse(
        status_code=400,
        content={
            "error":     "VALIDATION_ERROR",
            "message":   "Request validation failed",
            "details":   details,
            "requestId": getattr(request.state, "request_id", "unknown"),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    get_logger("unhandled").error("unhandled_exception error=%s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "error":     "INTERNAL_ERROR",
            "message":   "An unexpected error occurred",
            "details":   [],
            "requestId": getattr(request.state, "request_id", "unknown"),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(leads.router,          prefix="/api/v1")
app.include_router(partners.router,       prefix="/api/v1")
app.include_router(settings_router.router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "healthy", "version": "2.0.0"}


@app.get("/", include_in_schema=False)
async def root():
    return {"service": "ZAD Lead Intake API", "version": "2.0.0"}


# ---------------------------------------------------------------------------
# Dev entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True, log_level="debug")