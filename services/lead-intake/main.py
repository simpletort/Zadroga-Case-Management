"""
main.py — FastAPI application entrypoint for Cloud Run.

Startup sequence:
  1. Load settings (pydantic-settings / env vars)
  2. Setup structured logging
  3. Configure rate limiter
  4. Mount routers
  5. Register exception handlers

Health check endpoint (/health) is excluded from auth/rate-limiting
for Cloud Run and load balancer health probes.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from config import get_settings
from logging_config import setup_logging, get_logger
from middleware.rate_limiter import limiter, rate_limit_exceeded_handler
from routers import leads

# ── App factory ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown hooks."""
    setup_logging()
    logger = get_logger("startup")
    settings = get_settings()
    logger.info(
        "app_starting",
        env=settings.app_env,
        project=settings.gcp_project_id,
    )
    yield
    logger.info("app_shutdown")


settings = get_settings()

app = FastAPI(
    title="ZAD Lead Intake API",
    version="1.0.0",
    description="Lead Intake & Automated Screening — Module 1",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    lifespan=lifespan,
)

# ── Rate limiter ──────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Restrict origins in production to your Admin UI domain
ALLOWED_ORIGINS = [
    "https://zad-admin.web.app",
    "https://zad-admin.firebaseapp.com",
]
if not settings.is_production:
    ALLOWED_ORIGINS.append("http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

# ── Request ID middleware ─────────────────────────────────────────────────────
@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    """Attach a trace request ID to every request/response."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ── Exception handlers ────────────────────────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def pydantic_validation_handler(
    request: Request, exc: RequestValidationError
):
    """
    Convert Pydantic v2 validation errors into our standard ErrorResponse format.
    """
    details = []
    for err in exc.errors():
        field = ".".join(str(loc) for loc in err["loc"] if loc != "body")
        details.append({
            "field": field,
            "code": err["type"].upper(),
            "message": err["msg"],
        })

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "details": details,
            "requestId": getattr(request.state, "request_id", "unknown"),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    )


@app.exception_handler(HTTPException := __import__("fastapi").HTTPException)
async def http_exception_handler(request: Request, exc):
    """Pass through HTTPExceptions with our structured format."""
    detail = exc.detail
    if isinstance(detail, str):
        detail = {
            "error": "HTTP_ERROR",
            "message": detail,
            "details": [],
            "requestId": getattr(request.state, "request_id", "unknown"),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    return JSONResponse(status_code=exc.status_code, content=detail)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger = get_logger("unhandled")
    logger.error(
        "unhandled_exception",
        error=str(exc),
        request_id=getattr(request.state, "request_id", "unknown"),
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_ERROR",
            "message": "An unexpected error occurred",
            "details": [],
            "requestId": getattr(request.state, "request_id", "unknown"),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    )


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(leads.router, prefix="/api/v1")


# ── Health check (no auth) ────────────────────────────────────────────────────
@app.get("/health", include_in_schema=False)
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/", include_in_schema=False)
async def root():
    return {"service": "ZAD Lead Intake API", "version": "1.0.0"}


# ── Local dev entrypoint ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
        log_level="debug",
    )
