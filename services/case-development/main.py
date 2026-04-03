"""
SimpleTort — Case Development Service
Cloud Run | Python 3.11+ | FastAPI 0.110.x | Pydantic 2.x
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.middlewares.error_handler import ErrorHandlerMiddleware
from shared.middlewares.logging import LoggingMiddleware

from app.config import get_settings
from app.routes import assignment, dashboard, communication, review

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

origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
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
