"""
SimpleTort — Task Service
Cloud Run | Python 3.11+ | FastAPI 0.110.x | Pydantic 2.x
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routes import tasks, user_tasks, internal

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
    logger.info("Task service started — Firestore client initialised")
    yield
    logger.info("Task service shutting down")


app = FastAPI(
    title="SimpleTort Task Service",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://staff.simpletort.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
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
    return {"status": "ok", "service": "task-management"}


app.include_router(tasks.router, prefix="/api/v1")
app.include_router(user_tasks.router, prefix="/api/v1")
app.include_router(internal.router)
