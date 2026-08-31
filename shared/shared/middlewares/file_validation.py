"""
shared/middlewares/file_validation.py — File type and size validation middleware.

Checks every multipart/form-data upload field:
  - Extension must be in ALLOWED_EXTENSIONS (case-insensitive)
  - Body must not exceed MAX_FILE_SIZE_BYTES (50 MB)

Rejects with HTTP 415 and JSON {"error": ..., "detail": ...} on any violation.
Non-multipart requests pass through untouched.
"""

from __future__ import annotations

import os

from starlette.datastructures import UploadFile
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

MB = 1024 * 1024
MAX_FILE_SIZE_BYTES = 50 * MB

ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {"pdf", "jpg", "jpeg", "png", "docx", "tiff", "xlsx", "csv"}
)


def validate_file_extension(file_name: str) -> None:
    """Raise HTTP 415 if the file extension is not in ALLOWED_EXTENSIONS."""
    import os
    from fastapi import HTTPException
    ext = os.path.splitext(file_name)[1].lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"File type '.{ext}' is not allowed. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )


def _reject(error: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=415,
        content={"error": error, "detail": detail},
    )


class FileValidationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" not in content_type:
            return await call_next(request)

        form = await request.form()
        for _, field_value in form.multi_items():
            if not isinstance(field_value, UploadFile):
                continue

            ext = os.path.splitext(field_value.filename or "")[1].lstrip(".").lower()
            if ext not in ALLOWED_EXTENSIONS:
                return _reject(
                    "Unsupported file type",
                    f"Extension '.{ext}' is not allowed. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
                )

            content = await field_value.read()
            if len(content) > MAX_FILE_SIZE_BYTES:
                return _reject(
                    "File too large",
                    f"File exceeds the 50 MB limit ({len(content) // MB} MB uploaded).",
                )

            await field_value.seek(0)

        return await call_next(request)
