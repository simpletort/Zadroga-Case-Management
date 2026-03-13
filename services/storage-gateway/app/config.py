from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gcp_project_id: str = "simpletort-prod"
    firestore_database_id: str = "(default)"
    firebase_service_account_key_path: str = "/secrets/firebase-sa-key.json"
    gcs_bucket_name: str = "zadroga-case-files-simpletort-prod"
    signed_url_write_expiry_minutes: int = 15
    signed_url_read_expiry_minutes: int = 60
    env: str = "prod"  # dev | test | prod — injected via ENV trigger variable
    log_level: str = "INFO"

    # Virus scanning — staging / quarantine prefixes
    gcs_staging_prefix: str = "staging"
    gcs_quarantine_prefix: str = "quarantine"

    # Pub/Sub topic for virus-detected notifications
    pubsub_topic_virus_detected: str = "virus-detected"

    model_config = {"env_file": ".env", "case_sensitive": False}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
