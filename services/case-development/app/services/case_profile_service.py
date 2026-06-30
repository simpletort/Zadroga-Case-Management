"""
Case Profile Update Service  [AMBER ZONE — developer must review and edit meaningfully]

PATCH /api/v1/cases/{caseId} — update a subset of editable case fields.

Role rules:
  - paralegal      : may only edit cases where assignment.assignedParalegal == their uid
  - junior_partner and above: may edit any case

Disallowed fields (return 400 if present in request body): status, case_id, created_at
  → This is enforced at the model layer (CasePatchRequest) before this service is called.

Allowed fields: phone, email, address, notes, assigned_attorney

Firestore mapping (cases/{caseId} document):
  phone              → client.phone
  email              → client.email
  address            → client.address
  notes              → notes
  assigned_attorney  → assignment.assignedAttorney

Every successful call writes one audit_logs/{logId} document listing the changed fields.
PHI rule applies — phone, email, address are PHI fields and must appear in the audit entry.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from google.cloud import firestore

from app.utils.roles import normalize_role

logger = logging.getLogger(__name__)

# Roles that may edit any case (junior_partner and above).
_PRIVILEGED_ROLES: frozenset[str] = frozenset(
    {"junior_partner", "senior_partner", "system_admin", "admin_staff"}
)

# Maps request field name → Firestore dot-path on the cases document.
_FIELD_TO_FIRESTORE: dict[str, str] = {
    "phone":             "client.phone",
    "email":             "client.email",
    "address":           "client.address",
    "notes":             "notes",
    "assigned_attorney": "assignment.assignedAttorney",
}


def _get_case(db: firestore.Client, case_id: str) -> tuple[firestore.DocumentReference, dict]:
    ref  = db.collection("cases").document(case_id)
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case '{}' not found.".format(case_id),
        )
    return ref, snap.to_dict() or {}


def patch_case(
    db: firestore.Client,
    case_id: str,
    changed: dict[str, Any],
    actor_uid: str,
    actor_role: str,
) -> dict:
    """
    Validate the actor's permission, apply field updates, write an audit log entry.

    Args:
        changed: dict of {field_name: new_value} — only the fields that were explicitly
                 set in the request body (already filtered to ALLOWED_FIELDS by the caller).
        actor_uid:  Firebase UID of the requester.
        actor_role: normalised role string.

    Returns:
        dict with case_id, updated_fields, audit_log_id.
    """
    if not changed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Request body must include at least one editable field.",
        )

    role = normalize_role(actor_role)
    case_ref, case_data = _get_case(db, case_id)

    # Role guard — paralegal may only edit their own assigned cases.
    if role == "paralegal":
        assigned_paralegal = (case_data.get("assignment") or {}).get("assignedParalegal")
        if assigned_paralegal != actor_uid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Paralegal '{}' is not assigned to case '{}'.".format(
                    actor_uid, case_id
                ),
            )
    elif role not in _PRIVILEGED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Role '{}' is not permitted to edit case fields.".format(role),
        )

    # Build the Firestore update payload using dot-path keys.
    now = datetime.now(tz=timezone.utc)
    update_payload: dict[str, Any] = {"updatedAt": now}
    for field, value in changed.items():
        fs_path = _FIELD_TO_FIRESTORE.get(field)
        if fs_path:
            update_payload[fs_path] = value

    audit_log_id = str(uuid.uuid4())
    audit_ref    = db.collection("audit_logs").document(audit_log_id)

    batch = db.batch()
    batch.update(case_ref, update_payload)
    batch.set(audit_ref, {
        "auditLogId":    audit_log_id,
        "resourceType":  "case",
        "resourceId":    case_id,
        "action":        "case.patch",
        "changedFields": list(changed.keys()),
        "performedBy":   actor_uid,
        "performedAt":   now,
        "phiAccessed":   bool({"phone", "email", "address"} & changed.keys()),
    })
    batch.commit()

    logger.info(
        "Case %s patched by %s (role=%s); fields=%s audit=%s",
        case_id, actor_uid, role, list(changed.keys()), audit_log_id,
    )

    return {
        "case_id":        case_id,
        "updated_fields": list(changed.keys()),
        "audit_log_id":   audit_log_id,
    }
