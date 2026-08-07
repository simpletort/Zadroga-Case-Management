import os
from pydantic_settings import BaseSettings
from functools import lru_cache

# In Cloud Run, env vars are set directly — no .env file is read.
# Locally, select the env file by setting ENVIRONMENT before starting:
#   ENVIRONMENT=dev uvicorn main:app --reload
_ENV = os.getenv("ENVIRONMENT", "production")
_ENV_FILE = f".env.{_ENV}" if _ENV != "production" else ".env.production"


class Settings(BaseSettings):
    gcp_project_id: str = "simpletort-prod"
    firestore_database_id: str = "simpletort-dev"
    environment: str = "production"
    log_level: str = "INFO"
    # Comma-separated service account emails allowed to call this service via OIDC
    trusted_service_accounts: str = ""

    model_config = {"env_file": _ENV_FILE, "case_sensitive": False}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
