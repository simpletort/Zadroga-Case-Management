"""
api/services/case_service.py — Firestore case CRUD with atomic ID generation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from google.cloud import firestore
from google.cloud.firestore_v1 import AsyncTransaction

from config import get_settings
from models.lead import CaseDocument, LeadRequest, CaseStatus, StatusHistoryEntry
from logging_config import get_logger

logger = get_logger(__name__)


def _counter_doc_id(year: int, month: int) -> str:
    return f"ZAD-{year:04d}-{month:02d}"


def _case_id(year: int, month: int, count: int) -> str:
    return f"ZAD-{year:04d}-{month:02d}-{count:04d}"


async def _get_next_case_id(
    db: firestore.AsyncClient,
    transaction: AsyncTransaction,
    now: datetime,
) -> str:
    settings = get_settings()
    counter_id = _counter_doc_id(now.year, now.month)
    counter_ref = db.collection(settings.firestore_counters_collection).document(counter_id)
    counter_doc = await transaction.get(counter_ref)
    current_count = counter_doc.to_dict().get("count", 0) if counter_doc.exists else 0
    new_count = current_count + 1
    transaction.set(counter_ref, {"count": new_count, "updatedAt": firestore.SERVER_TIMESTAMP, "yearMonth": counter_id}, merge=True)
    return _case_id(now.year, now.month, new_count)


async def create_case(
    lead: LeadRequest,
    partner_id: str,
    request_id: str,
    db: firestore.AsyncClient,
) -> CaseDocument:
    settings = get_settings()
    now = datetime.utcnow()

    @firestore.async_transactional
    async def _txn(transaction: AsyncTransaction) -> CaseDocument:
        case_id = await _get_next_case_id(db, transaction, now)
        case = CaseDocument.from_lead(lead=lead, case_id=case_id, partner_id=partner_id, request_id=request_id)
        case_ref = db.collection(settings.firestore_cases_collection).document(case_id)
        transaction.set(case_ref, case.to_firestore_dict())
        logger.info("case_created", case_id=case_id, partner_id=partner_id)
        return case

    transaction = db.transaction()
    return await _txn(transaction)


async def get_case(case_id: str, db: firestore.AsyncClient) -> Optional[CaseDocument]:
    settings = get_settings()
    doc = await db.collection(settings.firestore_cases_collection).document(case_id).get()
    if not doc.exists:
        return None
    return CaseDocument(**doc.to_dict())


async def list_cases(db: firestore.AsyncClient, filters: dict, limit: int = 50) -> list[dict]:
    settings = get_settings()
    query = db.collection(settings.firestore_cases_collection)
    if filters.get("status"):
        query = query.where("status", "==", filters["status"])
    if filters.get("vcfEligibility"):
        query = query.where("vcfEligibility", "==", filters["vcfEligibility"])
    query = query.order_by("createdAt", direction=firestore.Query.DESCENDING).limit(limit)
    return [doc.to_dict() async for doc in query.stream()]


async def update_case_status(
    case_id: str,
    new_status: str,
    updated_by: str,
    note: str,
    db: firestore.AsyncClient,
) -> None:
    settings = get_settings()
    now = datetime.utcnow()
    doc_ref = db.collection(settings.firestore_cases_collection).document(case_id)

    history_entry = {
        "status": new_status,
        "timestamp": now.isoformat(),
        "updatedBy": updated_by,
        "note": note,
    }

    await doc_ref.update({
        "status": new_status,
        "statusHistory": firestore.ArrayUnion([history_entry]),
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })
    logger.info("case_status_updated", case_id=case_id, new_status=new_status, updated_by=updated_by)


async def update_case_vcf_status(
    case_id: str,
    vcf_eligibility: str,
    screening_details: dict,
    db: firestore.AsyncClient,
) -> None:
    settings = get_settings()
    doc_ref = db.collection(settings.firestore_cases_collection).document(case_id)
    await doc_ref.update({
        "vcfEligibility": vcf_eligibility,
        "vcfScreeningDetails": screening_details,
        "status": "Screened",
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })
    logger.info("case_vcf_updated", case_id=case_id, vcf_eligibility=vcf_eligibility)
