"""
api/middleware/auth.py — Compatibility shim for lead-intake routers.

The real authentication logic now lives in shared/middlewares/auth.py and runs
as ASGI middleware before any route handler is called. By the time a router
dependency like `get_partner()` executes, request.state.partner is already set.

This module re-exports PartnerContext from shared so existing router imports
like `from middleware.auth import PartnerContext, get_partner` keep working
without any change to leads.py or partners.py.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Re-export PartnerContext from shared so routers can keep their existing import
from shared.middlewares.auth import PartnerContext

__all__ = ["PartnerContext", "get_partner"]

security = HTTPBearer(auto_error=False)


async def get_partner(
    request: Request,
    _credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> PartnerContext:
    """
    FastAPI dependency used by every route that needs an authenticated caller.

    The shared AuthMiddleware always runs first and sets request.state.partner.
    This dependency just reads it, so all router code continues to work unchanged.

    If somehow request.state.partner is missing (e.g. a route was called in a
    test without the middleware), we return a clear 401 rather than an
    AttributeError.
    """
    ctx: PartnerContext | None = getattr(request.state, "partner", None)
    if ctx is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error":   "UNAUTHORIZED",
                "message": "Not authenticated. Provide X-API-Key or Authorization: Bearer <token>.",
                "details": [],
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    return ctx