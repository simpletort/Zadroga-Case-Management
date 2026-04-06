"""
config.py — Pydantic-settings configuration for the Notification Service.

All values are read from environment variables (injected by Cloud Run or
Secret Manager). Provide defaults only for non-sensitive, environment-agnostic
settings. Secrets (Twilio credentials) must always come from the environment.
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

    # Firestore collection names (suffixed with -dev in non-prod)
    sms_templates_collection: str = Field(
        "sms_templates", alias="FIRESTORE_SMS_TEMPLATES_COLLECTION"
    )
    opt_outs_collection: str = Field(
        "notification_opt_outs", alias="FIRESTORE_OPT_OUTS_COLLECTION"
    )
    delivery_records_collection: str = Field(
        "sms_delivery_records", alias="FIRESTORE_DELIVERY_RECORDS_COLLECTION"
    )
    cases_collection: str = Field(
        "cases", alias="FIRESTORE_CASES_COLLECTION"
    )

    # ── Twilio ────────────────────────────────────────────────────────────
    twilio_account_sid: str = Field(..., alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str = Field(..., alias="TWILIO_AUTH_TOKEN")
    twilio_from_number: str = Field(..., alias="TWILIO_FROM_NUMBER")

    # ── Cloud Tasks ───────────────────────────────────────────────────────
    cloud_tasks_queue: str = Field("sms-dispatch", alias="CLOUD_TASKS_QUEUE")
    cloud_tasks_queue_region: str = Field("us-east1", alias="CLOUD_TASKS_QUEUE_REGION")
    # Full URL of this notification service (used as the Cloud Tasks handler URL)
    notification_service_url: str = Field(
        "https://notification-service-prod-uc.a.run.app",
        alias="NOTIFICATION_SERVICE_URL",
    )
    # Service account for Cloud Tasks OIDC token
    notification_sa_email: str = Field(
        "notification-sa@simpletort-prod.iam.gserviceaccount.com",
        alias="NOTIFICATION_SA_EMAIL",
    )

    # ── SMS limits ────────────────────────────────────────────────────────
    # GSM-7 single-segment limit; beyond this Twilio auto-concatenates.
    sms_single_segment_chars: int = Field(160, alias="SMS_SINGLE_SEGMENT_CHARS")
    # Soft cap: refuse to send messages beyond this length (runaway templates).
    sms_max_chars: int = Field(1600, alias="SMS_MAX_CHARS")

    model_config = {"populate_by_name": True, "env_file": ".env", "extra": "ignore"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
