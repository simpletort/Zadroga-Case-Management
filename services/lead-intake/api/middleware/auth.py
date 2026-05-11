"""
api/middleware/auth.py — Auth dependency for lead-intake route handlers.

Two callers reach this service:

1. Staff via API Gateway (Firebase JWT):
   - API Gateway decodes the JWT and forwards claims as x-apigateway-api-userinfo
   - shared AuthMiddleware decodes it and sets request.state.user = {uid, role, email}
   - get_partner() below reads request.state.user and builds a PartnerContext from it

2. Marketing partners (X-API-Key):
   - API key is verified by partner_auth.verify_api_key()
   - result is stored in request.state.partner as a PartnerContext
   - get_partner() reads request.state.partner directly

FIX 1: PartnerContext was imported from shared.middlewares.auth which does NOT
        define it.  That caused an ImportError at startup, crashing the service.
        PartnerContext is defined locally in middleware/partner_auth.py — import
        it from there.

FIX 2: The shared AuthMiddleware sets request.state.user (not request.state.partner).
        The previous shim only checked request.state.partner, so staff callers
        always got 401 even after the gateway auth succeeded.
        Now we check both: partner first (API key callers), then user (staff callers).
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# FIX: PartnerContext lives in partner_auth, not in shared.middlewares.auth
from middleware.partner_auth import PartnerContext

__all__ = ["PartnerContext", "get_partner"]

security = HTTPBearer(auto_error=False)


async def get_partner(
    request: Request,
    _credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> PartnerContext:
    """
    FastAPI dependency used by every route that needs an authenticated caller.

    Checks two sources in order:
      1. request.state.partner — set by partner_auth when X-API-Key is present
      2. request.state.user    — set by shared AuthMiddleware for API Gateway / OIDC

    For staff callers coming through the API Gateway, builds a PartnerContext
    using their Firebase UID as the partner_id so all downstream code can read
    partner.partner_id without branching on caller type.
    """
    # Path 1: marketing partner authenticated by X-API-Key
    partner_ctx: PartnerContext | None = getattr(request.state, "partner", None)
    if partner_ctx is not None:
        return partner_ctx

    # Path 2: staff authenticated by API Gateway (Firebase JWT → x-apigateway-api-userinfo)
    # or direct Firebase JWT / OIDC service-to-service token.
    # shared AuthMiddleware sets request.state.user = {uid, role, email}
    user: dict | None = getattr(request.state, "user", None)
    if user is not None:
        return PartnerContext(
            partner_id   = user.get("uid", ""),
            auth_method  = "jwt",
            partner_name = user.get("email", ""),
            raw_claims   = user,
        )

    # Neither auth path ran — return 401
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error":   "UNAUTHORIZED",
            "message": "Not authenticated. Provide X-API-Key or Authorization: Bearer <token>.",
            "details": [],
        },
        headers={"WWW-Authenticate": "Bearer"},
    )