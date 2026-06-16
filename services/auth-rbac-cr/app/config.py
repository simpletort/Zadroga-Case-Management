from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gcp_project_id: str = "simpletort-zadroga-dev"
    firestore_database_id: str = "simpletort-dev"
    firebase_service_account_key_path: str = "/secrets/firebase-sa-key.json"
    environment: str = "production"
    log_level: str = "INFO"
    trusted_service_accounts: list[str] = []
    email_provider: str = ""
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "noreply@simpletort.com"
    mailgun_api_key: str = ""
    mailgun_domain: str = ""
    mailgun_from_email: str = ""
    rbac_cache_ttl: int = 300

    model_config = {"env_file": ".env", "case_sensitive": False}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
