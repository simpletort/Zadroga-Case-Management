import base64
import json
import sys
from typing import Optional

from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth as firebase_auth
import logging

from app.utils.roles import normalize_role

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
    "case_assign_override":  "admin_staff",
    "case_assignment_read":  "paralegal",
    "workload_view":         "paralegal",
    "dashboard_view":        "paralegal",
    "comm_read":             "paralegal",
    "comm_write":            "paralegal",
    "review_preflight":      "paralegal",
    "review_submit":         "paralegal",
    "search_view":           "paralegal",
    "attorney_review_queue": "junior_partner",
    "attorney_approve":      "junior_partner",
    "attorney_bulk_approve": "junior_partner",
    "case_escalate":         "junior_partner",
    "escalation_queue":      "senior_partner",
    "escalation_decide":     "senior_partner",
    "case_reject":           "junior_partner",
    "case_resubmit":         "paralegal",
}


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = None,
) -> dict:
    """Verify auth and return the decoded claims dict.

    When called via Google Cloud API Gateway the original Firebase token is
    replaced by a Google-signed OIDC token.  The gateway forwards the already-
    verified Firebase JWT payload in the X-Apigateway-Api-Userinfo header
    (Base64URL-encoded JSON).  Read from that header first so we don't
    double-verify using the wrong token type.
    """
    userinfo = request.headers.get("x-apigateway-api-userinfo")
    if userinfo:
        try:
            padded = userinfo + "=" * (-len(userinfo) % 4)
            claims = json.loads(base64.urlsafe_b64decode(padded))
            # Firebase Admin SDK adds 'uid' mapped from 'sub'/'user_id'.
            # The raw JWT payload uses 'sub'/'user_id' — normalise so callers
            # can always use claims["uid"].
            if "uid" not in claims:
                claims["uid"] = claims.get("sub") or claims.get("user_id", "")
            return claims
        except Exception as e:
            logger.error("Failed to decode X-Apigateway-Api-Userinfo: %s", e)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid gateway auth header.",
            )

    # Direct call (no gateway) — verify the Firebase ID token normally.
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
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    ) -> dict:
        # Dynamic module lookup — picks up any patch applied to the attribute.
        _get_user = sys.modules[__name__].get_current_user
        user = _get_user(request, credentials)

        user_role     = normalize_role(user.get("role", ""))
        required_role = ENDPOINT_MIN_ROLES.get(endpoint_key, "senior_partner")
        user_level    = ROLE_HIERARCHY.get(user_role, 0)
        required_level = ROLE_HIERARCHY.get(required_role, 99)
        logger.info

        if user_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This action requires at least '{}' (level {}) access. Current role: '{}', Current level: {}".format(required_role, required_level, user_role, user_level),
            )
        return user

    return _check
