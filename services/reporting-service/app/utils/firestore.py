import firebase_admin
from firebase_admin import credentials
from google.cloud import firestore as gcp_firestore
from functools import lru_cache
from app.config import get_settings
import logging

logger = logging.getLogger(__name__)


@lru_cache()
def get_firestore_client():
    settings = get_settings()

    if not firebase_admin._apps:
        try:
            cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred, {"projectId": settings.gcp_project_id})
            logger.info("Firebase initialised with Application Default Credentials")
        except Exception:
            cred = credentials.Certificate(settings.firebase_service_account_key_path)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase initialised with service account key file")

    return gcp_firestore.Client(
        project=settings.gcp_project_id,
        database=settings.firestore_database_id,
    )
