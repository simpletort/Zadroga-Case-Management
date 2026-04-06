"""
api/config.py — Application settings via pydantic-settings.

All messaging (SMS, email) is handled by the notification service.
lead-intake only publishes Pub/Sub events and writes to Firestore.
No SendGrid, Twilio, or notification_service_url fields here.
"""
from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="api/.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── GCP ──────────────────────────────────────────────────────────────────
    gcp_project_id: str = "simpletort-zadroga-dev"
    app_env:        str = "development"   # development | staging | production

    # ── Firebase ──────────────────────────────────────────────────────────────
    # Used to verify Firebase Auth JWT tokens issued by auth-rbac for staff.
    firebase_project_id: str = "simpletort-zadroga-dev"
    firestore_database: str = "simpletort-dev"

    # ── Firestore ─────────────────────────────────────────────────────────────
    firestore_cases_collection:        str = "cases"
    firestore_counters_collection:     str = "counters"
    firestore_partners_collection:     str = "partners"
    firestore_request_logs_collection: str = "request_logs"
    firestore_database:                str = "simpletort-dev"

    # ── JWT Auth (partner API key tokens) ─────────────────────────────────────
    jwks_uri:     str = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
    jwt_audience: str = ""
    jwt_issuer:   str = ""

    # ── VCF eligibility window ────────────────────────────────────────────────
    # Do not change without legal review (Zadroga Act / Never Forget the Heroes Act).
    vcf_window_start: str = "2001-09-11"
    vcf_window_end:   str = "2011-05-30"

    # ── API Key Auth ──────────────────────────────────────────────────────────
    hmac_signature_max_age_seconds: int = 300

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    rate_limit_requests:       int = 100
    rate_limit_window_seconds: int = 60

    # ── Cloud Tasks (Admin Staff follow-up task only) ─────────────────────────
    # The sms-dispatch queue is owned by the notification service.
    # lead-intake only uses lead-followup-queue for the 48h follow-up Cloud Task
    # that calls back to /internal/tasks/followup on this service.
    cloud_tasks_queue:        str = "lead-followup-queue"
    cloud_tasks_location:     str = "us-central1"
    cloud_tasks_queue_region: str = "us-central1"
    cloud_tasks_handler_url:  str = ""   # This service's Cloud Run URL
    cloud_tasks_sa_email:     str = ""   # SA used to sign Cloud Tasks OIDC tokens
    followup_delay_hours:     int = 48
    

    # ── Pub/Sub topics ────────────────────────────────────────────────────────
    # lead-created  → notification service sends welcome_sms
    # lead-screened → audit trail + staff Firestore notification (no SMS)
    # lead-followup → notification service sends followup_sms
    pubsub_lead_created_topic:  str = "lead-created-dev"
    pubsub_lead_screened_topic: str = "lead-screened-dev"
    pubsub_lead_followup_topic: str = "lead-followup-dev"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def firebase_jwks_uri(self) -> str:
        return "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"

    @property
    def firebase_jwt_issuer(self) -> str:
        return f"https://securetoken.google.com/{self.firebase_project_id}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
