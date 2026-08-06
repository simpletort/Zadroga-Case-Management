import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Prevent Firebase/Firestore init during import
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("ENVIRONMENT", "test")

# ---------------------------------------------------------------------------
# Stub out heavy third-party packages that are not installed in the test env
# or that would attempt real network calls on import.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Shared middleware package — stub with a proper ASGI pass-through so that
# Starlette / FastAPI can await the middleware callable during requests.
# ---------------------------------------------------------------------------

class _NoopMiddleware:
    """Minimal ASGI middleware that delegates straight to the wrapped app."""
    def __init__(self, app, **kwargs):
        self.app = app

    async def __call__(self, scope, receive, send):
        await self.app(scope, receive, send)


def _get_cors_origins_stub(environment: str, gcp_project_id: str) -> list[str]:
    return ["http://localhost:3000"]


_shared_auth_mod = MagicMock()
_shared_auth_mod.AuthMiddleware = _NoopMiddleware

_shared_cors_mod = MagicMock()
_shared_cors_mod.get_cors_origins = _get_cors_origins_stub

_shared_error_handler_mod = MagicMock()
_shared_error_handler_mod.ErrorHandlerMiddleware = _NoopMiddleware

_shared_logging_mod = MagicMock()
_shared_logging_mod.LoggingMiddleware = _NoopMiddleware

_shared_middlewares_mod = MagicMock()
_shared_middlewares_mod.AuthMiddleware = _NoopMiddleware
_shared_middlewares_mod.get_cors_origins = _get_cors_origins_stub
_shared_middlewares_mod.ErrorHandlerMiddleware = _NoopMiddleware
_shared_middlewares_mod.LoggingMiddleware = _NoopMiddleware
_shared_middlewares_mod.auth = _shared_auth_mod
_shared_middlewares_mod.cors = _shared_cors_mod
_shared_middlewares_mod.error_handler = _shared_error_handler_mod
_shared_middlewares_mod.logging = _shared_logging_mod

_shared_mod = MagicMock()
_shared_mod.middlewares = _shared_middlewares_mod

sys.modules.setdefault("shared", _shared_mod)
sys.modules.setdefault("shared.middlewares", _shared_middlewares_mod)
sys.modules.setdefault("shared.middlewares.auth", _shared_auth_mod)
sys.modules.setdefault("shared.middlewares.cors", _shared_cors_mod)
sys.modules.setdefault("shared.middlewares.error_handler", _shared_error_handler_mod)
sys.modules.setdefault("shared.middlewares.logging", _shared_logging_mod)

# Google Cloud / Firebase stubs — prevent real SDK init during module import.
# Actual Firestore / Firebase Auth calls are individually mocked in each test.
for _mod in (
    "google",
    "google.cloud",
    "google.cloud.firestore",
    "google.cloud.firestore_v1",
    "firebase_admin",
    "firebase_admin.auth",
    "firebase_admin.credentials",
):
    sys.modules.setdefault(_mod, MagicMock())

# Pre-import app.utils.firestore so that unittest.mock.patch can resolve the
# dotted name "app.utils.firestore.get_firestore_client" via pkgutil.resolve_name
# (which does getattr(app.utils, 'firestore') and requires the submodule to
# already be registered as an attribute of the package).
import app.utils.firestore  # noqa: E402 — must come after sys.modules stubs above
