"""
api/config.py — Application settings via pydantic-settings.
All config loaded from environment variables / Secret Manager.
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
    gcp_project_id: str = "zad-lead-intake"
    app_env: str = "development"  # development | staging | production

    # ── Firestore ─────────────────────────────────────────────────────────────
    firestore_cases_collection: str = "cases"
    firestore_counters_collection: str = "counters"
    firestore_partners_collection: str = "partners"
    firestore_api_keys_collection: str = "api_keys"
    firestore_request_logs_collection: str = "request_logs"

    # ── JWT Auth ──────────────────────────────────────────────────────────────
    jwks_uri: str = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
    jwt_audience: str = ""
    jwt_issuer: str = ""

    # ── API Key Auth ──────────────────────────────────────────────────────────
    partner_auth_enabled: bool = True
    hmac_signature_max_age_seconds: int = 300  # 5 minutes

    # ── VCF Window ────────────────────────────────────────────────────────────
    vcf_window_start: str = "2001-09-11"
    vcf_window_end: str = "2011-05-30"

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60

    # ── Cloud Tasks ───────────────────────────────────────────────────────────
    cloud_tasks_queue: str = "lead-followup-queue"
    cloud_tasks_location: str = "us-central1"
    cloud_tasks_handler_url: str = ""
    cloud_tasks_sa_email: str = ""
    followup_delay_hours: int = 48

    # ── Notifications ─────────────────────────────────────────────────────────
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "noreply@zadlegal.com"
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
