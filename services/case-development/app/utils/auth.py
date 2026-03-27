import sys
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth as firebase_auth
import logging

logger = logging.getLogger(__name__)

# auto_error=False so that a missing Authorization header yields None instead
# of an opaque 422/403 from Starlette; we raise the explicit 403 ourselves.
bearer_scheme = HTTPBearer(auto_error=False)

# Higher number == more authority.
ROLE_HIERARCHY = {
    "paralegal":      1,
    "admin_staff":    2,
    "junior_partner": 3,
    "senior_partner": 4,
    "system_admin":   5,
}

ENDPOINT_MIN_ROLES = {
    "case_assign_override": "admin_staff",
    "case_assignment_read": "paralegal",
    "workload_view":        "paralegal",
    "dashboard_view":       "paralegal",
}


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = None,
) -> dict:
    """Verify a Firebase ID token and return the decoded claims dict."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authenticated.",
        )
    token = credentials.credentials
    try:
        return firebase_auth.verify_id_token(token)
    except firebase_auth.ExpiredIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please re-authenticate.",
        )
    except firebase_auth.InvalidIdTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: {}".format(e),
        )
    except Exception as e:
        logger.error("Auth error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed.",
        )


def require_min_role(endpoint_key: str):
    """Return a FastAPI dependency that enforces a minimum role level.

    ``get_current_user`` is resolved through the module namespace at *call
    time* (not at import time) so that ``unittest.mock.patch`` on
    ``app.utils.auth.get_current_user`` works correctly in tests without
    needing ``app.dependency_overrides``.
    """
    def _check(
        credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    ) -> dict:
        # Dynamic module lookup — picks up any patch applied to the attribute.
        _get_user = sys.modules[__name__].get_current_user
        user = _get_user(credentials)

        user_role     = user.get("role", "")
        required_role = ENDPOINT_MIN_ROLES.get(endpoint_key, "senior_partner")
        user_level    = ROLE_HIERARCHY.get(user_role, 0)
        required_level = ROLE_HIERARCHY.get(required_role, 99)

        if user_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This action requires at least '{}' (level {}) access. Current role: '{}', Current level: {}".format(required_role, required_level, user_role, user_level),
            )
        return user

    return _check
