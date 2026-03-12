"""
services/case_service.py — Firestore case creation with atomic ID generation.

Case ID format: ZAD-YYYY-MM-XXXX
  - YYYY: 4-digit year
  - MM: 2-digit month (zero-padded)
  - XXXX: 4-digit monthly counter (zero-padded, resets each month)

Atomicity:
  Firestore transactions are used to read-increment-write the monthly counter
  in a single atomic operation. This prevents race conditions under concurrent
  requests and ensures no two cases share the same ID.

Counter document path: /counters/ZAD-YYYY-MM
  Fields: { count: int, updatedAt: timestamp }

Case document path: /cases/ZAD-YYYY-MM-XXXX

Idempotency:
  The requestId field on each case document acts as a dedup key.
  If a transaction succeeds but the HTTP response is lost (retry scenario),
  duplicate_detection.is_idempotent_retry() will catch the re-submission.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from google.cloud import firestore
from google.cloud.firestore_v1 import AsyncTransaction

from config import get_settings
from models.lead import CaseDocument, LeadRequest, CaseStatus
from logging_config import get_logger

logger = get_logger(__name__)


def _counter_doc_id(year: int, month: int) -> str:
    """Returns e.g. 'ZAD-2025-03' for the counter document."""
    return f"ZAD-{year:04d}-{month:02d}"


def _case_id(year: int, month: int, count: int) -> str:
    """Returns e.g. 'ZAD-2025-03-0042'."""
    return f"ZAD-{year:04d}-{month:02d}-{count:04d}"


async def _get_next_case_id(
    db: firestore.AsyncClient,
    transaction: AsyncTransaction,
    now: datetime,
) -> str:
    """
    Atomically increment the monthly counter and return the next case ID.
    Called WITHIN an existing Firestore transaction.
    """
    settings = get_settings()
    counters_col = settings.firestore_counters_collection

    counter_id = _counter_doc_id(now.year, now.month)
    counter_ref = db.collection(counters_col).document(counter_id)

    counter_doc = await transaction.get(counter_ref)

    if counter_doc.exists:
        current_count = counter_doc.to_dict().get("count", 0)
    else:
        current_count = 0

    new_count = current_count + 1

    transaction.set(
        counter_ref,
        {
            "count": new_count,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "yearMonth": counter_id,
        },
        merge=True,
    )

    return _case_id(now.year, now.month, new_count)


async def create_case(
    lead: LeadRequest,
    partner_id: str,
    request_id: str,
    db: firestore.AsyncClient,
) -> CaseDocument:
    """
    Create a new case document in Firestore with an auto-generated ZAD ID.

    Steps (all within a single Firestore transaction):
      1. Increment monthly counter → generate case ID
      2. Write case document

    Returns the created CaseDocument.
    Raises on Firestore errors (caller handles HTTP response).
    """
    settings = get_settings()
    now = datetime.utcnow()

    @firestore.async_transactional
    async def _txn(transaction: AsyncTransaction) -> CaseDocument:
        # Step 1: Generate case ID atomically
        case_id = await _get_next_case_id(db, transaction, now)

        # Step 2: Build case document
        case = CaseDocument.from_lead(
            lead=lead,
            case_id=case_id,
            partner_id=partner_id,
            request_id=request_id,
        )

        # Step 3: Write to Firestore
        case_ref = db.collection(settings.firestore_cases_collection).document(case_id)
        transaction.set(case_ref, case.to_firestore_dict())

        logger.info(
            "case_created",
            case_id=case_id,
            partner_id=partner_id,
            request_id=request_id,
            status=case.status.value,
        )

        return case

    transaction = db.transaction()
    return await _txn(transaction)


async def get_case(
    case_id: str,
    db: firestore.AsyncClient,
) -> Optional[CaseDocument]:
    """Fetch a case document by ID. Returns None if not found."""
    settings = get_settings()
    doc_ref = db.collection(settings.firestore_cases_collection).document(case_id)
    doc = await doc_ref.get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    return CaseDocument(**data)


async def update_case_vcf_status(
    case_id: str,
    vcf_eligibility: str,
    screening_details: dict,
    db: firestore.AsyncClient,
) -> None:
    """Called by the VCF screener Cloud Function after screening."""
    settings = get_settings()
    doc_ref = db.collection(settings.firestore_cases_collection).document(case_id)
    await doc_ref.update({
        "vcfEligibility": vcf_eligibility,
        "vcfScreeningDetails": screening_details,
        "status": "Screened",
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })
    logger.info(
        "case_vcf_updated",
        case_id=case_id,
        vcf_eligibility=vcf_eligibility,
    )
