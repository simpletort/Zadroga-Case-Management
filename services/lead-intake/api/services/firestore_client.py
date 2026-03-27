"""
api/services/firestore_client.py — Async Firestore client singleton.
"""
from __future__ import annotations
from typing import Optional
from google.cloud import firestore
from config import get_settings

_db: Optional[firestore.AsyncClient] = None


def get_db() -> firestore.AsyncClient:
    global _db
    if _db is None:
        settings = get_settings()
        _db = firestore.AsyncClient(project=settings.gcp_project_id, database="simpletort-dev")
    return _db
