import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """
    Global error handler for all unhandled exceptions.
    Returns structured JSON error responses instead of raw 500s.
    Used across all services.
    """

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except ValueError as e:
            logger.warning(f"Validation error on {request.url.path}: {e}")
            return JSONResponse({"error": str(e)}, status_code=400)
        except PermissionError as e:
            logger.warning(f"Permission denied on {request.url.path}: {e}")
            return JSONResponse({"error": str(e)}, status_code=403)
        except FileNotFoundError as e:
            logger.warning(f"Resource not found on {request.url.path}: {e}")
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            logger.exception(f"Unhandled error on {request.url.path}: {e}")
            return JSONResponse({"error": "An internal server error occurred."}, status_code=500)
