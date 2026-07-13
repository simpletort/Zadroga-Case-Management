"""
api/middleware/auth.py — Auth dependency for lead-intake route handlers.

Three callers reach this service:

1. Staff via API Gateway (Firebase JWT → x-apigateway-api-userinfo header):
   - API Gateway decodes the JWT and forwards claims as x-apigateway-api-userinfo.
   - shared AuthMiddleware decodes it and sets:
       request.state.user    = {uid, role, email}
       request.state.partner = PartnerContext(auth_method="gateway", ...)
   - get_partner() returns request.state.partner directly.

2. Staff submitting leads directly via Firebase JWT (Authorization: Bearer <token>):
   - Shared AuthMiddleware verifies the Firebase JWT (path 3) and sets:
       request.state.user    = {uid, role, email}
       request.state.partner = PartnerContext(auth_method="firebase_jwt", ...)
   - get_partner() returns it, giving staff full access to all lead endpoints.
   - This is how the internal UI submits leads — same as the API Gateway path
     but without the gateway in front (direct Cloud Run URL or dev mode).

3. Marketing partners (X-API-Key):
   - partner_auth middleware verifies the key and writes request.state.partner.
   - get_partner() returns request.state.partner directly.

Route handlers can call is_staff_caller(partner) to check if the caller is
staff (True) or a marketing partner (False), e.g. for audit-trail labelling
or to set marketingSource to the staff member's display name.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from middleware.partner_auth import PartnerContext

__all__ = ["PartnerContext", "get_partner", "is_staff_caller"]

security = HTTPBearer(auto_error=False)


async def get_partner(
    request: Request,
    _credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> PartnerContext:
    """
    FastAPI dependency — resolves the authenticated caller to a PartnerContext.

    Priority:
      1. request.state.partner already populated by shared AuthMiddleware
         (covers gateway, firebase_jwt, api_key paths) → return it directly.
      2. request.state.user populated but partner not set → build PartnerContext
         from user dict (safety fallback for partial middleware runs).
      3. Neither set → HTTP 401.

    Staff callers (auth_method = "gateway" or "firebase_jwt") use their Firebase
    UID as partner_id so all downstream code reading partner.partner_id works
    without any branching on caller type.
    """
    # Path 1: shared AuthMiddleware built a full PartnerContext for any auth method
    partner_ctx: PartnerContext | None = getattr(request.state, "partner", None)
    if partner_ctx is not None:
        return partner_ctx

    # Path 2: safety fallback — user set but partner not (shouldn't happen in prod)
    user: dict | None = getattr(request.state, "user", None)
    if user is not None:
        return PartnerContext(
            partner_id   = user.get("uid", ""),
            auth_method  = "firebase_jwt",
            partner_name = user.get("email", ""),
            raw_claims   = user,
        )

    # No auth succeeded
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error":   "UNAUTHORIZED",
            "message": (
                "Not authenticated. "
                "Staff: provide Authorization: Bearer <firebase-id-token>. "
                "Partners: provide X-API-Key."
            ),
            "details": [],
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


def is_staff_caller(partner: PartnerContext) -> bool:
    """
    Returns True if the caller is an authenticated staff member (Firebase JWT
    or API Gateway), False if they are a marketing partner (X-API-Key).

    Usage in route handlers:
        if is_staff_caller(partner):
            marketing_source = f"staff:{partner.partner_id}"
    """
    return partner.auth_method in ("gateway", "firebase_jwt")