from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    gcp_project_id: str = "simpletort-prod"
    firestore_database_id: str = "(default)"
    environment: str = "production"
    log_level: str = "INFO"
    trusted_service_accounts: str = ""

    # Cloud Tasks — reminder scheduling
    cloud_tasks_queue: str = "task-reminders"
    cloud_tasks_location: str = "us-east1"
    task_service_url: str = ""          # this service's own Cloud Run URL (set in env)
    service_account_email: str = ""     # SA used for OIDC tokens on internal callbacks
    reminder_advance_hours: int = 24

    model_config = {"env_file": ".env", "case_sensitive": False}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
