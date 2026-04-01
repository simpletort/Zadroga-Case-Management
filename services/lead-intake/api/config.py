"""
api/config.py — Application settings via pydantic-settings.
All config loaded from environment variables / Secret Manager mounts.

Changes vs. original:
  - Removed duplicate `notification_service_url` and `cloud_tasks_sms_queue` fields
  - Added `firebase_project_id` for Firebase JWT verification in staff auth
  - Added `cloud_tasks_queue_region` (canonical name, replaces duplicate aliases)
  - Removed direct sendgrid/twilio references from Cloud Tasks queue names
    (those are now managed by the Notification Dispatcher service)
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
    app_env: str = "development"           # development | staging | production

    # ── Firebase ──────────────────────────────────────────────────────────────
    # Used for staff Firebase JWT verification (auth-rbac tokens).
    # Must match the Firebase project where auth-rbac Cloud Functions are deployed.
    firebase_project_id: str = "simpletort-zadroga-dev"

    # ── Firestore ─────────────────────────────────────────────────────────────
    firestore_cases_collection:       str = "cases"
    firestore_counters_collection:    str = "counters"
    firestore_partners_collection:    str = "partners"
    firestore_request_logs_collection: str = "request_logs"

    # ── JWT Auth (partner tokens) ─────────────────────────────────────────────
    jwks_uri:    str = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
    jwt_audience: str = ""
    jwt_issuer:   str = ""

    # ── VCF eligibility window ────────────────────────────────────────────────
    # Do not change without legal review (Zadroga Act / Never Forget the Heroes Act).
    vcf_window_start: str = "2001-09-11"
    vcf_window_end:   str = "2011-05-30"

    # ── API Key Auth ──────────────────────────────────────────────────────────
    hmac_signature_max_age_seconds: int = 300   # 5 minutes

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    rate_limit_requests:       int = 100
    rate_limit_window_seconds: int = 60

    # ── Cloud Tasks ───────────────────────────────────────────────────────────
    cloud_tasks_queue:        str = "lead-followup-queue"
    cloud_tasks_location:     str = "us-central1"
    cloud_tasks_queue_region: str = "us-central1"   # canonical alias for location
    cloud_tasks_handler_url:  str = ""    # Cloud Run service URL (no trailing slash)
    cloud_tasks_sa_email:     str = ""
    cloud_tasks_sms_queue:    str = "sms-dispatch"
    cloud_tasks_email_queue:  str = "email-dispatch"
    followup_delay_hours:     int = 48

    # ── Notification Dispatcher Service (separate Cloud Run service) ──────────
    # When set: welcome emails/SMS are enqueued to this service via Cloud Tasks.
    # When unset (dev): direct SendGrid/Twilio calls are used as fallback.
    notification_service_url: str = ""    # e.g. https://notification-dispatcher-xxx.run.app

    # ── Direct notification credentials (dev fallback) ────────────────────────
    sendgrid_api_key:      str = ""
    sendgrid_from_email:   str = "noreply@zadlegal.com"
    twilio_account_sid:    str = ""
    twilio_auth_token:     str = ""
    twilio_from_number:    str = ""

    # ── Pub/Sub topics ────────────────────────────────────────────────────────
    # lead-created  → triggers VCF screening (now done inline, topic kept for audit)
    # lead-screened → consumed by Notification Dispatcher service
    pubsub_lead_created_topic:  str = "lead-created-dev"
    pubsub_lead_screened_topic: str = "lead-screened-dev"

    # ── Client portal ─────────────────────────────────────────────────────────
    portal_base_url: str = "https://portal.zadroga.com/c"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def firebase_jwks_uri(self) -> str:
        """Google's public keys for verifying Firebase Auth JWTs."""
        return "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"

    @property
    def firebase_jwt_issuer(self) -> str:
        return f"https://securetoken.google.com/{self.firebase_project_id}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
