from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import field_validator
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

    @field_validator("trusted_service_accounts", mode="before")
    @classmethod
    def _parse_string_list(cls, v: Any) -> Any:
        """
        Allow the env var to be either a JSON array or a comma-separated
        string.  An empty string (e.g. from an unset Cloud Build substitution)
        is treated as an empty list rather than raising a ValidationError.
        """
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            # Try JSON first ("[]", "[\"a\",\"b\"]")
            import json
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass
            # Fall back to comma-separated
            return [item.strip() for item in v.split(",") if item.strip()]
        return v


@lru_cache()
def get_settings() -> Settings:
    return Settings()
