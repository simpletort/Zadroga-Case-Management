"""
services/firestore_client.py — Async Firestore client singleton.

Follows the same pattern as the notification service: prefers a service-account
key file when present, falls back to Application Default Credentials (ADC) for
Cloud Run and local `gcloud auth application-default login` workflows.
"""
from __future__ import annotations

import os
from typing import Optional

import google.auth
import google.oauth2.service_account
from google.cloud.firestore_v1.async_client import AsyncClient

from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)

_db: Optional[AsyncClient] = None


def _get_credentials():
    settings = get_settings()
    key_path = settings.firebase_service_account_key_path

    if os.path.exists(key_path):
        creds = google.oauth2.service_account.Credentials.from_service_account_file(
            key_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        logger.info("firestore_init_service_account", key_path=key_path)
        return creds

    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    logger.info("firestore_init_adc")
    return creds


def get_db() -> AsyncClient:
    """Return the process-level async Firestore client (lazy singleton)."""
    global _db
    if _db is None:
        settings = get_settings()
        creds = _get_credentials()
        _db = AsyncClient(
            project=settings.gcp_project_id,
            credentials=creds,
            database=settings.firestore_database_id,
        )
        logger.info(
            "firestore_client_created",
            project=settings.gcp_project_id,
            database=settings.firestore_database_id,
        )
    return _db
