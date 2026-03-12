"""
Lifecycle route — PUT /api/v1/storage/lifecycle

Allows system admins to update the GCS bucket lifecycle policy.
Default policy (from Product Architecture §5.2):
  Standard → Coldline after 365 days of age.

Restricted to system_admin role only.
"""

import logging

from fastapi import APIRouter, Depends

from app.models.storage import LifecycleUpdateRequest, LifecycleUpdateResponse
from app.services.gcs_service import update_lifecycle_rules
from app.utils.auth import require_min_role
from app.utils.gcs_client import get_gcs_client
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/storage", tags=["Storage"])
settings = get_settings()


def _build_sdk_rules(rules: list) -> list[dict]:
    """Convert Pydantic LifecycleRule models to the dict shape expected by GCS SDK."""
    sdk_rules = []
    for rule in rules:
        action: dict = {"type": rule.action.value}
        if rule.storage_class:
            action["storageClass"] = rule.storage_class
        sdk_rules.append({
            "action": action,
            "condition": {"age": rule.condition.age_days},
        })
    return sdk_rules


@router.put(
    "/lifecycle",
    response_model=LifecycleUpdateResponse,
    summary="Update GCS bucket lifecycle rules (system admin only)",
)
def update_lifecycle(
    body: LifecycleUpdateRequest,
    _user: dict = Depends(require_min_role("lifecycle_update")),
):
    sdk_rules = _build_sdk_rules(body.rules)
    gcs_client = get_gcs_client()
    update_lifecycle_rules(gcs_client=gcs_client, rules=sdk_rules)

    return LifecycleUpdateResponse(
        bucket=settings.gcs_bucket_name,
        rules_applied=len(sdk_rules),
        message="Lifecycle policy updated successfully.",
    )
