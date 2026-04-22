"""
firestore_client.py — Singleton Firestore client for the Enrollment Workflow Service.

Uses AsyncClient so dashboard routes (which are async def) can call
.stream() and .get() without blocking the event loop.
"""

from __future__ import annotations

import os

from google.cloud.firestore_v1.async_client import AsyncClient

_db: AsyncClient | None = None

GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
FIRESTORE_DATABASE_ID = os.environ.get("FIRESTORE_DATABASE_ID", "simpletort-dev")


def get_db() -> AsyncClient:
    global _db
    if _db is None:
        _db = AsyncClient(
            project=GCP_PROJECT_ID or None,
            database=FIRESTORE_DATABASE_ID or None,
        )
    return _db