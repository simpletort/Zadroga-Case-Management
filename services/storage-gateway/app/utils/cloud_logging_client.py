"""
Cloud Logging client singleton — writes structured audit entries to a
named log stream in Cloud Logging.

Named log: simpletort-file-access-audit
  projects/{PROJECT_ID}/logs/simpletort-file-access-audit

Log entries are immutable once written (GCP platform guarantee).
A Log Sink should export this named log to a locked GCS bucket for
7-year HIPAA retention.  See docs/audit-retention-setup.md.
"""

from functools import lru_cache

from app.config import get_settings

AUDIT_LOG_NAME = "simpletort-file-access-audit"


@lru_cache(maxsize=1)
def get_cloud_logger():
    """
    Return a singleton Cloud Logging logger scoped to the HIPAA audit log stream.

    The ``google-cloud-logging`` import is intentionally deferred to this
    function body so that test fixtures can patch ``get_cloud_logger`` before
    the real package is ever loaded.  This avoids ``ModuleNotFoundError`` in
    environments where the package is not installed (e.g. CI test runners that
    don't install GCP extras).

    Cloud Run's default service account must have the
    ``roles/logging.logWriter`` IAM role (granted by default on Cloud Run).
    """
    import google.cloud.logging  # noqa: PLC0415 — lazy import for testability

    settings = get_settings()
    client = google.cloud.logging.Client(project=settings.gcp_project_id)
    return client.logger(AUDIT_LOG_NAME)
