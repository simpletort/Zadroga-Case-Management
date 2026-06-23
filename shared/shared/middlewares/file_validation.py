"""
shared/middlewares/file_validation.py — File type and size validation middleware.

Dependency note: requires `python-magic` (listed in pyproject.toml).
On Windows, also install `python-magic-bin` which bundles the libmagic DLL:
    pip install python-magic-bin

Checks every multipart/form-data upload field:
  - Extension must be in ALLOWED_EXTENSIONS (case-insensitive)
  - python-magic detected MIME type must be in ALLOWED_MIME_TYPES
  - Body must not exceed MAX_FILE_SIZE_BYTES (50 MB)

Rejects with HTTP 415 and JSON {"error": ..., "detail": ...} on any violation.
Non-multipart requests pass through untouched.
"""

from __future__ import annotations

import os

import magic
from starlette.datastructures import UploadFile
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

MB = 1024 * 1024
MAX_FILE_SIZE_BYTES = 50 * MB

ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {"pdf", "jpg", "jpeg", "png", "docx", "tiff"}
)

ALLOWED_MIME_TYPES: frozenset[str] = frozenset({
    "application/pdf",
    "image/jpeg",
    "image/png",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/tiff",
})

_MAGIC_SAMPLE_BYTES = 2048


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
        for field_name, field_value in form.multi_items():
            if not isinstance(field_value, UploadFile):
                continue

            # --- Extension check ---
            ext = os.path.splitext(field_value.filename or "")[1].lstrip(".").lower()
            if ext not in ALLOWED_EXTENSIONS:
                return _reject(
                    "Unsupported file type",
                    f"Extension '.{ext}' is not allowed. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
                )

            # --- Read content for size + MIME checks ---
            content = await field_value.read()

            # --- Size check ---
            if len(content) > MAX_FILE_SIZE_BYTES:
                return _reject(
                    "File too large",
                    f"File exceeds the 50 MB limit ({len(content) // MB} MB uploaded).",
                )

            # --- MIME type check via python-magic ---
            detected_mime = magic.from_buffer(content[:_MAGIC_SAMPLE_BYTES], mime=True)
            if detected_mime not in ALLOWED_MIME_TYPES:
                return _reject(
                    "Unsupported media type",
                    f"Detected MIME type '{detected_mime}' is not allowed.",
                )

            # Rewind so the route handler can read the file
            await field_value.seek(0)

        return await call_next(request)
