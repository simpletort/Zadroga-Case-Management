"""
services/firestore_client.py — Async Firestore client singleton.

Initialises Firestore once per process using the service account key
injected by Secret Manager.  Falls back to application default credentials
(ADC) when the key file is absent, which covers local dev with gcloud auth.

Uses google-cloud-firestore directly (not firebase_admin.firestore_async)
so that named databases (e.g. "simpletort-dev") are supported via the
`database` constructor argument.
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
    """Return Google credentials from service account key or ADC."""
    settings = get_settings()
    key_path = settings.firebase_service_account_key_path

    if os.path.exists(key_path):
        creds = google.oauth2.service_account.Credentials.from_service_account_file(
            key_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        logger.info("firestore_init_service_account", key_path=key_path)
        return creds

    # ADC — works in Cloud Run with the attached service account
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    logger.info("firestore_init_adc")
    return creds


def get_db() -> AsyncClient:
    """Return the process-level async Firestore client (lazy init)."""
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
