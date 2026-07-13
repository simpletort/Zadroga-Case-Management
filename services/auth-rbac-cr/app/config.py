from __future__ import annotations

import json
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gcp_project_id: str = Field(alias="GCP_PROJECT_ID")
    firestore_database_id: str = "simpletort-dev"
    firebase_service_account_key_path: str = "/secrets/firebase-sa-key.json"
    environment: str = "production"
    log_level: str = "INFO"
    # Stored as a raw string, not list[str]. pydantic-settings treats list-typed
    # env fields as "complex" and tries to json.loads() the raw env var *before*
    # any field_validator runs — a comma-separated string or an empty string
    # (e.g. an unset Cloud Build substitution) isn't valid JSON, so that source-level
    # decode raises SettingsError and crashes the app at import time. Keeping this
    # as `str` skips that decode entirely; trusted_service_accounts (below) does the
    # JSON-or-comma-separated parsing safely after the value is already a plain string.
    trusted_service_accounts_raw: str = Field(default="", validation_alias="TRUSTED_SERVICE_ACCOUNTS")
    email_provider: str = ""
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "noreply@simpletort.com"
    mailgun_api_key: str = ""
    mailgun_domain: str = ""
    mailgun_from_email: str = ""
    rbac_cache_ttl: int = 300

    model_config = {"env_file": ".env", "case_sensitive": False, "populate_by_name": True}

    @property
    def trusted_service_accounts(self) -> list[str]:
        """
        Parse trusted_service_accounts_raw as either a JSON array or a
        comma-separated string. An empty/unset value yields an empty list.
        """
        v = self.trusted_service_accounts_raw.strip()
        if not v:
            return []
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass
        return [item.strip() for item in v.split(",") if item.strip()]


@lru_cache()
def get_settings() -> Settings:
    return Settings()
