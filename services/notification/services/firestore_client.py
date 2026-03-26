"""
services/firestore_client.py — Async Firestore client singleton.

Initialises Firebase/Firestore once per process using the service account key
injected by Secret Manager.  Falls back to application default credentials
(ADC) when the key file is absent, which covers local dev with gcloud auth.
"""
from __future__ import annotations

import os
from typing import Optional

import firebase_admin
from firebase_admin import credentials, firestore_async
from google.cloud.firestore_v1.async_client import AsyncClient

from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)

_db: Optional[AsyncClient] = None


def _init_firebase() -> None:
    """Initialise the Firebase Admin SDK if not already done."""
    if firebase_admin._apps:
        return

    settings = get_settings()
    key_path = settings.firebase_service_account_key_path

    if os.path.exists(key_path):
        cred = credentials.Certificate(key_path)
        logger.info("firebase_init_service_account", key_path=key_path)
    else:
        # Use ADC — works in Cloud Run with a properly configured service account
        cred = credentials.ApplicationDefault()
        logger.info("firebase_init_adc")

    firebase_admin.initialize_app(cred, {"projectId": settings.gcp_project_id})


def get_db() -> AsyncClient:
    """Return the process-level async Firestore client (lazy init)."""
    global _db
    if _db is None:
        _init_firebase()
        settings = get_settings()
        _db = firestore_async.client(database=settings.firestore_database_id)
        logger.info(
            "firestore_client_created",
            database=settings.firestore_database_id,
        )
    return _db
