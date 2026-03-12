from google.cloud import storage as gcs
from functools import lru_cache
from app.config import get_settings
import logging

logger = logging.getLogger(__name__)


@lru_cache()
def get_gcs_client() -> gcs.Client:
    settings = get_settings()
    client = gcs.Client(project=settings.gcp_project_id)
    logger.info("GCS client initialised for project %s", settings.gcp_project_id)
    return client
