from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── GCP ────────────────────────────────────────────────────────────────
    gcp_project_id: str
    app_env: str = "development"
    firestore_database_id: str = "simpletort-dev"

    # ── Auth ───────────────────────────────────────────────────────────────
    jwt_audience: str = ""
    jwt_issuer: str = ""

    # ── Pub/Sub Topics ─────────────────────────────────────────────────────
    pubsub_topic_enrollment: str = "enrollment-status-changes"
    pubsub_topic_tasks: str = "task-created"
    pubsub_topic_notifications: str = "notification-requests"

    # ── SendGrid ───────────────────────────────────────────────────────────
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "noreply@zadlegal.com"
    sendgrid_from_name: str = "ZAD Legal System"

    # ── Service URLs ───────────────────────────────────────────────────────
    notification_service_url: str = "http://localhost:8081"

    # ── Deadline Config ────────────────────────────────────────────────────
    vcf_deadline_years: int = 2
    alert_days: list[int] = [90, 60, 30]

    # ── Request Limits ─────────────────────────────────────────────────────
    rate_limit_per_minute: int = 120

    @field_validator("alert_days", mode="before")
    @classmethod
    def parse_alert_days(cls, v: Any) -> Any:
        if isinstance(v, str):
            return [int(x) for x in v.strip("[] ").split(",")]
        return v

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()