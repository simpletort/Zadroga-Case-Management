import time
import hmac
import hashlib
import logging
import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# SITO-444: Upload URLs expire in 15 min, download URLs expire in 1 hour
UPLOAD_EXPIRY_SECONDS = 15 * 60       # 15 minutes
DOWNLOAD_EXPIRY_SECONDS = 60 * 60     # 1 hour

SIGNED_URL_SECRET = os.getenv("SIGNED_URL_SECRET", "change-me-in-production")


def generate_signed_url(base_url: str, url_type: str = "download") -> dict:
    """
    Helper to generate a signed URL with expiry.
    url_type: 'upload' (15 min) or 'download' (1 hour)
    """
    expiry = UPLOAD_EXPIRY_SECONDS if url_type == "upload" else DOWNLOAD_EXPIRY_SECONDS
    expires_at = int(time.time()) + expiry

    payload = f"{base_url}:{expires_at}"
    signature = hmac.new(
        SIGNED_URL_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()

    return {
        "url": f"{base_url}?expires={expires_at}&signature={signature}",
        "expires_at": expires_at,
        "type": url_type,
    }


class SignedURLExpiryMiddleware(BaseHTTPMiddleware):
    """
    Validates signed URL expiry and HMAC signature on incoming requests.
    Per SITO-444: Upload URLs expire in 15 min, download URLs in 1 hour.
    Only checks requests that contain 'expires' and 'signature' query params.
    """

    async def dispatch(self, request: Request, call_next):
        expires = request.query_params.get("expires")
        signature = request.query_params.get("signature")

        if expires and signature:
            try:
                expires_ts = int(expires)
            except ValueError:
                return JSONResponse({"error": "Invalid expires parameter"}, status_code=400)

            if int(time.time()) > expires_ts:
                logger.warning(f"Expired signed URL accessed: {request.url.path}")
                return JSONResponse(
                    {"error": "This signed URL has expired. Please request a new one."},
                    status_code=410,
                )

            # Verify HMAC signature
            base_url = str(request.url).split("?")[0]
            payload = f"{base_url}:{expires}"
            expected_sig = hmac.new(
                SIGNED_URL_SECRET.encode(), payload.encode(), hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(expected_sig, signature):
                logger.warning(f"Invalid signature for signed URL: {request.url.path}")
                return JSONResponse({"error": "Invalid URL signature"}, status_code=403)

        return await call_next(request)
