from __future__ import annotations

import logging
from functools import lru_cache

import firebase_admin
from firebase_admin import credentials
from google.cloud import firestore

from app.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache()
def get_firestore_client() -> firestore.Client:
    settings = get_settings()

    if not firebase_admin._apps:
        try:
            cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred, {"projectId": settings.gcp_project_id})
            logger.info("Firebase initialized with Application Default Credentials")
        except Exception as adc_exc:
            logger.warning("ADC init failed (%s) — falling back to service account key", adc_exc)
            cred = credentials.Certificate(settings.firebase_service_account_key_path)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase initialized with service account key")

    return firestore.Client(
        project=settings.gcp_project_id,
        database=settings.firestore_database_id,
    )
