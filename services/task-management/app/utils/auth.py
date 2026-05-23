from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth as firebase_auth
import logging

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer()

ROLE_HIERARCHY = {
    "admin_staff":    1,
    "paralegal":      2,
    "junior_partner": 3,
    "senior_partner": 4,
    "system_admin":   5,
}

ENDPOINT_MIN_ROLES = {
    "task_create":       "admin_staff",
    "task_read":         "admin_staff",
    "task_update":       "admin_staff",
    "task_complete":     "admin_staff",
    "task_start":        "admin_staff",
    "task_assign":       "paralegal",
    "task_assign_other": "junior_partner",
    "task_skip":         "junior_partner",
    "task_delete":       "senior_partner",
    "task_list_case":    "admin_staff",
    "task_list_own":     "admin_staff",
    "task_list_other":   "senior_partner",
}


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
) -> dict:
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
    def _check(user: dict = Security(get_current_user)):
        user_role = user.get("role", "")
        required_role = ENDPOINT_MIN_ROLES.get(endpoint_key, "senior_partner")
        user_level = ROLE_HIERARCHY.get(user_role, 0)
        required_level = ROLE_HIERARCHY.get(required_role, 99)

        if user_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This action requires at least '{}' access.".format(required_role),
            )
        return user

    return _check
