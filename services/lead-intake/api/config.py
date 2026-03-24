"""
api/config.py — Application settings via pydantic-settings.
All config loaded from environment variables / Secret Manager mounts.
"""
from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── GCP ──────────────────────────────────────────────────────────────────
    gcp_project_id: str = "simpletort-zadroga-dev"
    app_env: str = "development"           # development | staging | production

    # ── Firestore ─────────────────────────────────────────────────────────────
    firestore_cases_collection: str = "cases"
    firestore_counters_collection: str = "counters"
    firestore_partners_collection: str = "partners"
    firestore_request_logs_collection: str = "request_logs"

    # ── JWT Auth ──────────────────────────────────────────────────────────────
    jwks_uri: str = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
    jwt_audience: str = ""
    jwt_issuer: str = ""

    # ── API Key Auth ──────────────────────────────────────────────────────────
    hmac_signature_max_age_seconds: int = 300   # 5 minutes

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60

    # ── Cloud Tasks ───────────────────────────────────────────────────────────
    cloud_tasks_queue: str = "lead-followup-queue"
    cloud_tasks_location: str = "us-central1"
    cloud_tasks_handler_url: str = ""       # Cloud Run service URL (no trailing slash)
    cloud_tasks_sa_email: str = ""
    cloud_tasks_sms_queue: str = "sms-dispatch"
    cloud_tasks_email_queue: str = "email-dispatch"
    followup_delay_hours: int = 48

    # ── Notifications ─────────────────────────────────────────────────────────
    # When set, notifications are enqueued to the notification service via Cloud Tasks.
    # When unset (dev), direct SendGrid/Twilio calls are used as fallback.
    notification_service_url: str = ""
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "noreply@simpletort-zadroga-dev.firebaseapp.com"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    # ── Pub/Sub ───────────────────────────────────────────────────────────────
    pubsub_lead_created_topic: str = "lead-created"
    pubsub_lead_screened_topic: str = "lead-screened"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
