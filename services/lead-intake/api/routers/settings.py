"""
api/routers/settings.py — Firm-level settings management.

Admin-only endpoints. Accessible by:
  1. A Firebase Auth token with role "senior_partner" or "system_admin"
  2. A partner JWT with raw_claims["admin"] == True (legacy)
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from google.cloud import firestore
from pydantic import BaseModel, Field

from logging_config import get_logger
from middleware.auth import PartnerContext, get_partner
from services.case_service import reset_prefix_cache
from services.firestore_client import get_db

logger = get_logger(__name__)
router = APIRouter(prefix="/admin/settings", tags=["Firm Settings"])

_ADMIN_ROLES = {"senior_partner", "system_admin"}
_FIRM_SETTINGS_COLLECTION = "firmSettings"
_CASE_ID_PREFIX_DOC       = "case_id_prefix"


def _require_admin(partner: PartnerContext) -> PartnerContext:
    role = partner.raw_claims.get("role", "")
    if role in _ADMIN_ROLES:
        return partner
    if partner.raw_claims.get("admin"):
        return partner
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error":   "FORBIDDEN",
            "message": "Admin role required (senior_partner or system_admin)",
            "details": [],
        },
    )


class UpdateCaseIdPrefixRequest(BaseModel):
    prefix: str = Field(
        ...,
        min_length=1,
        max_length=10,
        pattern=r'^[A-Z]+$',
        description="Uppercase letters only. Becomes the leading segment of every new case ID.",
        examples=["ZAD", "CASE", "TORT"],
    )


class CaseIdPrefixResponse(BaseModel):
    prefix:    str
    updatedAt: str
    updatedBy: str


@router.patch(
    "/case-id-prefix",
    response_model=CaseIdPrefixResponse,
    summary="Update the firm-wide case ID prefix",
    description=(
        "Writes `prefix` to `firmSettings/case_id_prefix` in Firestore and "
        "invalidates the in-process cache so the next `POST /leads` picks up "
        "the new value immediately. Only affects **new** cases — existing case "
        "IDs are never rewritten."
    ),
)
async def update_case_id_prefix(
    body:    UpdateCaseIdPrefixRequest,
    partner: PartnerContext = Depends(get_partner),
    db:      firestore.AsyncClient = Depends(get_db),
) -> CaseIdPrefixResponse:
    _require_admin(partner)

    now        = datetime.utcnow()
    updated_by = partner.raw_claims.get("email") or partner.partner_id

    doc_ref = db.collection(_FIRM_SETTINGS_COLLECTION).document(_CASE_ID_PREFIX_DOC)
    await doc_ref.set(
        {
            "prefix":    body.prefix,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "updatedBy": updated_by,
        },
        merge=True,
    )

    # Bust the module-level cache in case_service so the next case creation
    # re-reads the new value from Firestore.
    reset_prefix_cache()

    logger.info(
        "case_id_prefix_updated",
        new_prefix=body.prefix,
        updated_by=updated_by,
    )

    return CaseIdPrefixResponse(
        prefix    = body.prefix,
        updatedAt = now.isoformat() + "Z",
        updatedBy = updated_by,
    )


@router.get(
    "/case-id-prefix",
    response_model=CaseIdPrefixResponse,
    summary="Get the current case ID prefix",
)
async def get_case_id_prefix(
    partner: PartnerContext = Depends(get_partner),
    db:      firestore.AsyncClient = Depends(get_db),
) -> CaseIdPrefixResponse:
    _require_admin(partner)

    doc = await db.collection(_FIRM_SETTINGS_COLLECTION).document(_CASE_ID_PREFIX_DOC).get()
    if not doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error":   "NOT_FOUND",
                "message": "case_id_prefix has not been configured yet",
                "details": [],
            },
        )

    data = doc.to_dict() or {}
    return CaseIdPrefixResponse(
        prefix    = data.get("prefix", "CASE"),
        updatedAt = (data.get("updatedAt") or datetime.utcnow()).isoformat() + "Z"
            if not isinstance(data.get("updatedAt"), str) else data["updatedAt"],
        updatedBy = data.get("updatedBy", ""),
    )
