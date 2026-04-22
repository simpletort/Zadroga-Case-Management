"""
middleware/auth.py — JWT authentication for the Enrollment Workflow Service.

Verifies Firebase / Google Identity Platform Bearer tokens.
Skipped in development for easier local testing.
"""

from __future__ import annotations

import logging
from typing import Optional

import google.auth.transport.requests
import google.oauth2.id_token
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import get_settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)
_google_request = google.auth.transport.requests.Request()


class StaffUser:
    """Authenticated staff user extracted from JWT claims."""

    def __init__(self, uid: str, email: str, role: str = "", name: str = ""):
        self.uid = uid
        self.email = email
        self.role = role
        self.name = name

    def __repr__(self) -> str:
        return f"StaffUser(uid={self.uid}, role={self.role})"


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> StaffUser:
    """
    FastAPI dependency: verify Bearer JWT and return authenticated user.
    In development, returns a mock system user (no auth required).
    """
    settings = get_settings()

    if not settings.is_production:
        return StaffUser(uid="dev-user", email="dev@zadlegal.com", role="admin_staff", name="Dev User")

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    token = credentials.credentials
    try:
        id_info = google.oauth2.id_token.verify_firebase_token(
            token,
            _google_request,
            audience=settings.jwt_audience,
        )
    except Exception as exc:
        logger.warning("jwt_verification_failed error=%s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    return StaffUser(
        uid=id_info.get("uid") or id_info.get("sub", ""),
        email=id_info.get("email", ""),
        role=id_info.get("role", ""),
        name=id_info.get("name", ""),
    )


def require_paralegal_or_above(current_user: StaffUser = Depends(get_current_user)) -> StaffUser:
    allowed = {"paralegal", "admin_staff", "junior_partner", "senior_partner", "system_admin"}
    if current_user.role not in allowed and get_settings().is_production:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return current_user
