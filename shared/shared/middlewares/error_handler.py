"""
shared/middlewares/error_handler.py — Catch-all 500 handler for unhandled exceptions.
"""

from __future__ import annotations

import logging
import traceback

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception:
            logger.error(
                "Unhandled exception on %s %s\n%s",
                request.method,
                request.url.path,
                traceback.format_exc(),
            )
            return JSONResponse(
                {"detail": "Internal server error."},
                status_code=500,
            )
