"""
SimpleTort — Cloud Storage Gateway Service
Cloud Run | Python 3.11+ | FastAPI 0.110.x | Pydantic 2.x

Central gatekeeper for all GCS file access.
Generates signed URLs for secure upload/download without exposing
raw GCS credentials to frontend clients or other services.
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import signed_url, metadata, lifecycle, upload, documents, browser
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
# Route permission map — (HTTP method, path regex, Firestore permission key)
# AuthMiddleware checks the requesting user's role has this permission.
# ---------------------------------------------------------------------------
ROUTE_PERMISSIONS: list[tuple[str, str, str]] = [
    # Signed URL
    ("GET",   r"^/api/v1/storage/signed-url$",                        "storage.signed_url"),
    # File metadata
    ("GET",   r"^/api/v1/storage/[^/]+/metadata$",                    "storage.metadata.read"),
    # Lifecycle — reads
    ("GET",   r"^/api/v1/storage/lifecycle$",                         "storage.lifecycle.read"),
    # Lifecycle — writes
    ("PUT",   r"^/api/v1/storage/lifecycle$",                         "storage.lifecycle.write"),
    ("POST",  r"^/api/v1/storage/lifecycle/apply-default$",           "storage.lifecycle.write"),
    ("PUT",   r"^/api/v1/storage/lifecycle/soft-delete$",             "storage.lifecycle.write"),
    # Case document hold
    ("PUT",   r"^/api/v1/storage/cases/[^/]+/hold$",                  "storage.hold.write"),
    # Upload flow
    ("POST",  r"^/api/v1/storage/upload/register$",                   "storage.upload.write"),
    ("GET",   r"^/api/v1/storage/upload/[^/]+/status$",               "storage.upload.read"),
    # Document list / update
    ("GET",   r"^/api/v1/storage/cases/[^/]+/documents$",             "storage.documents.read"),
    ("PATCH", r"^/api/v1/storage/cases/[^/]+/documents/[^/]+$",       "storage.documents.write"),
    # File browser
    ("GET",   r"^/api/v1/storage/cases/[^/]+/browse$",                "storage.documents.read"),
    ("POST",  r"^/api/v1/storage/cases/[^/]+/folders$",               "storage.documents.write"),
    ("POST",  r"^/api/v1/storage/cases/[^/]+/move$",                  "storage.documents.write"),
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.utils.firestore import get_firestore_client
    from app.utils.gcs_client import get_gcs_client
    get_firestore_client()
    get_gcs_client()
    logger.info("Storage Gateway started — Firestore and GCS clients initialised")
    yield
    logger.info("Storage Gateway shutting down")


app = FastAPI(
    title="SimpleTort Cloud Storage Gateway Service",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

# Middleware stack — added in innermost-first order; last added = outermost.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(settings.environment, settings.gcp_project_id),
    allow_credentials=True,
    allow_methods=["GET", "PUT", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "x-apigateway-api-userinfo"],
)
app.add_middleware(
    AuthMiddleware,
    route_permissions=ROUTE_PERMISSIONS,
    roles_firestore_project=settings.gcp_project_id,
    roles_firestore_database=settings.firestore_database_id,
    trusted_service_accounts=settings.trusted_service_accounts,
)
app.add_middleware(LoggingMiddleware)
app.add_middleware(ErrorHandlerMiddleware)


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok", "service": "storage-gateway"}


app.include_router(signed_url.router)
app.include_router(metadata.router)
app.include_router(lifecycle.router)
app.include_router(upload.router)
app.include_router(documents.router)
app.include_router(browser.router)
