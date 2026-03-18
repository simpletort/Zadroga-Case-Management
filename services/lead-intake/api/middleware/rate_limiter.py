"""
api/middleware/rate_limiter.py — SlowAPI rate limiter setup.
"""
from __future__ import annotations
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from datetime import datetime


def _key_func(request: Request) -> str:
    """Rate limit key: partner_id if auth'd, else IP."""
    partner = getattr(getattr(request, "state", None), "partner", None)
    if partner:
        return f"partner:{partner.partner_id}"
    return get_remote_address(request)


limiter = Limiter(key_func=_key_func, default_limits=["200/minute"])


async def rate_limit_exceeded_handler(request: Request, exc) -> Response:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": "RATE_LIMIT_EXCEEDED",
            "message": "Too many requests. Please slow down.",
            "details": [],
            "requestId": getattr(request.state, "request_id", "unknown"),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    )
