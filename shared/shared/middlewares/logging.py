import time
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs all incoming requests and outgoing responses with duration.
    Used across all services.
    """

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        user_id = getattr(getattr(request, "state", None), "user", {})
        user_id = user_id.get("id", "anonymous") if isinstance(user_id, dict) else "anonymous"

        logger.info(f"--> {request.method} {request.url.path} [user={user_id}]")

        response = await call_next(request)

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            f"<-- {request.method} {request.url.path} "
            f"status={response.status_code} duration={duration_ms:.1f}ms"
        )
        return response
