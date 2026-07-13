from google.cloud import firestore as gcp_firestore
from functools import lru_cache
from app.config import get_settings
import logging

logger = logging.getLogger(__name__)


@lru_cache()
def get_firestore_client():
    settings = get_settings()
    return gcp_firestore.Client(
        project=settings.gcp_project_id,
        database=settings.firestore_database_id,
    )
