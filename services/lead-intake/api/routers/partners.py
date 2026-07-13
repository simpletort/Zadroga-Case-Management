"""
api/routers/partners.py — Partner management: create partners, issue/revoke API keys.

Admin-only endpoints.  Accessible by:
  1. A partner JWT with raw_claims["admin"] == True (legacy)
  2. A Firebase Auth token (from auth-rbac) with role "senior_partner" or "system_admin"

Role values from auth-rbac: system_admin | senior_partner | junior_partner | paralegal | admin_staff
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from google.cloud import firestore

from config import get_settings
from middleware.auth import PartnerContext, get_partner
from models.partner import (
    ApiKeyEntry, ApiKeyResponse, CreateApiKeyRequest,
    CreatePartnerRequest, PartnerDocument, PartnerStatsResponse,
)
from services.firestore_client import get_db
from logging_config import get_logger

logger   = get_logger(__name__)
router   = APIRouter(prefix="/admin/partners", tags=["Partner Management"])
settings = get_settings()

# Roles from auth-rbac that have partner management rights
_ADMIN_ROLES = {"senior_partner", "system_admin"}


def _require_admin(partner: PartnerContext) -> PartnerContext:
    """
    Enforce admin access.  Accepts:
      - Firebase JWT with role in _ADMIN_ROLES
      - Legacy partner JWT with raw_claims["admin"] == True
    """
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


@router.post("", status_code=201, summary="Create a new marketing partner")
async def create_partner(
    body:    CreatePartnerRequest,
    partner: PartnerContext = Depends(get_partner),
    db:      firestore.AsyncClient = Depends(get_db),
) -> dict:
    _require_admin(partner)
    settings_obj = get_settings()
    now          = datetime.utcnow()
    partner_id   = f"partner_{uuid.uuid4().hex[:12]}"

    doc = PartnerDocument(
        partnerId=partner_id, name=body.name, active=True,
        allowedIps=body.allowedIps, requireHmac=body.requireHmac,
        createdAt=now, updatedAt=now,
    )
    await db.collection(settings_obj.firestore_partners_collection).document(partner_id).set(doc.model_dump())
    logger.info("partner_created", partner_id=partner_id, name=body.name)
    return {"partnerId": partner_id, "name": body.name, "createdAt": now.isoformat()}


@router.get("", summary="List all partners")
async def list_partners(
    partner: PartnerContext = Depends(get_partner),
    db:      firestore.AsyncClient = Depends(get_db),
) -> list[dict]:
    _require_admin(partner)
    settings_obj = get_settings()
    docs         = [doc async for doc in db.collection(settings_obj.firestore_partners_collection).stream()]
    return [
        {
            "partnerId":    d.get("partnerId"),
            "name":         d.get("name"),
            "active":       d.get("active"),
            "requestCount": d.get("requestCount", 0),
            "activeKeys":   sum(1 for k in d.get("apiKeys", []) if k.get("active")),
            "lastRequestAt": d.get("lastRequestAt"),
            "createdAt":    d.get("createdAt"),
        }
        for doc in docs
        for d in [doc.to_dict()]
    ]


@router.post("/{partner_id}/keys", status_code=201, summary="Generate a new API key for a partner")
async def create_api_key(
    partner_id: str,
    body:       CreateApiKeyRequest,
    partner:    PartnerContext = Depends(get_partner),
    db:         firestore.AsyncClient = Depends(get_db),
) -> ApiKeyResponse:
    _require_admin(partner)
    settings_obj = get_settings()
    now          = datetime.utcnow()

    partner_ref = db.collection(settings_obj.firestore_partners_collection).document(partner_id)
    partner_doc = await partner_ref.get()
    if not partner_doc.exists:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": f"Partner {partner_id} not found", "details": []})

    raw_key  = f"zad_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_id   = f"key_{uuid.uuid4().hex[:12]}"

    key_entry = ApiKeyEntry(
        keyId=key_id, label=body.label, keyHash=key_hash,
        createdAt=now, expiresAt=body.expiresAt, active=True,
    )
    await partner_ref.update({
        "apiKeys":   firestore.ArrayUnion([key_entry.model_dump()]),
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })
    logger.info("api_key_created", partner_id=partner_id, key_id=key_id)
    return ApiKeyResponse(keyId=key_id, apiKey=raw_key, label=body.label, createdAt=now, expiresAt=body.expiresAt)


@router.delete("/{partner_id}/keys/{key_id}", summary="Revoke an API key")
async def revoke_api_key(
    partner_id: str,
    key_id:     str,
    partner:    PartnerContext = Depends(get_partner),
    db:         firestore.AsyncClient = Depends(get_db),
) -> dict:
    _require_admin(partner)
    settings_obj = get_settings()
    partner_ref  = db.collection(settings_obj.firestore_partners_collection).document(partner_id)
    partner_doc  = await partner_ref.get()
    if not partner_doc.exists:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Partner not found", "details": []})

    data         = partner_doc.to_dict()
    keys         = data.get("apiKeys", [])
    updated_keys = []
    found        = False
    for k in keys:
        if k.get("keyId") == key_id:
            k["active"] = False
            found       = True
        updated_keys.append(k)

    if not found:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": f"Key {key_id} not found", "details": []})

    await partner_ref.update({"apiKeys": updated_keys, "updatedAt": firestore.SERVER_TIMESTAMP})
    logger.info("api_key_revoked", partner_id=partner_id, key_id=key_id)
    return {"keyId": key_id, "status": "revoked", "revokedAt": datetime.utcnow().isoformat()}


@router.get("/{partner_id}/stats", summary="Get partner usage stats")
async def get_partner_stats(
    partner_id: str,
    partner:    PartnerContext = Depends(get_partner),
    db:         firestore.AsyncClient = Depends(get_db),
) -> PartnerStatsResponse:
    _require_admin(partner)
    settings_obj = get_settings()
    doc          = await db.collection(settings_obj.firestore_partners_collection).document(partner_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Partner not found", "details": []})
    data = doc.to_dict()
    return PartnerStatsResponse(
        partnerId=partner_id, name=data.get("name", ""),
        requestCount=data.get("requestCount", 0),
        lastRequestAt=data.get("lastRequestAt"),
        activeKeys=sum(1 for k in data.get("apiKeys", []) if k.get("active")),
    )
