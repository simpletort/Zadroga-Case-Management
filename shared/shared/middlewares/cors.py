"""
shared/middlewares/cors.py — Canonical CORS origin list for all SimpleTort services.
"""

from __future__ import annotations

_PROD_ORIGINS = [
    "https://staff.simpletort.com",
]

_DEV_EXTRAS = [
    "https://simpletort-zadroga-dev.web.app",
    "https://simpletort.web.app",
    "http://localhost:3000",
    "http://localhost:5173",
]


def get_cors_origins(environment: str) -> list[str]:
    """Return the allowed CORS origins for the given environment."""
    if environment == "production":
        return list(_PROD_ORIGINS)
    return _PROD_ORIGINS + _DEV_EXTRAS
