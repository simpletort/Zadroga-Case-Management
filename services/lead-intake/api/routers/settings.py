"""
api/routers/settings.py — Firm-level settings management.

Admin-only endpoints. Accessible by:
  1. A Firebase Auth token with role "senior_partner" or "system_admin"
  2. A partner JWT with raw_claims["admin"] == True (legacy)
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from google.cloud import firestore
from pydantic import BaseModel, Field

from logging_config import get_logger
from middleware.auth import PartnerContext, get_partner
from services.case_service import reset_prefix_cache
from services.firestore_client import get_db
from services.vcf_screener import reset_rules_cache

logger = get_logger(__name__)
router = APIRouter(prefix="/admin/settings", tags=["Firm Settings"])

_ADMIN_ROLES               = {"senior_partner", "system_admin"}
_FIRM_SETTINGS_COLLECTION  = "firmSettings"
_CASE_ID_PREFIX_DOC        = "case_id_prefix"
_SCREENING_RULES_COLLECTION = "screeningRules"


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


# ── Screening Rules ─────────────────────────────────────────────────────────────


class ScreeningRuleParams(BaseModel):
    """Operator-specific parameters. Only the keys relevant to the chosen operator are used."""
    # fields_not_empty
    fields:      Optional[list[str]] = None
    # in_list (also used by date_overlap for field references)
    field:       Optional[str]       = None
    values:      Optional[list[str]] = None
    match_type:  Optional[str]       = "substring"   # "substring" | "exact"
    # date_overlap
    field_start: Optional[str]       = None
    field_end:   Optional[str]       = None
    range_start: Optional[str]       = None          # ISO date string, e.g. "2001-09-11"
    range_end:   Optional[str]       = None          # ISO date string, e.g. "2011-05-30"
    # boolean_equals
    expected:    Optional[bool]      = None
    # number_in_range
    min:         Optional[float]     = None
    max:         Optional[float]     = None


class CreateScreeningRuleRequest(BaseModel):
    ruleId:      str              = Field(..., min_length=1, max_length=50,  pattern=r'^[A-Z0-9_]+$')
    name:        str              = Field(..., min_length=1, max_length=100)
    description: str              = Field(default="")
    enabled:     bool             = True
    severity:    Literal["hard_fail", "soft_flag"]
    operator:    Literal["fields_not_empty", "in_list", "date_overlap", "boolean_equals", "number_in_range"]
    params:      ScreeningRuleParams
    passCode:    str              = Field(..., min_length=1, max_length=50)
    failCode:    str              = Field(..., min_length=1, max_length=50)
    passReason:  str              = Field(default="")
    failReason:  str              = Field(default="")
    order:       int              = Field(default=0, ge=0)


class ScreeningRuleResponse(BaseModel):
    ruleId:      str
    name:        str
    description: str
    enabled:     bool
    severity:    str
    operator:    str
    params:      dict
    passCode:    str
    failCode:    str
    passReason:  str
    failReason:  str
    order:       int
    updatedAt:   str
    updatedBy:   str


def _rule_doc_to_response(data: dict) -> ScreeningRuleResponse:
    """Convert a raw Firestore rule document to ScreeningRuleResponse."""
    updated_at = data.get("updatedAt") or datetime.utcnow()
    if not isinstance(updated_at, str):
        updated_at = updated_at.isoformat() + "Z"
    return ScreeningRuleResponse(
        ruleId      = data.get("ruleId", ""),
        name        = data.get("name", ""),
        description = data.get("description", ""),
        enabled     = bool(data.get("enabled", True)),
        severity    = data.get("severity", "hard_fail"),
        operator    = data.get("operator", ""),
        params      = data.get("params", {}),
        passCode    = data.get("passCode", ""),
        failCode    = data.get("failCode", ""),
        passReason  = data.get("passReason", ""),
        failReason  = data.get("failReason", ""),
        order       = int(data.get("order", 0)),
        updatedAt   = updated_at,
        updatedBy   = data.get("updatedBy", ""),
    )


# GET /admin/settings/screening-rules
@router.get(
    "/screening-rules",
    response_model=list[ScreeningRuleResponse],
    summary="List all screening rules",
    description="Returns all rules (enabled and disabled) ordered by `order` field.",
)
async def list_screening_rules(
    partner: PartnerContext = Depends(get_partner),
    db:      firestore.AsyncClient = Depends(get_db),
) -> list[ScreeningRuleResponse]:
    _require_admin(partner)
    query = db.collection(_SCREENING_RULES_COLLECTION).order_by("order")
    return [_rule_doc_to_response(doc.to_dict()) async for doc in query.stream()]


# POST /admin/settings/screening-rules
@router.post(
    "/screening-rules",
    response_model=ScreeningRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new screening rule",
)
async def create_screening_rule(
    body:    CreateScreeningRuleRequest,
    partner: PartnerContext = Depends(get_partner),
    db:      firestore.AsyncClient = Depends(get_db),
) -> ScreeningRuleResponse:
    _require_admin(partner)

    doc_ref = db.collection(_SCREENING_RULES_COLLECTION).document(body.ruleId)
    existing = await doc_ref.get()
    if existing.exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error":   "CONFLICT",
                "message": f"Rule '{body.ruleId}' already exists. Use PUT to update it.",
                "details": [],
            },
        )

    now        = datetime.utcnow()
    updated_by = partner.raw_claims.get("email") or partner.partner_id
    doc_data   = {
        **body.model_dump(),
        "params":    body.params.model_dump(exclude_none=True),
        "createdAt": firestore.SERVER_TIMESTAMP,
        "updatedAt": firestore.SERVER_TIMESTAMP,
        "updatedBy": updated_by,
    }
    await doc_ref.set(doc_data)
    reset_rules_cache()

    logger.info("screening_rule_created", rule_id=body.ruleId, updated_by=updated_by)
    return _rule_doc_to_response({**doc_data, "updatedAt": now.isoformat() + "Z", "updatedBy": updated_by})


# GET /admin/settings/screening-rules/{rule_id}
@router.get(
    "/screening-rules/{rule_id}",
    response_model=ScreeningRuleResponse,
    summary="Get a single screening rule",
)
async def get_screening_rule(
    rule_id: str,
    partner: PartnerContext = Depends(get_partner),
    db:      firestore.AsyncClient = Depends(get_db),
) -> ScreeningRuleResponse:
    _require_admin(partner)

    doc = await db.collection(_SCREENING_RULES_COLLECTION).document(rule_id).get()
    if not doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error":   "NOT_FOUND",
                "message": f"Screening rule '{rule_id}' not found",
                "details": [],
            },
        )
    return _rule_doc_to_response(doc.to_dict())


# PUT /admin/settings/screening-rules/{rule_id}
@router.put(
    "/screening-rules/{rule_id}",
    response_model=ScreeningRuleResponse,
    summary="Replace a screening rule",
    description="Full replacement. The `ruleId` in the URL must match the document — the body's `ruleId` field is overridden.",
)
async def update_screening_rule(
    rule_id: str,
    body:    CreateScreeningRuleRequest,
    partner: PartnerContext = Depends(get_partner),
    db:      firestore.AsyncClient = Depends(get_db),
) -> ScreeningRuleResponse:
    _require_admin(partner)

    doc_ref  = db.collection(_SCREENING_RULES_COLLECTION).document(rule_id)
    existing = await doc_ref.get()
    if not existing.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error":   "NOT_FOUND",
                "message": f"Screening rule '{rule_id}' not found",
                "details": [],
            },
        )

    now        = datetime.utcnow()
    updated_by = partner.raw_claims.get("email") or partner.partner_id
    # Preserve original createdAt; replace everything else
    original   = existing.to_dict() or {}
    doc_data   = {
        **body.model_dump(),
        "ruleId":    rule_id,   # URL param is authoritative
        "params":    body.params.model_dump(exclude_none=True),
        "createdAt": original.get("createdAt", firestore.SERVER_TIMESTAMP),
        "updatedAt": firestore.SERVER_TIMESTAMP,
        "updatedBy": updated_by,
    }
    await doc_ref.set(doc_data, merge=False)
    reset_rules_cache()

    logger.info("screening_rule_updated", rule_id=rule_id, updated_by=updated_by)
    return _rule_doc_to_response({**doc_data, "updatedAt": now.isoformat() + "Z", "updatedBy": updated_by})


# DELETE /admin/settings/screening-rules/{rule_id}
@router.delete(
    "/screening-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a screening rule",
)
async def delete_screening_rule(
    rule_id: str,
    partner: PartnerContext = Depends(get_partner),
    db:      firestore.AsyncClient = Depends(get_db),
) -> Response:
    _require_admin(partner)

    doc_ref  = db.collection(_SCREENING_RULES_COLLECTION).document(rule_id)
    existing = await doc_ref.get()
    if not existing.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error":   "NOT_FOUND",
                "message": f"Screening rule '{rule_id}' not found",
                "details": [],
            },
        )

    await doc_ref.delete()
    reset_rules_cache()

    logger.info("screening_rule_deleted", rule_id=rule_id,
                updated_by=partner.raw_claims.get("email") or partner.partner_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
