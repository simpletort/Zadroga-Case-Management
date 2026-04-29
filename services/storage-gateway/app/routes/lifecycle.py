"""
Lifecycle routes — /api/v1/storage/lifecycle and /api/v1/storage/cases/{caseId}/hold

Default Zadroga policy (applied via POST /lifecycle/apply-default):
  staging/     → Delete after 1 day        (orphaned staging cleanup)
  quarantine/  → Delete after 90 days      (compliance retention)
  All objects  → NEARLINE after 180 days
  All objects  → COLDLINE after 365 days

Active case document exemption:
  temporaryHold=True is set on clean-scanned files by the virus scanner.
  Lifecycle transitions are skipped for held objects regardless of age.
  Hold is released via PUT /cases/{caseId}/hold when a case is closed/settled.

All lifecycle endpoints require system_admin role.
"""

import logging

from fastapi import APIRouter, Request

from app.models.storage import (
    CaseHoldRequest,
    CaseHoldResponse,
    LifecyclePolicyResponse,
    LifecycleUpdateRequest,
    LifecycleUpdateResponse,
    SoftDeleteRequest,
    SoftDeleteResponse,
)
from app.services.gcs_service import (
    configure_soft_delete,
    get_lifecycle_rules,
    set_case_documents_hold,
    update_lifecycle_rules,
)
from app.utils.audit import AuditAction, log_audit_event
from app.utils.gcs_client import get_gcs_client
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/storage", tags=["Storage"])
settings = get_settings()

# Canonical Zadroga lifecycle policy.
# Active case files (temporaryHold=True) are automatically exempt from
# the NEARLINE/COLDLINE rules regardless of object age.
DEFAULT_LIFECYCLE_RULES = [
    {
        "action": {"type": "Delete"},
        "condition": {"age": 1, "matchesPrefix": ["staging/"]},
    },
    {
        "action": {"type": "Delete"},
        "condition": {"age": 90, "matchesPrefix": ["quarantine/"]},
    },
    {
        "action": {"type": "SetStorageClass", "storageClass": "NEARLINE"},
        "condition": {"age": 180},
    },
    {
        "action": {"type": "SetStorageClass", "storageClass": "COLDLINE"},
        "condition": {"age": 365},
    },
]


def _build_sdk_rules(rules: list) -> list[dict]:
    """Convert Pydantic LifecycleRule models to the dict shape expected by GCS SDK."""
    sdk_rules = []
    for rule in rules:
        action: dict = {"type": rule.action.value}
        if rule.storage_class:
            action["storageClass"] = rule.storage_class
        condition: dict = {"age": rule.condition.age_days}
        if rule.condition.matches_prefix:
            condition["matchesPrefix"] = rule.condition.matches_prefix
        sdk_rules.append({"action": action, "condition": condition})
    return sdk_rules


# ── GET /lifecycle ─────────────────────────────────────────────────────────────

@router.get(
    "/lifecycle",
    response_model=LifecyclePolicyResponse,
    summary="Read current bucket lifecycle rules and soft-delete policy (system_admin only)",
)
def get_lifecycle():
    gcs_client = get_gcs_client()
    rules, retention_days = get_lifecycle_rules(gcs_client)
    return LifecyclePolicyResponse(
        bucket=settings.gcs_bucket_name,
        rules=rules,
        soft_delete_retention_days=retention_days,
    )


# ── PUT /lifecycle ─────────────────────────────────────────────────────────────

@router.put(
    "/lifecycle",
    response_model=LifecycleUpdateResponse,
    summary="Replace bucket lifecycle rules (system_admin only)",
)
def update_lifecycle(
    body: LifecycleUpdateRequest,
):
    sdk_rules = _build_sdk_rules(body.rules)
    gcs_client = get_gcs_client()
    update_lifecycle_rules(gcs_client=gcs_client, rules=sdk_rules)
    return LifecycleUpdateResponse(
        bucket=settings.gcs_bucket_name,
        rules_applied=len(sdk_rules),
        message="Lifecycle policy updated successfully.",
    )


# ── POST /lifecycle/apply-default ─────────────────────────────────────────────

@router.post(
    "/lifecycle/apply-default",
    response_model=LifecycleUpdateResponse,
    summary="Apply the canonical Zadroga lifecycle policy (system_admin only)",
)
def apply_default_lifecycle():
    """
    Applies the standard four-rule Zadroga policy:
      - staging/    → Delete after 1 day
      - quarantine/ → Delete after 90 days
      - All objects → NEARLINE after 180 days
      - All objects → COLDLINE after 365 days

    Active case files are exempt via GCS temporaryHold (set by virus scanner).
    """
    gcs_client = get_gcs_client()
    update_lifecycle_rules(gcs_client=gcs_client, rules=DEFAULT_LIFECYCLE_RULES)
    return LifecycleUpdateResponse(
        bucket=settings.gcs_bucket_name,
        rules_applied=len(DEFAULT_LIFECYCLE_RULES),
        message="Default Zadroga lifecycle policy applied successfully.",
    )


# ── PUT /lifecycle/soft-delete ─────────────────────────────────────────────────

@router.put(
    "/lifecycle/soft-delete",
    response_model=SoftDeleteResponse,
    summary="Configure bucket soft-delete retention window (system_admin only)",
)
def update_soft_delete(
    body: SoftDeleteRequest,
):
    """
    Sets the soft-delete retention window on the GCS bucket.
    Deleted objects are recoverable for ``retention_days`` days.
    Minimum 7 days, maximum 90 days.
    """
    gcs_client = get_gcs_client()
    configure_soft_delete(gcs_client=gcs_client, retention_days=body.retention_days)
    return SoftDeleteResponse(
        bucket=settings.gcs_bucket_name,
        retention_days=body.retention_days,
        message="Soft-delete retention set to {} days.".format(body.retention_days),
    )


# ── PUT /cases/{case_id}/hold ──────────────────────────────────────────────────

@router.put(
    "/cases/{case_id}/hold",
    response_model=CaseHoldResponse,
    summary="Set or release temporary hold on all documents in a case (system_admin only)",
)
def update_case_hold(
    request: Request,
    case_id: str,
    body: CaseHoldRequest,
):
    """
    Sets ``temporaryHold`` on every GCS object under ``{caseId}/``.

    hold=true  — Protects documents from lifecycle transitions and deletion.
                 Set automatically by the virus scanner for clean-scanned files.
    hold=false — Releases the hold. Use when a case is Closed or Settled so
                 lifecycle rules (NEARLINE/COLDLINE transitions) can apply.
    """
    gcs_client = get_gcs_client()
    count = set_case_documents_hold(
        gcs_client=gcs_client, case_id=case_id, hold=body.hold
    )

    audit_action = AuditAction.hold_set if body.hold else AuditAction.hold_release
    log_audit_event(
        action=audit_action,
        request=request,
        case_id=case_id,
        metadata={"documents_updated": count},
    )

    action = "applied to" if body.hold else "released from"
    return CaseHoldResponse(
        case_id=case_id,
        hold=body.hold,
        documents_updated=count,
        message="Temporary hold {} {} document(s) in case {}.".format(
            action, count, case_id
        ),
    )
