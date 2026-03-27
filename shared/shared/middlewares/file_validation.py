import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# SITO-444: Allowed content types for uploads
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
}

# SITO-444: 25MB max file size
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024


class FileValidationMiddleware(BaseHTTPMiddleware):
    """
    Enforces content-type restrictions and file size limits on upload requests.
    Per SITO-444: Allowed types are PDF, JPG, PNG, DOCX. Max size is 25MB.
    Only applies to POST/PUT requests.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT"):
            content_type = request.headers.get("content-type", "").split(";")[0].strip()
            content_length = int(request.headers.get("content-length", 0))

            if content_type and content_type not in ALLOWED_CONTENT_TYPES:
                logger.warning(f"Rejected unsupported content-type: {content_type}")
                return JSONResponse(
                    {
                        "error": f"Unsupported file type: '{content_type}'.",
                        "allowed_types": list(ALLOWED_CONTENT_TYPES),
                    },
                    status_code=415,
                )

            if content_length > MAX_FILE_SIZE_BYTES:
                logger.warning(f"Rejected oversized upload: {content_length} bytes")
                return JSONResponse(
                    {
                        "error": f"File size {content_length} bytes exceeds the 25MB limit.",
                        "max_size_bytes": MAX_FILE_SIZE_BYTES,
                    },
                    status_code=413,
                )

        return await call_next(request)
