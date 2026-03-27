import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


async def verify_token(token: str) -> dict | None:
    """
    Replace this with your actual token verification logic.
    e.g. JWT decode, DB lookup, or call to an auth service.
    Returns a user dict with roles, or None if invalid.
    """
    if not token:
        return None
    # Example: return {"id": "user-123", "roles": ["viewer", "uploader"]}
    return {"id": "user-placeholder", "roles": ["viewer"]}


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Validates Bearer token from the Authorization header.
    Attaches the resolved user to request.state.user.
    Enforces RBAC — required for download URLs per SITO-444.
    """

    EXCLUDED_PATHS = {"/health", "/docs", "/openapi.json"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse({"error": "Unauthorized: missing or invalid token"}, status_code=401)

        token = auth_header.split(" ", 1)[1]
        user = await verify_token(token)

        if not user:
            logger.warning(f"Invalid token for path {request.url.path}")
            return JSONResponse({"error": "Forbidden: token validation failed"}, status_code=403)

        request.state.user = user
        logger.debug(f"Authenticated user {user['id']} for {request.url.path}")
        return await call_next(request)
