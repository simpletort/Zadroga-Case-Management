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
    firestore_database_id: str = "(default)"
    firebase_service_account_key_path: str = "/secrets/firebase-sa-key.json"
    environment: str = "production"
    log_level: str = "INFO"
    allowed_origins: str =  [
  "https://simpletort-zadroga-dev.web.app",
  "https://simpletort-zadroga-dev.firebaseapp.com"
]

    model_config = {"env_file": _ENV_FILE, "case_sensitive": False}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
