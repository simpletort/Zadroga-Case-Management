"""
GCS Service — signed URL generation and lifecycle management.

All file access in SimpleTort goes through signed URLs so that:
  1. GCS credentials are never exposed to frontend clients.
  2. Access is time-limited and scoped to a specific object.
  3. Every URL request is logged for HIPAA audit purposes.
"""

import datetime
import logging
from typing import Optional

from google.cloud import storage as gcs

from app.config import get_settings
from app.models.storage import DocumentCategory, UrlAction

logger = logging.getLogger(__name__)
settings = get_settings()

# Maps DocumentCategory enum values to GCS path templates.
# {caseId} is replaced at runtime for case-scoped categories.
CATEGORY_PATHS: dict[str, str] = {
    DocumentCategory.temp_lead_attachments: "temp-lead-attachments",
    DocumentCategory.medical_records:       "{caseId}/medical-records",
    DocumentCategory.proof_of_presence:     "{caseId}/proof-of-presence",
    DocumentCategory.id_documents:          "{caseId}/id-documents",
    DocumentCategory.legal_forms:           "{caseId}/legal-forms",
    DocumentCategory.vcf_documents:         "{caseId}/vcf-documents",
    DocumentCategory.settlement_docs:       "{caseId}/settlement-docs",
    DocumentCategory.client_uploads:        "client-uploads",
}


def build_blob_path(
    category: DocumentCategory,
    file_name: str,
    case_id: Optional[str] = None,
) -> str:
    """
    Construct the GCS blob path for a given category and file name.

    Raises ValueError if a case-scoped category is used without a caseId.
    """
    template = CATEGORY_PATHS[category]
    if "{caseId}" in template:
        if not case_id:
            raise ValueError(
                "category '{}' requires a caseId".format(category.value)
            )
        path = template.format(caseId=case_id)
    else:
        path = template
    return "{}/{}".format(path, file_name)


def generate_signed_url(
    gcs_client: gcs.Client,
    blob_path: str,
    action: UrlAction,
    content_type: Optional[str] = None,
    expiry_minutes: Optional[int] = None,
) -> tuple[str, datetime.datetime]:
    """
    Generate a v4 signed URL for the given blob path.

    Returns:
        (signed_url, expires_at)
    """
    if expiry_minutes is None:
        expiry_minutes = (
            settings.signed_url_write_expiry_minutes
            if action == UrlAction.write
            else settings.signed_url_read_expiry_minutes
        )

    expiration = datetime.timedelta(minutes=expiry_minutes)
    http_method = "PUT" if action == UrlAction.write else "GET"

    bucket = gcs_client.bucket(settings.gcs_bucket_name)
    blob = bucket.blob(blob_path)

    kwargs: dict = {
        "version": "v4",
        "expiration": expiration,
        "method": http_method,
    }
    if action == UrlAction.write and content_type:
        kwargs["content_type"] = content_type

    signed_url = blob.generate_signed_url(**kwargs)
    expires_at = datetime.datetime.utcnow() + expiration

    logger.info(
        "Signed URL generated: action=%s path=%s expiry=%dmin",
        action.value, blob_path, expiry_minutes,
    )
    return signed_url, expires_at


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
