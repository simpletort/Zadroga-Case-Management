"""
SimpleTort — Reporting & KPI Dashboard Service
Cloud Run | Python 3.11+ | FastAPI 0.110.x | Pydantic 2.x
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.middlewares.cors import get_cors_origins
from app.config import get_settings
from app.routes import dashboard, cases, staff, leads, expenses

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
    logger.info("Reporting service started — Firestore client initialised")
    yield
    logger.info("Reporting service shutting down")


app = FastAPI(
    title="SimpleTort Reporting & KPI Dashboard Service",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(settings.environment) + ["https://lookerstudio.google.com"],
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "x-apigateway-api-userinfo"],
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
    return {"status": "ok", "service": "reporting-service"}


app.include_router(dashboard.router)
app.include_router(cases.router)
app.include_router(staff.router)
app.include_router(leads.router)
app.include_router(expenses.router)
