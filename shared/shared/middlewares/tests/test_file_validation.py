"""
Tests for FileValidationMiddleware.

Rules under test:
  - Allowed extensions: pdf, jpg, jpeg, png, docx, tiff
  - Max body size: 50 MB
  - Rejection → 415 with JSON body {"error": ..., "detail": ...}
  - Non-multipart requests pass through untouched
  - Valid files pass through untouched
"""

from __future__ import annotations

import io

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
    return {"file": (filename, io.BytesIO(content), mime)}


# ---------------------------------------------------------------------------
# Non-multipart requests pass through
# ---------------------------------------------------------------------------

class TestNonMultipart:
    def test_get_request_passes_through(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_json_post_passes_through(self, client):
        resp = client.post("/upload", json={"key": "value"})
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
        resp = client.post("/upload", files=_multipart(filename, b"x" * 100, mime))
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_max_size_boundary_passes(self, client):
        resp = client.post("/upload", files=_multipart("big.pdf", b"a" * MAX_FILE_SIZE_BYTES))
        assert resp.status_code == 200

    def test_bytes_content_irrelevant_for_valid_extension(self, client):
        """No MIME sniffing — any bytes in a .pdf are accepted."""
        resp = client.post("/upload", files=_multipart("doc.pdf", b"PK\x03\x04notreallypdf"))
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
        "file.pdf.exe",
    ])
    def test_disallowed_extension_returns_415(self, client, filename):
        resp = client.post("/upload", files=_multipart(filename, b"data"))
        assert resp.status_code == 415
        body = resp.json()
        assert "error" in body
        assert "detail" in body

    def test_no_extension_returns_415(self, client):
        resp = client.post("/upload", files=_multipart("filewithnoext", b"data"))
        assert resp.status_code == 415

    def test_uppercase_extension_allowed(self, client):
        resp = client.post("/upload", files=_multipart("REPORT.PDF", b"x" * 10))
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Size validation
# ---------------------------------------------------------------------------

class TestSizeRejection:
    def test_oversized_file_returns_415(self, client):
        content = b"a" * (MAX_FILE_SIZE_BYTES + 1)
        resp = client.post("/upload", files=_multipart("big.pdf", content))
        assert resp.status_code == 415
        body = resp.json()
        assert "error" in body
        assert "detail" in body

    def test_50mb_plus_one_byte_rejected(self, client):
        content = b"z" * (50 * MB + 1)
        resp = client.post("/upload", files=_multipart("huge.pdf", content))
        assert resp.status_code == 415


# ---------------------------------------------------------------------------
# Error body shape
# ---------------------------------------------------------------------------

class TestErrorBody:
    def test_error_body_has_required_keys(self, client):
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
        resp = client.post("/upload", files=_multipart("big.pdf", content))
        assert resp.status_code == 415
        body = resp.json()
        assert "50" in body["detail"] or "MB" in body["detail"]

    def test_extension_error_mentions_allowed_list(self, client):
        resp = client.post("/upload", files=_multipart("bad.exe", b"MZ"))
        assert resp.status_code == 415
        body = resp.json()
        assert any(ext in body["detail"] for ext in ALLOWED_EXTENSIONS)
