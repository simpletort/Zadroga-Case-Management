# """
# api/main.py — FastAPI entrypoint for Cloud Run.
# ...
# """
# from __future__ import annotations

# import re
# import uuid
# from datetime import datetime
# from contextlib import asynccontextmanager

# from fastapi import FastAPI, Request
# from fastapi.exceptions import RequestValidationError
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.responses import JSONResponse
# from slowapi.errors import RateLimitExceeded
# from slowapi.middleware import SlowAPIMiddleware

# from config import get_settings
# from logging_config import setup_logging, get_logger
# from middleware.rate_limiter import limiter, rate_limit_exceeded_handler
# from shared.middlewares.auth import AuthMiddleware
# from shared.middlewares.cors import get_cors_origins  # ← shared package
# from routers import leads, partners


# # ---------------------------------------------------------------------------
# # Route permission map
# # ---------------------------------------------------------------------------
# # Tuple layout: (HTTP_METHOD, url_regex, permission_key)
# #
# # Auth layers
# # ───────────
# # "leads.*"         → AuthMiddleware checks X-API-Key (partner key) first;
# #                     falls back to Firebase JWT for staff/internal callers.
# # "admin.*"         → AuthMiddleware requires Firebase JWT with role claim
# #                     senior_partner | system_admin  OR  admin == true.
# # "leads.internal"  → AuthMiddleware requires OIDC token issued by Cloud Tasks
# #                     service account; verification skipped in dev/test envs.
# # "public"          → No auth check performed.
# #
# # URL patterns use Python regex. [^/]+ matches a single path segment (e.g. a
# # lead_id or partner_id). Patterns without a $ anchor match any sub-path.
# # ---------------------------------------------------------------------------

# _ROUTE_PERMISSIONS: list[tuple[str, str, str]] = [
#     # ── Health / root (public) ──────────────────────────────────────────────
#     ("GET",    r"^/health$",                                          "public"),
#     ("GET",    r"^/$",                                                "public"),

#     # ── Leads — create ─────────────────────────────────────────────────────
#     # API-key only; idempotent via X-Request-ID; 100/min rate limit
#     ("POST",   r"^/api/v1/leads$",                                    "cases.create"),

#     # ── Leads — read ───────────────────────────────────────────────────────
#     # Partner key OR Firebase JWT accepted
#     ("GET",    r"^/api/v1/leads$",                                    "cases.read"),
#     ("GET",    r"^/api/v1/leads/[^/]+$",                              "cases.read"),

#     # ── Leads — write (status / assignment) ────────────────────────────────
#     ("PATCH",  r"^/api/v1/leads/[^/]+/status$",                       "cases.write"),
#     ("POST",   r"^/api/v1/leads/bulk-assign$",                        "cases.write"),

#     # ── Leads — export ─────────────────────────────────────────────────────
#     # Stricter rate limit (10/min); same auth as leads.read
#     ("GET",    r"^/api/v1/leads/export/csv$",                         "cases.read"),

#     # ── Leads — internal Cloud Tasks webhook ───────────────────────────────
#     # Hidden from OpenAPI; OIDC token required (skipped in APP_ENV=development)
#     ("POST",   r"^/api/v1/leads/internal/tasks/followup$",            "tasks.read"),

#     # ── Admin — partner management ─────────────────────────────────────────
#     # Firebase JWT with admin role required for ALL /admin/partners routes
#     ("POST",   r"^/api/v1/admin/partners$",                           "staff.write"),
#     ("GET",    r"^/api/v1/admin/partners$",                           "staff.read"),
#     ("POST",   r"^/api/v1/admin/partners/[^/]+/keys$",               "staff.write"),
#     ("DELETE", r"^/api/v1/admin/partners/[^/]+/keys/[^/]+$",         "staff.write"),
#     ("GET",    r"^/api/v1/admin/partners/[^/]+/stats$",              "staff.read"),
# ]


# # ---------------------------------------------------------------------------
# # Permission → auth strategy mapping
# # (consumed by AuthMiddleware to know which strategy to apply per route)
# # ---------------------------------------------------------------------------
# # This dict is passed to AuthMiddleware alongside _ROUTE_PERMISSIONS so the
# # middleware knows WHICH auth mechanism to enforce for each permission key,
# # rather than hard-coding that logic inside the router layer.
# # ---------------------------------------------------------------------------

# # _PERMISSION_AUTH_STRATEGY: dict[str, str] = {
# #     # No auth
# #     "public":                "none",

# #     # Partner API key only (X-API-Key header)
# #     "cases.create":          "api_key",

# #     # Partner API key OR Firebase JWT (staff can also read/write)
# #     "cases.read":            "api_key_or_firebase",
# #     "cases.write":           "api_key_or_firebase",
# #     "cases.export":          "api_key_or_firebase",

# #     # Cloud Tasks OIDC token (bypassed in development mode)
# #     "task.read":        "oidc",

# #     # Firebase JWT with admin role claim required
# #     "admin.partners.read":   "firebase_admin",
# #     "admin.partners.write":  "firebase_admin",
# # }


# # ---------------------------------------------------------------------------
# # Admin role claims accepted by the firebase_admin strategy
# # ---------------------------------------------------------------------------

# _ADMIN_ROLES: list[str] = ["senior_partner", "system_admin"]


# # ---------------------------------------------------------------------------
# # App lifespan
# # ---------------------------------------------------------------------------

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     setup_logging()
#     logger = get_logger("startup")
#     settings = get_settings()
#     logger.info("app_starting", env=settings.app_env, project=settings.gcp_project_id)
#     yield
#     get_logger("shutdown").info("app_shutdown")


# # ---------------------------------------------------------------------------
# # FastAPI app
# # ---------------------------------------------------------------------------

# settings = get_settings()

# app = FastAPI(
#     title="ZAD Lead Intake API",
#     version="2.0.0",
#     description="Lead Intake, VCF Screening & Partner Management — Module 1",
#     openapi_url="/api/v1/openapi.json",
#     docs_url="/api/v1/docs",
#     redoc_url="/api/v1/redoc",
#     lifespan=lifespan,
# )

# # ---------------------------------------------------------------------------
# # Rate limiter
# # ---------------------------------------------------------------------------

# app.state.limiter = limiter
# app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
# app.add_middleware(SlowAPIMiddleware)


# app.add_middleware(
#     AuthMiddleware,
#     route_permissions=_ROUTE_PERMISSIONS,
#     roles_firestore_project=settings.gcp_project_id,
#     roles_firestore_database=settings.firestore_database,
#     trusted_service_accounts=[
#         e.strip() for e in settings.trusted_service_accounts.split(",") if e.strip()
#     ],
#     skip_paths=["/health", "/", "/api/v1/docs", "/api/v1/redoc", "/api/v1/openapi.json"],
# )

# # ---------------------------------------------------------------------------
# # CORS
# # ---------------------------------------------------------------------------

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=get_cors_origins(settings.app_env),
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )
# # ---------------------------------------------------------------------------
# # Request-ID passthrough middleware
# # ---------------------------------------------------------------------------

# @app.middleware("http")
# async def attach_request_id(request: Request, call_next):
#     request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
#     request.state.request_id = request_id
#     response = await call_next(request)
#     response.headers["X-Request-ID"] = request_id
#     return response

# # ---------------------------------------------------------------------------
# # Exception handlers
# # ---------------------------------------------------------------------------

# @app.exception_handler(RequestValidationError)
# async def pydantic_validation_handler(request: Request, exc: RequestValidationError):
#     details = []
#     for err in exc.errors():
#         field = ".".join(str(loc) for loc in err["loc"] if loc != "body")
#         details.append({
#             "field": field,
#             "code": err["type"].upper(),
#             "message": err["msg"],
#         })
#     return JSONResponse(
#         status_code=400,
#         content={
#             "error": "VALIDATION_ERROR",
#             "message": "Request validation failed",
#             "details": details,
#             "requestId": getattr(request.state, "request_id", "unknown"),
#             "timestamp": datetime.utcnow().isoformat() + "Z",
#         },
#     )


# @app.exception_handler(Exception)
# async def unhandled_exception_handler(request: Request, exc: Exception):
#     get_logger("unhandled").error("unhandled_exception", error=str(exc))
#     return JSONResponse(
#         status_code=500,
#         content={
#             "error": "INTERNAL_ERROR",
#             "message": "An unexpected error occurred",
#             "details": [],
#             "requestId": getattr(request.state, "request_id", "unknown"),
#             "timestamp": datetime.utcnow().isoformat() + "Z",
#         },
#     )

# # ---------------------------------------------------------------------------
# # Routers
# # ---------------------------------------------------------------------------

# app.include_router(leads.router, prefix="/api/v1")
# app.include_router(partners.router, prefix="/api/v1")

# # ---------------------------------------------------------------------------
# # Public endpoints (excluded from OpenAPI schema)
# # ---------------------------------------------------------------------------

# @app.get("/health", include_in_schema=False)
# async def health():
#     return {"status": "healthy", "version": "2.0.0"}


# @app.get("/", include_in_schema=False)
# async def root():
#     return {"service": "ZAD Lead Intake API", "version": "2.0.0"}

# # ---------------------------------------------------------------------------
# # Dev entrypoint
# # ---------------------------------------------------------------------------

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True, log_level="debug")

"""
api/main.py — FastAPI entrypoint for Cloud Run.

Auth is handled entirely by shared.middlewares.AuthMiddleware which now covers:
  - x-apigateway-api-userinfo (API Gateway path)
  - X-API-Key (marketing partner API key path)
  - Authorization: Bearer <Firebase JWT> (staff direct path)
  - Authorization: Bearer <Google OIDC> (service-to-service path)

Route-level dependencies (get_partner) read from request.state.partner which
the middleware always sets before the route handler is invoked.
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


# ---------------------------------------------------------------------------
# Route permission map
# ---------------------------------------------------------------------------
# Tuple layout: (HTTP_METHOD, url_regex, permission_key)
#
# The permission_key is matched against the `permissions` array in the
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

    # Leads — create (partner API key only in practice, but any authenticated caller)
    ("POST",   r"^/api/v1/leads$",                                   "cases.create"),

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
# Middleware is executed in REVERSE registration order (innermost last added).
# CORSMiddleware is added last so it runs first on every request, ensuring
# CORS preflight OPTIONS always gets the right headers even before auth.
#
# Execution order on a real request:
#   CORSMiddleware → AuthMiddleware → SlowAPIMiddleware → route handler
# ---------------------------------------------------------------------------

# Resolve trusted_service_accounts: config stores a comma-separated string,
# AuthMiddleware now accepts both str and list[str].
app.add_middleware(
    AuthMiddleware,
    route_permissions        = _ROUTE_PERMISSIONS,
    roles_firestore_project  = settings.gcp_project_id,
    roles_firestore_database = settings.firestore_database,
    trusted_service_accounts = settings.trusted_service_accounts,
    skip_paths               = [
        "/health",
        "/",
        "/api/v1/docs",
        "/api/v1/redoc",
        "/api/v1/openapi.json",
    ],
    # Partner API key config
    partners_collection      = settings.firestore_partners_collection,
    request_logs_collection  = settings.firestore_request_logs_collection,
    gcp_project_id           = settings.gcp_project_id,
    hmac_max_age_seconds     = settings.hmac_signature_max_age_seconds,
    # Firebase JWT config
    firebase_project_id      = settings.firebase_project_id,
    app_env                  = settings.app_env,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = get_cors_origins(settings.app_env),
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

app.include_router(leads.router,    prefix="/api/v1")
app.include_router(partners.router, prefix="/api/v1")


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