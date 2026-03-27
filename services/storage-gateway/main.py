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

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routes import signed_url, metadata, lifecycle, upload, documents

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
    docs_url="/docs" if settings.env != "prod" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://staff.simpletort.com",
    ],
    allow_credentials=True,
    allow_methods=["GET", "PUT", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s: %s", request.url, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please try again."},
    )


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok", "service": "storage-gateway"}


app.include_router(signed_url.router)
app.include_router(metadata.router)
app.include_router(lifecycle.router)
app.include_router(upload.router)
app.include_router(documents.router)
