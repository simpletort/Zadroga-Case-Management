"""
SimpleTort – Workflow Orchestrator Service
Configuration loaded from environment variables.
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # GCP Project
    gcp_project_id: str
    gcp_region: str = "us-east1"

    # Firestore
    firestore_database: str = "(default)"

    # Pub/Sub topics consumed by this service
    pubsub_case_events_topic: str = "case-events"
    pubsub_case_events_subscription: str = "workflow-orchestrator-case-events-sub"
    pubsub_deadline_alerts_topic: str = "deadline-alerts"

    # Cloud Tasks queue
    cloud_tasks_queue: str = "workflow-deadlines"
    cloud_tasks_service_url: Optional[str] = None  # URL of this Cloud Run service; set after first deploy

    # Cloud Workflows
    workflows_location: str = "us-central1"

    # Service identity (for service-to-service auth)
    service_account_email: Optional[str] = None

    # App
    environment: str = "development"
    log_level: str = "INFO"
    port: int = 8080

    # Seed workflow definitions into Firestore on startup (development only).
    # Set AUTO_SEED_DEFINITIONS=true in .env to auto-seed; defaults to False.
    auto_seed_definitions: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
