"""
config.py — Pydantic-settings configuration for the Settlement Financial Service.

All values are read from environment variables injected by Cloud Run or
Secret Manager.  Defaults are suitable for local development only.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Runtime environment ───────────────────────────────────────────────
    app_env: str = Field("development", alias="APP_ENV")
    environment: str = Field("production", alias="ENVIRONMENT")
    gcp_project_id: str = Field("simpletort-zadroga-dev", alias="GCP_PROJECT_ID")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    # ── Firestore ─────────────────────────────────────────────────────────
    firestore_database_id: str = Field("(default)", alias="FIRESTORE_DATABASE_ID")
    firebase_service_account_key_path: str = Field(
        "/secrets/firebase-sa-key.json",
        alias="FIREBASE_SA_KEY_PATH",
    )

    # Roles Firestore database (for AuthMiddleware permission lookups)
    roles_firestore_database_id: str = Field("(default)", alias="ROLES_FIRESTORE_DATABASE_ID")

    # Comma-separated service account emails trusted for service-to-service OIDC calls
    trusted_service_accounts: str = Field("", alias="TRUSTED_SERVICE_ACCOUNTS")

    # Firestore collection name for saved calculations
    settlement_calculations_collection: str = Field(
        "settlement_calculations",
        alias="FIRESTORE_SETTLEMENT_CALCULATIONS_COLLECTION",
    )

    # ── Cloud Storage ─────────────────────────────────────────────────────
    gcs_bucket: str = Field("case-files-dev", alias="GCS_BUCKET")

    # Storage Gateway service URL (Cloud Run) — all case file ops go through here
    storage_gateway_url: str = Field("", alias="STORAGE_GATEWAY_URL")

    # ── Firm logo ─────────────────────────────────────────────────────────
    # Absolute path to the logo file on the container filesystem.
    # Mount it via Cloud Run volume or leave blank to use no logo.
    firm_logo_path: str = Field("", alias="FIRM_LOGO_PATH")

    model_config = {"populate_by_name": True, "env_file": ".env", "extra": "ignore"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
