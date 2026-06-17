"""
GCS Service — signed URL generation and lifecycle management.

All file access in SimpleTort goes through signed URLs so that:
  1. GCS credentials are never exposed to frontend clients.
  2. Access is time-limited and scoped to a specific object.
  3. Every URL request is logged for HIPAA audit purposes.
"""

import datetime
import logging
import urllib.request
from functools import lru_cache
from typing import Optional

import google.auth
import google.auth.transport.requests
import google.oauth2.service_account
from google.auth import iam
from google.cloud import storage as gcs

from app.config import get_settings
from app.models.storage import UrlAction

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_SIGNED_URL_EXPIRY_MINUTES = 15


def _fetch_metadata_email() -> str:
    """Fetch the default service account email from the GCE metadata server."""
    url = (
        "http://metadata.google.internal/computeMetadata/v1"
        "/instance/service-accounts/default/email"
    )
    req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=2) as resp:
        return resp.read().decode().strip()


@lru_cache(maxsize=1)
def _get_signing_credentials() -> google.oauth2.service_account.Credentials:
    """
    Build IAM-backed signing credentials for Cloud Run environments.

    Cloud Run uses Compute Engine tokens (no embedded private key), so we
    delegate signing to the IAM signBlob API.  The service account must have
    the 'Service Account Token Creator' role on itself.
    """
    sa_email = settings.gcs_service_account_email or _fetch_metadata_email()

    auth_request = google.auth.transport.requests.Request()
    credentials, _ = google.auth.default()
    credentials.refresh(auth_request)

    signer = iam.Signer(
        request=auth_request,
        credentials=credentials,
        service_account_email=sa_email,
    )
    return google.oauth2.service_account.Credentials(
        signer=signer,
        service_account_email=sa_email,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/devstorage.read_write"],
    )


def generate_signed_url(
    gcs_client: gcs.Client,
    blob_path: str,
    action: UrlAction,
    content_type: Optional[str] = None,
    expiry_minutes: Optional[int] = None,
    inline: bool = False,
) -> tuple[str, datetime.datetime, bool]:
    """
    Generate a v4 signed URL for the given blob path.

    TTL is capped at MAX_SIGNED_URL_EXPIRY_MINUTES regardless of the caller-supplied value.

    Returns:
        (signed_url, expires_at, ttl_was_capped)
        ttl_was_capped is True when the requested TTL exceeded the cap.
    """
    requested_minutes = expiry_minutes
    if expiry_minutes is None:
        expiry_minutes = (
            settings.signed_url_write_expiry_minutes
            if action == UrlAction.write
            else settings.signed_url_read_expiry_minutes
        )

    ttl_was_capped = expiry_minutes > MAX_SIGNED_URL_EXPIRY_MINUTES
    if ttl_was_capped:
        logger.warning(
            "Signed URL TTL capped: requested=%dmin cap=%dmin path=%s",
            expiry_minutes, MAX_SIGNED_URL_EXPIRY_MINUTES, blob_path,
        )
        expiry_minutes = MAX_SIGNED_URL_EXPIRY_MINUTES

    expiration = datetime.timedelta(minutes=expiry_minutes)
    http_method = "PUT" if action == UrlAction.write else "GET"

    bucket = gcs_client.bucket(settings.gcs_bucket_name)
    blob = bucket.blob(blob_path)

    kwargs: dict = {
        "version": "v4",
        "expiration": expiration,
        "method": http_method,
        "credentials": _get_signing_credentials(),
    }
    if action == UrlAction.write and content_type:
        kwargs["content_type"] = content_type
    if action == UrlAction.read and inline:
        kwargs["response_disposition"] = "inline"

    signed_url = blob.generate_signed_url(**kwargs)
    expires_at = datetime.datetime.utcnow() + expiration

    logger.info(
        "Signed URL generated: action=%s path=%s expiry=%dmin capped=%s",
        action.value, blob_path, expiry_minutes, ttl_was_capped,
    )
    return signed_url, expires_at, ttl_was_capped


def update_lifecycle_rules(
    gcs_client: gcs.Client,
    rules: list[dict],
) -> None:
    """
    Replace the bucket lifecycle configuration with the provided rules.

    Each rule dict has the shape expected by the GCS Python SDK:
        {"action": {"type": "SetStorageClass", "storageClass": "COLDLINE"},
         "condition": {"age": 365}}
    """
    bucket = gcs_client.bucket(settings.gcs_bucket_name)
    bucket.lifecycle_rules = rules
    bucket.patch()
    logger.info(
        "Lifecycle rules updated on bucket %s: %d rule(s)",
        settings.gcs_bucket_name, len(rules),
    )


def get_lifecycle_rules(gcs_client: gcs.Client) -> tuple[list[dict], Optional[int]]:
    """
    Read the current bucket lifecycle configuration and soft-delete retention.

    Returns:
        (rules_list, soft_delete_retention_days)
        soft_delete_retention_days is None if no soft-delete policy is set.
    """
    bucket = gcs_client.get_bucket(settings.gcs_bucket_name)
    rules = list(bucket.lifecycle_rules)

    retention_days: Optional[int] = None
    try:
        secs = bucket.soft_delete_policy.retention_duration_seconds
        if secs:
            retention_days = int(secs) // 86400
    except Exception:
        pass  # soft_delete_policy may not exist on all SDK versions / bucket types

    logger.info(
        "Lifecycle rules read from bucket %s: %d rule(s), soft_delete=%s days",
        settings.gcs_bucket_name, len(rules), retention_days,
    )
    return rules, retention_days


def configure_soft_delete(gcs_client: gcs.Client, retention_days: int = 30) -> None:
    """
    Set the soft-delete retention policy on the bucket.

    Objects deleted while this policy is active are recoverable for
    `retention_days` days via GCS restore operations.
    """
    bucket = gcs_client.bucket(settings.gcs_bucket_name)
    bucket.soft_delete_policy.retention_duration_seconds = retention_days * 86400
    bucket.patch()
    logger.info(
        "Soft-delete policy set on bucket %s: %d days",
        settings.gcs_bucket_name, retention_days,
    )


def set_case_documents_hold(
    gcs_client: gcs.Client,
    case_id: str,
    hold: bool,
) -> int:
    """
    Set or release a temporary hold on every object under {caseId}/.

    When hold=True  — objects are exempt from lifecycle transitions and deletion.
    When hold=False — hold is released; lifecycle rules resume for those objects.

    Also writes custom metadata ``case-status`` = ``active`` / ``archived`` so
    the hold state is human-readable in the GCS console.

    Returns the number of objects updated.
    """
    bucket = gcs_client.bucket(settings.gcs_bucket_name)
    prefix = "{}/".format(case_id)
    blobs = list(gcs_client.list_blobs(settings.gcs_bucket_name, prefix=prefix))

    case_status = "active" if hold else "archived"
    updated = 0
    for blob in blobs:
        blob.temporary_hold = hold
        blob.metadata = {**(blob.metadata or {}), "case-status": case_status}
        blob.patch()
        updated += 1

    logger.info(
        "Case hold updated: case_id=%s hold=%s objects_updated=%d",
        case_id, hold, updated,
    )
    return updated
