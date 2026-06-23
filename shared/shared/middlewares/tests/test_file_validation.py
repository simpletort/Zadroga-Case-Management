"""
Tests for FileValidationMiddleware.

Rules under test:
  - Allowed extensions: pdf, jpg, jpeg, png, docx, tiff
  - python-magic MIME type must also match an allowed type
  - Max body size: 50 MB
  - Rejection → 415 with JSON body {"error": ..., "detail": ...}
  - Non-multipart requests pass through untouched
  - Valid files pass through untouched
"""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import JSONResponse

from shared.middlewares.file_validation import (
    MAX_FILE_SIZE_BYTES,
    ALLOWED_EXTENSIONS,
    FileValidationMiddleware,
)

MB = 1024 * 1024


# ---------------------------------------------------------------------------
# Minimal FastAPI app with the middleware and a catch-all upload endpoint
# ---------------------------------------------------------------------------

def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(FileValidationMiddleware)

    @app.post("/upload")
    async def upload(request: Request):
        form = await request.form()
        return JSONResponse({"ok": True})

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


@pytest.fixture()
def client():
    return TestClient(_make_app(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _multipart(filename: str, content: bytes, mime: str = "application/octet-stream"):
    """Build files= kwarg for TestClient.post."""
    return {"file": (filename, io.BytesIO(content), mime)}


def _magic_patch(mime: str):
    """Patch python-magic so tests don't depend on real magic bytes."""
    return patch("shared.middlewares.file_validation.magic.from_buffer", return_value=mime)


# ---------------------------------------------------------------------------
# Non-multipart requests pass through
# ---------------------------------------------------------------------------

class TestNonMultipart:
    def test_get_request_passes_through(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_json_post_passes_through(self, client):
        resp = client.post("/upload", json={"key": "value"})
        # No file field → endpoint returns 200 (form parse succeeds with no file key)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Valid files pass through
# ---------------------------------------------------------------------------

class TestValidFiles:
    @pytest.mark.parametrize("filename,mime", [
        ("report.pdf",  "application/pdf"),
        ("photo.jpg",   "image/jpeg"),
        ("photo.jpeg",  "image/jpeg"),
        ("scan.png",    "image/png"),
        ("letter.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("scan.tiff",   "image/tiff"),
    ])
    def test_allowed_file_passes(self, client, filename, mime):
        with _magic_patch(mime):
            resp = client.post("/upload", files=_multipart(filename, b"x" * 100, mime))
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_max_size_boundary_passes(self, client):
        content = b"a" * MAX_FILE_SIZE_BYTES
        with _magic_patch("application/pdf"):
            resp = client.post("/upload", files=_multipart("big.pdf", content, "application/pdf"))
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Extension validation
# ---------------------------------------------------------------------------

class TestExtensionRejection:
    @pytest.mark.parametrize("filename", [
        "malware.exe",
        "script.js",
        "archive.zip",
        "data.csv",
        "image.gif",
        "page.html",
        "file.pdf.exe",   # double extension — outer wins
    ])
    def test_disallowed_extension_returns_415(self, client, filename):
        with _magic_patch("application/octet-stream"):
            resp = client.post("/upload", files=_multipart(filename, b"data", "application/octet-stream"))
        assert resp.status_code == 415
        body = resp.json()
        assert "error" in body
        assert "detail" in body

    def test_no_extension_returns_415(self, client):
        with _magic_patch("application/octet-stream"):
            resp = client.post("/upload", files=_multipart("filewithnoext", b"data"))
        assert resp.status_code == 415
        body = resp.json()
        assert "error" in body
        assert "detail" in body

    def test_uppercase_extension_allowed(self, client):
        """Extension check is case-insensitive."""
        with _magic_patch("application/pdf"):
            resp = client.post("/upload", files=_multipart("REPORT.PDF", b"x" * 10, "application/pdf"))
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# MIME type validation (python-magic)
# ---------------------------------------------------------------------------

class TestMimeRejection:
    def test_mismatched_mime_returns_415(self, client):
        """Extension is .pdf but magic detects a different type."""
        with _magic_patch("application/zip"):
            resp = client.post("/upload", files=_multipart("disguised.pdf", b"PK\x03\x04fake"))
        assert resp.status_code == 415
        body = resp.json()
        assert "error" in body
        assert "detail" in body

    def test_html_content_in_pdf_returns_415(self, client):
        with _magic_patch("text/html"):
            resp = client.post("/upload", files=_multipart("page.pdf", b"<html></html>"))
        assert resp.status_code == 415

    def test_correct_mime_required_even_for_allowed_extension(self, client):
        """A .jpg with magic returning image/gif should be rejected."""
        with _magic_patch("image/gif"):
            resp = client.post("/upload", files=_multipart("photo.jpg", b"GIF89a"))
        assert resp.status_code == 415


# ---------------------------------------------------------------------------
# Size validation
# ---------------------------------------------------------------------------

class TestSizeRejection:
    def test_oversized_file_returns_415(self, client):
        content = b"a" * (MAX_FILE_SIZE_BYTES + 1)
        with _magic_patch("application/pdf"):
            resp = client.post("/upload", files=_multipart("big.pdf", content, "application/pdf"))
        assert resp.status_code == 415
        body = resp.json()
        assert "error" in body
        assert "detail" in body

    def test_50mb_plus_one_byte_rejected(self, client):
        content = b"z" * (50 * MB + 1)
        with _magic_patch("application/pdf"):
            resp = client.post("/upload", files=_multipart("huge.pdf", content, "application/pdf"))
        assert resp.status_code == 415


# ---------------------------------------------------------------------------
# Error body shape
# ---------------------------------------------------------------------------

class TestErrorBody:
    def test_error_body_has_required_keys(self, client):
        with _magic_patch("application/octet-stream"):
            resp = client.post("/upload", files=_multipart("bad.exe", b"MZ"))
        assert resp.status_code == 415
        body = resp.json()
        assert set(body.keys()) >= {"error", "detail"}
        assert isinstance(body["error"], str)
        assert isinstance(body["detail"], str)
        assert len(body["error"]) > 0
        assert len(body["detail"]) > 0

    def test_size_error_mentions_limit(self, client):
        content = b"x" * (MAX_FILE_SIZE_BYTES + 1)
        with _magic_patch("application/pdf"):
            resp = client.post("/upload", files=_multipart("big.pdf", content, "application/pdf"))
        assert resp.status_code == 415
        body = resp.json()
        # detail should tell the caller what the limit is
        assert "50" in body["detail"] or "MB" in body["detail"]

    def test_mime_error_mentions_type(self, client):
        with _magic_patch("application/zip"):
            resp = client.post("/upload", files=_multipart("bad.pdf", b"PK\x03\x04"))
        assert resp.status_code == 415
        body = resp.json()
        assert "application/zip" in body["detail"] or "MIME" in body["detail"]
