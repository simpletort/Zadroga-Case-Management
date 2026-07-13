"""
api/services/duplicate_detection.py — Duplicate lead and idempotency detection.

Duplicate tiers (per AI_CONTEXT.md):
  - Hard (P1): SSN + DOB  → auto-flag Disqualified (mass_tort)
  - Soft (P1): email + phone → 409 DUPLICATE_LEAD
  - Fuzzy (P3): Name + DOB + phone → Needs Review (not yet implemented)
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Optional
from google.cloud import firestore
from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class DuplicateMatch:
    """Result of a hard-duplicate check."""
    matched_case_id: str
    match_type: str   # "ssn_dob"


async def detect_ssn_dob_duplicate(
    ssn: Optional[str],
    date_of_birth: Optional[date],
    db: firestore.AsyncClient,
) -> Optional[DuplicateMatch]:
    """
    Hard duplicate check for mass_tort leads (AI_CONTEXT.md spec):
      SSN + DOB → auto-flag as duplicate.

    Uses ssn_hash (deterministic SHA-256) for Firestore query since
    ssn_encrypted is non-deterministic (KMS random padding).

    Returns DuplicateMatch with the existing caseId, or None.
    """
    if not ssn or not date_of_birth:
        return None

    from shared.crypto import compute_ssn_hash
    ssn_hash = compute_ssn_hash(ssn)

    settings = get_settings()

    # Firestore composite query: ssn_hash == X AND dateOfBirth == Y
    # Requires a composite index on (ssn_hash, dateOfBirth) — see DEPLOY note.
    dob_str = date_of_birth.isoformat()
    query = (
        db.collection(settings.firestore_cases_collection)
        .where(filter=firestore.FieldFilter("ssn_hash", "==", ssn_hash))
        .where(filter=firestore.FieldFilter("dateOfBirth", "==", dob_str))
        .limit(1)
    )

    async for doc in query.stream():
        logger.info(
            "ssn_dob_duplicate_found",
            matched_case_id=doc.id,
        )
        return DuplicateMatch(matched_case_id=doc.id, match_type="ssn_dob")

    return None


async def detect_duplicate(email: str, phone: str, db: firestore.AsyncClient) -> Optional[str]:
    """Return existing case_id if email AND phone already exist, else None."""
    settings = get_settings()
    query = (
        db.collection(settings.firestore_cases_collection)
        .where("email", "==", email)
        .where("phone", "==", phone)
        .limit(1)
    )
    async for doc in query.stream():
        return doc.id
    return None


async def is_idempotent_retry(request_id: str, db: firestore.AsyncClient) -> Optional[str]:
    """Return existing case_id if this requestId was already processed."""
    settings = get_settings()
    query = (
        db.collection(settings.firestore_cases_collection)
        .where("requestId", "==", request_id)
        .limit(1)
    )
    async for doc in query.stream():
        return doc.id
    return None
