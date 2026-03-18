"""
api/services/duplicate_detection.py — Duplicate lead and idempotency detection.
"""
from __future__ import annotations
from typing import Optional
from google.cloud import firestore
from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)


async def detect_duplicate(email: str, phone: str, db: firestore.AsyncClient) -> Optional[str]:
    """Return existing case_id if email AND phone already exist, else None."""
    settings = get_settings()
    query = (
        db.collection(settings.firestore_cases_collection)
        .where("email", "==", email)
        .where("phone", "==", phone)
        .limit(1)
    )
    async for doc in query.stream():
        return doc.id
    return None


async def is_idempotent_retry(request_id: str, db: firestore.AsyncClient) -> Optional[str]:
    """Return existing case_id if this requestId was already processed."""
    settings = get_settings()
    query = (
        db.collection(settings.firestore_cases_collection)
        .where("requestId", "==", request_id)
        .limit(1)
    )
    async for doc in query.stream():
        return doc.id
    return None
