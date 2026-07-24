"""
Case Profile Update Service  [AMBER ZONE — developer must review and edit meaningfully]

PATCH /api/v1/cases/{caseId} — update a subset of editable case fields.

Role rules:
  - paralegal      : may only edit cases where assignment.assignedParalegal == their uid
  - junior_partner and above: may edit any case
  - partner (X-API-Key auth, e.g. the intake-form Apps Script dispatcher — see
    shared/shared/middlewares/auth.py's API-key path, which sets
    request.state.user.role = "partner"): may edit any case. This grants nothing beyond
    the fixed FIELD_CATALOG below — same as every other caller — so it can never write
    status, case_id, created_at, or a field owned by another endpoint.

Disallowed fields (return 400 if present in request body): status, case_id, created_at
  → This is enforced at the model layer (CasePatchRequest) before this service is called.

Allowed fields: phone, email, address, notes, assigned_attorney, first_name, last_name,
                date_of_birth, exposure_location, exposure_date_start, exposure_date_end,
                conditions, prior_attorney

Firestore mapping (cases/{caseId} document):
  phone                → phone
  email                → email
  address              → address.{street,city,state,zip}
  notes                → notes
  assigned_attorney    → assignment.assignedAttorney
  first_name           → firstName
  last_name            → lastName
  date_of_birth        → dateOfBirth
  exposure_location    → exposureLocation
  exposure_date_start  → exposureDateStart
  exposure_date_end    → exposureDateEnd
  conditions           → conditions
  prior_attorney       → priorAttorney

Every successful call writes one audit_logs/{logId} document listing the changed fields.
PHI rule applies — every editable field on this endpoint is claimant PHI (identity, contact,
and exposure/medical-screening data) and must appear in the audit entry as such.
"""

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from google.cloud import firestore

from app.models.case_profile import FIELD_CATALOG
from app.services.case_profile_fields_service import get_enabled_field_set
from app.utils.roles import normalize_role

logger = logging.getLogger(__name__)

# Roles that may edit any case (junior_partner and above), plus "partner" — the role
# assigned to X-API-Key-authenticated external callers (see module docstring). This does
# NOT widen what a partner caller can write; the fixed FIELD_CATALOG guard applies
# identically to every role.
_PRIVILEGED_ROLES: frozenset[str] = frozenset(
    {"junior_partner", "senior_partner", "system_admin", "admin_staff", "partner"}
)

# Maps request field name → Firestore dot-path on the cases document, derived from the
# single source of truth in app/models/case_profile.py:FIELD_CATALOG. "address" has no
# entry — it's expanded to per-subfield dot-paths separately, below.
_FIELD_TO_FIRESTORE: dict[str, str] = {
    field: meta["firestore_path"]
    for field, meta in FIELD_CATALOG.items()
    if meta["firestore_path"]
}

# Fields that are claimant PHI (identity, contact, or exposure/medical screening data),
# derived from FIELD_CATALOG — used for the audit_logs.phiAccessed flag.
_PHI_FIELDS: frozenset[str] = frozenset(
    field for field, meta in FIELD_CATALOG.items() if meta["phi"]
)


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

    # Firm-configurable subset of the fixed catalog (firmSettings/case_profile_editable_fields).
    # Defaults to the full catalog when unconfigured — see case_profile_fields_service.py.
    enabled_fields = get_enabled_field_set(db)
    disabled_requested = set(changed.keys()) - enabled_fields
    if disabled_requested:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The following fields are not currently editable (disabled by firm settings): {}".format(
                ", ".join(sorted(disabled_requested))
            ),
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
    update_payload: dict[str, Any] = {"updatedAt": now, "questionnaireComplete": True}
    for field, value in changed.items():
        if field == "address" and value is not None:
            # address is a top-level Firestore map {street, city, state, zip}.
            # Write only the sub-fields that were explicitly provided so we don't
            # overwrite unmentioned sub-fields with None.
            addr_dict = value if isinstance(value, dict) else value.model_dump(exclude_none=True)
            for sub_field, sub_value in addr_dict.items():
                update_payload["address.{}".format(sub_field)] = sub_value
        else:
            fs_path = _FIELD_TO_FIRESTORE.get(field)
            if fs_path:
                # Dates are stored as ISO strings on this document (see lead-intake's
                # CaseDocument.to_firestore_dict) — match that convention, not a native
                # Firestore Timestamp.
                update_payload[fs_path] = value.isoformat() if isinstance(value, date) else value

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
        "phiAccessed":   bool(_PHI_FIELDS & changed.keys()),
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
