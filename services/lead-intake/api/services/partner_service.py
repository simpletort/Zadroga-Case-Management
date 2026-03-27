"""
api/services/partner_service.py — Partner lifecycle management.
"""
from __future__ import annotations
from google.cloud import firestore
from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)


async def get_partner_by_id(partner_id: str, db: firestore.AsyncClient) -> dict | None:
    settings = get_settings()
    doc = await db.collection(settings.firestore_partners_collection).document(partner_id).get()
    return doc.to_dict() if doc.exists else None


async def deactivate_partner(partner_id: str, db: firestore.AsyncClient) -> None:
    settings = get_settings()
    ref = db.collection(settings.firestore_partners_collection).document(partner_id)
    await ref.update({"active": False, "updatedAt": firestore.SERVER_TIMESTAMP})
    logger.info("partner_deactivated", partner_id=partner_id)
