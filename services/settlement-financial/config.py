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
    gcp_project_id: str = Field("simpletort-prod", alias="GCP_PROJECT_ID")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    # ── Firestore ─────────────────────────────────────────────────────────
    firestore_database_id: str = Field("(default)", alias="FIRESTORE_DATABASE_ID")
    firebase_service_account_key_path: str = Field(
        "/secrets/firebase-sa-key.json",
        alias="FIREBASE_SA_KEY_PATH",
    )

    # Firestore collection name for saved calculations
    settlement_calculations_collection: str = Field(
        "settlement_calculations",
        alias="FIRESTORE_SETTLEMENT_CALCULATIONS_COLLECTION",
    )

    model_config = {"populate_by_name": True, "env_file": ".env", "extra": "ignore"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
