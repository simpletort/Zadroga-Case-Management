"""
api/main.py — FastAPI entrypoint for Cloud Run.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from config import get_settings
from logging_config import setup_logging, get_logger
from middleware.rate_limiter import limiter, rate_limit_exceeded_handler
from routers import leads, partners


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger = get_logger("startup")
    settings = get_settings()
    logger.info("app_starting", env=settings.app_env, project=settings.gcp_project_id)
    yield
    get_logger("shutdown").info("app_shutdown")


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

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS
ALLOWED_ORIGINS = ["https://zad-admin.web.app", "https://zad-admin.firebaseapp.com"]
if not settings.is_production:
    ALLOWED_ORIGINS += ["http://localhost:3000", "http://localhost:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-API-Key", "X-Signature", "X-Timestamp"],
)


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(RequestValidationError)
async def pydantic_validation_handler(request: Request, exc: RequestValidationError):
    details = []
    for err in exc.errors():
        field = ".".join(str(loc) for loc in err["loc"] if loc != "body")
        details.append({"field": field, "code": err["type"].upper(), "message": err["msg"]})
    return JSONResponse(
        status_code=400,
        content={
            "error": "VALIDATION_ERROR", "message": "Request validation failed",
            "details": details, "requestId": getattr(request.state, "request_id", "unknown"),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    get_logger("unhandled").error("unhandled_exception", error=str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_ERROR", "message": "An unexpected error occurred",
            "details": [], "requestId": getattr(request.state, "request_id", "unknown"),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    )


app.include_router(leads.router, prefix="/api/v1")
app.include_router(partners.router, prefix="/api/v1")


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "healthy", "version": "2.0.0"}


@app.get("/", include_in_schema=False)
async def root():
    return {"service": "ZAD Lead Intake API", "version": "2.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
