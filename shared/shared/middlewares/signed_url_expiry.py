"""
shared/middlewares/signed_url_expiry.py — Signed-URL expiry check middleware (stub).
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class SignedUrlExpiryMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        return await call_next(request)
