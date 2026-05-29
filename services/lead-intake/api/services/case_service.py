"""
api/services/case_service.py — Firestore case CRUD with atomic ID generation.

Changes vs original:
  - apply_vcf_screening_result(): writes VCF screening output + creates
    staff in-app notification in the notifications collection.
  - write_staff_screening_notification(): writes a Firestore notification
    document for the assigned paralegal/admin_staff to see in their dashboard.
    This replaces the removed notification_dispatcher Cloud Function.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from google.cloud import firestore
from google.cloud.firestore_v1 import AsyncTransaction

from config import get_settings
from models.lead import CaseDocument, CaseStatus, LeadRequest, VCFEligibility
from logging_config import get_logger

logger = get_logger(__name__)

_case_id_prefix_cache: Optional[str] = None


async def _fetch_prefix(db: firestore.AsyncClient) -> str:
    global _case_id_prefix_cache
    if _case_id_prefix_cache is not None:
        return _case_id_prefix_cache
    doc = await db.collection("firmSettings").document("case_id_prefix").get()
    _case_id_prefix_cache = (doc.to_dict() or {}).get("prefix", "CASE") if doc.exists else "CASE"
    return _case_id_prefix_cache


def _counter_doc_id(prefix: str, year: int, month: int) -> str:
    return f"{prefix}-{year:04d}-{month:02d}"


def _case_id(prefix: str, year: int, month: int, count: int) -> str:
    return f"{prefix}-{year:04d}-{month:02d}-{count:04d}"


async def _get_next_case_id(
    db:          firestore.AsyncClient,
    transaction: AsyncTransaction,
    now:         datetime,
) -> str:
    settings    = get_settings()
    prefix      = await _fetch_prefix(db)
    counter_id  = _counter_doc_id(prefix, now.year, now.month)
    counter_ref = db.collection(settings.firestore_counters_collection).document(counter_id)
    counter_doc = await counter_ref.get(transaction=transaction)
    current_count = counter_doc.to_dict().get("count", 0) if counter_doc.exists else 0
    new_count     = current_count + 1
    transaction.set(
        counter_ref,
        {"count": new_count, "updatedAt": firestore.SERVER_TIMESTAMP, "yearMonth": counter_id},
        merge=True,
    )
    return _case_id(prefix, now.year, now.month, new_count)


async def create_case(
    lead:       LeadRequest,
    partner_id: str,
    request_id: str,
    db:         firestore.AsyncClient,
) -> CaseDocument:
    """Create a new case document in Firestore (atomic ID generation)."""
    settings = get_settings()
    now      = datetime.utcnow()

    @firestore.async_transactional
    async def _txn(transaction: AsyncTransaction) -> CaseDocument:
        case_id  = await _get_next_case_id(db, transaction, now)
        case     = CaseDocument.from_lead(
            lead=lead, case_id=case_id, partner_id=partner_id, request_id=request_id,
        )
        case_ref = db.collection(settings.firestore_cases_collection).document(case_id)
        transaction.set(case_ref, case.to_firestore_dict())
        logger.info("case_created", case_id=case_id, partner_id=partner_id)
        return case

    transaction = db.transaction()
    return await _txn(transaction)


async def write_staff_screening_notification(
    case_id:     str,
    first_name:  str,
    last_name:   str,
    eligibility: str,
    score:       int,
    flags:       list[str],
    assigned_to: Optional[str],
    db:          firestore.AsyncClient,
) -> None:
    """
    Write an in-app notification document to /notifications/{id} for staff.

    This replaces the removed notification_dispatcher Cloud Function.
    The auth-rbac frontend reads the notifications collection to show
    alerts in the staff dashboard.

    Notification types match the old Cloud Function schema so the frontend
    doesn't need changes:
      CASE_QUALIFIED    — paralegal can convert to active case
      CASE_DISQUALIFIED — admin staff awareness
      CASE_NEEDS_REVIEW — paralegal manual review required

    Firestore document schema:
      notificationId : str
      type           : str
      title          : str
      body           : str
      caseId         : str
      assignedTo     : str (uid or "admin_pool")
      priority       : "high" | "normal"
      read           : false
      createdAt      : SERVER_TIMESTAMP
    """
    _TYPE_MAP = {
        "eligible":     ("CASE_QUALIFIED",    "high"),
        "ineligible":   ("CASE_DISQUALIFIED", "normal"),
        "needs_review": ("CASE_NEEDS_REVIEW", "high"),
    }
    notif_type, priority = _TYPE_MAP.get(eligibility, ("CASE_SCREENED", "normal"))
    full_name = f"{first_name} {last_name}".strip()

    if eligibility == "eligible":
        title = f"Case {case_id} qualified for VCF"
        body  = f"{full_name} passed VCF screening (score: {score}). Ready to convert to active case."
    elif eligibility == "ineligible":
        title = f"Case {case_id} did not qualify"
        body  = f"{full_name} did not meet VCF eligibility criteria."
    else:
        flag_summary = "; ".join(flags[:3]) if flags else "See screening details"
        title = f"Case {case_id} requires manual review"
        body  = f"Flags: {flag_summary}"

    notif_ref = db.collection("notifications").document()
    try:
        await notif_ref.set({
            "notificationId": notif_ref.id,
            "type":           notif_type,
            "title":          title,
            "body":           body,
            "caseId":         case_id,
            "assignedTo":     assigned_to or "admin_pool",
            "priority":       priority,
            "read":           False,
            "createdAt":      firestore.SERVER_TIMESTAMP,
        })
        logger.info(
            "staff_notification_written",
            case_id=case_id,
            notif_type=notif_type,
            assigned_to=assigned_to,
        )
    except Exception as exc:
        # Non-fatal — case is already created and screened; notification is supplementary
        logger.error("staff_notification_write_failed", case_id=case_id, error=str(exc))


async def apply_vcf_screening_result(
    case_id:           str,
    eligibility:       str,
    new_status:        str,
    screening_details: dict,
    db:                firestore.AsyncClient,
) -> None:
    """
    Write VCF screening results to the case document.
    Called synchronously from POST /leads immediately after run_screening().
    """
    settings      = get_settings()
    doc_ref       = db.collection(settings.firestore_cases_collection).document(case_id)
    now           = datetime.utcnow()
    history_entry = {
        "status":    new_status,
        "timestamp": now.isoformat(),
        "updatedBy": "vcf-screener-inline",
        "note":      f"VCF screening: {eligibility} (score={screening_details.get('score', 0)})",
    }
    await doc_ref.update({
        "vcfEligibility":      eligibility,
        "vcfScreeningDetails": screening_details,
        "status":              new_status,
        "statusHistory":       firestore.ArrayUnion([history_entry]),
        "updatedAt":           firestore.SERVER_TIMESTAMP,
    })
    logger.info(
        "vcf_screening_applied",
        case_id=case_id,
        eligibility=eligibility,
        status=new_status,
    )


async def get_case(case_id: str, db: firestore.AsyncClient) -> Optional[CaseDocument]:
    settings = get_settings()
    doc      = await db.collection(settings.firestore_cases_collection).document(case_id).get()
    if not doc.exists:
        return None
    try:
        return CaseDocument(**doc.to_dict())
    except Exception as exc:
        logger.error("case_deserialisation_failed", case_id=case_id, error=str(exc))
        raise


async def list_cases(db: firestore.AsyncClient, filters: dict, limit: int = 50) -> list[dict]:
    settings = get_settings()
    query    = db.collection(settings.firestore_cases_collection)
    if filters.get("status"):
        query = query.where("status", "==", filters["status"])
    if filters.get("vcfEligibility"):
        query = query.where("vcfEligibility", "==", filters["vcfEligibility"])
    query = query.order_by("createdAt", direction=firestore.Query.DESCENDING).limit(limit)
    return [doc.to_dict() async for doc in query.stream()]


async def update_case_status(
    case_id:    str,
    new_status: str,
    updated_by: str,
    note:       str,
    db:         firestore.AsyncClient,
) -> None:
    settings      = get_settings()
    now           = datetime.utcnow()
    doc_ref       = db.collection(settings.firestore_cases_collection).document(case_id)
    history_entry = {
        "status":    new_status,
        "timestamp": now.isoformat(),
        "updatedBy": updated_by,
        "note":      note,
    }
    update_payload = {
        "status":        new_status,
        "statusHistory": firestore.ArrayUnion([history_entry]),
        "updatedAt":     firestore.SERVER_TIMESTAMP,
    }
    # When a lead is activated it becomes a full case — flip the flag
    if new_status == CaseStatus.ACTIVE.value:
        update_payload["isLead"] = False

    await doc_ref.update(update_payload)
    logger.info(
        "case_status_updated",
        case_id=case_id,
        new_status=new_status,
        updated_by=updated_by,
    )


async def update_case_vcf_status(
    case_id:           str,
    vcf_eligibility:   str,
    screening_details: dict,
    db:                firestore.AsyncClient,
) -> None:
    """Manual override — updates VCF fields without touching status history."""
    settings = get_settings()
    doc_ref  = db.collection(settings.firestore_cases_collection).document(case_id)
    await doc_ref.update({
        "vcfEligibility":      vcf_eligibility,
        "vcfScreeningDetails": screening_details,
        "updatedAt":           firestore.SERVER_TIMESTAMP,
    })
    logger.info("case_vcf_updated", case_id=case_id, vcf_eligibility=vcf_eligibility)
#     staff in-app notification in the notifications collection.
#   - write_staff_screening_notification(): writes a Firestore notification
#     document for the assigned paralegal/admin_staff to see in their dashboard.
#     This replaces the removed notification_dispatcher Cloud Function.
# """
# from __future__ import annotations

# from datetime import datetime
# from typing import Optional

# from google.cloud import firestore
# from google.cloud.firestore_v1 import AsyncTransaction

# from config import get_settings
# from models.lead import CaseDocument, CaseStatus, LeadRequest, VCFEligibility
# from logging_config import get_logger

# logger = get_logger(__name__)


# def _counter_doc_id(year: int, month: int) -> str:
#     return f"ZAD-{year:04d}-{month:02d}"


# def _case_id(year: int, month: int, count: int) -> str:
#     return f"ZAD-{year:04d}-{month:02d}-{count:04d}"


# async def _get_next_case_id(
#     db:          firestore.AsyncClient,
#     transaction: AsyncTransaction,
#     now:         datetime,
# ) -> str:
#     settings    = get_settings()
#     counter_id  = _counter_doc_id(now.year, now.month)
#     counter_ref = db.collection(settings.firestore_counters_collection).document(counter_id)
#     counter_doc = await counter_ref.get(transaction=transaction)
#     current_count = counter_doc.to_dict().get("count", 0) if counter_doc.exists else 0
#     new_count     = current_count + 1
#     transaction.set(
#         counter_ref,
#         {"count": new_count, "updatedAt": firestore.SERVER_TIMESTAMP, "yearMonth": counter_id},
#         merge=True,
#     )
#     return _case_id(now.year, now.month, new_count)


# async def create_case(
#     lead:       LeadRequest,
#     partner_id: str,
#     request_id: str,
#     db:         firestore.AsyncClient,
# ) -> CaseDocument:
#     """Create a new case document in Firestore (atomic ID generation)."""
#     settings = get_settings()
#     now      = datetime.utcnow()

#     @firestore.async_transactional
#     async def _txn(transaction: AsyncTransaction) -> CaseDocument:
#         case_id  = await _get_next_case_id(db, transaction, now)
#         case     = CaseDocument.from_lead(
#             lead=lead, case_id=case_id, partner_id=partner_id, request_id=request_id,
#         )
#         case_ref = db.collection(settings.firestore_cases_collection).document(case_id)
#         transaction.set(case_ref, case.to_firestore_dict())
#         logger.info("case_created", case_id=case_id, partner_id=partner_id)
#         return case

#     transaction = db.transaction()
#     return await _txn(transaction)


# async def write_staff_screening_notification(
#     case_id:     str,
#     first_name:  str,
#     last_name:   str,
#     eligibility: str,
#     score:       int,
#     flags:       list[str],
#     assigned_to: Optional[str],
#     db:          firestore.AsyncClient,
# ) -> None:
#     """
#     Write an in-app notification document to /notifications/{id} for staff.

#     This replaces the removed notification_dispatcher Cloud Function.
#     The auth-rbac frontend reads the notifications collection to show
#     alerts in the staff dashboard.

#     Notification types match the old Cloud Function schema so the frontend
#     doesn't need changes:
#       CASE_QUALIFIED    — paralegal can convert to active case
#       CASE_DISQUALIFIED — admin staff awareness
#       CASE_NEEDS_REVIEW — paralegal manual review required

#     Firestore document schema:
#       notificationId : str
#       type           : str
#       title          : str
#       body           : str
#       caseId         : str
#       assignedTo     : str (uid or "admin_pool")
#       priority       : "high" | "normal"
#       read           : false
#       createdAt      : SERVER_TIMESTAMP
#     """
#     _TYPE_MAP = {
#         "eligible":     ("CASE_QUALIFIED",    "high"),
#         "ineligible":   ("CASE_DISQUALIFIED", "normal"),
#         "needs_review": ("CASE_NEEDS_REVIEW", "high"),
#     }
#     notif_type, priority = _TYPE_MAP.get(eligibility, ("CASE_SCREENED", "normal"))
#     full_name = f"{first_name} {last_name}".strip()

#     if eligibility == "eligible":
#         title = f"Case {case_id} qualified for VCF"
#         body  = f"{full_name} passed VCF screening (score: {score}). Ready to convert to active case."
#     elif eligibility == "ineligible":
#         title = f"Case {case_id} did not qualify"
#         body  = f"{full_name} did not meet VCF eligibility criteria."
#     else:
#         flag_summary = "; ".join(flags[:3]) if flags else "See screening details"
#         title = f"Case {case_id} requires manual review"
#         body  = f"Flags: {flag_summary}"

#     notif_ref = db.collection("notifications").document()
#     try:
#         await notif_ref.set({
#             "notificationId": notif_ref.id,
#             "type":           notif_type,
#             "title":          title,
#             "body":           body,
#             "caseId":         case_id,
#             "assignedTo":     assigned_to or "admin_pool",
#             "priority":       priority,
#             "read":           False,
#             "createdAt":      firestore.SERVER_TIMESTAMP,
#         })
#         logger.info(
#             "staff_notification_written",
#             case_id=case_id,
#             notif_type=notif_type,
#             assigned_to=assigned_to,
#         )
#     except Exception as exc:
#         # Non-fatal — case is already created and screened; notification is supplementary
#         logger.error("staff_notification_write_failed", case_id=case_id, error=str(exc))


# async def apply_vcf_screening_result(
#     case_id:           str,
#     eligibility:       str,
#     new_status:        str,
#     screening_details: dict,
#     db:                firestore.AsyncClient,
# ) -> None:
#     """
#     Write VCF screening results to the case document.
#     Called synchronously from POST /leads immediately after run_screening().
#     """
#     settings      = get_settings()
#     doc_ref       = db.collection(settings.firestore_cases_collection).document(case_id)
#     now           = datetime.utcnow()
#     history_entry = {
#         "status":    new_status,
#         "timestamp": now.isoformat(),
#         "updatedBy": "vcf-screener-inline",
#         "note":      f"VCF screening: {eligibility} (score={screening_details.get('score', 0)})",
#     }
#     await doc_ref.update({
#         "vcfEligibility":      eligibility,
#         "vcfScreeningDetails": screening_details,
#         "status":              new_status,
#         "statusHistory":       firestore.ArrayUnion([history_entry]),
#         "updatedAt":           firestore.SERVER_TIMESTAMP,
#     })
#     logger.info(
#         "vcf_screening_applied",
#         case_id=case_id,
#         eligibility=eligibility,
#         status=new_status,
#     )


# async def get_case(case_id: str, db: firestore.AsyncClient) -> Optional[CaseDocument]:
#     settings = get_settings()
#     doc      = await db.collection(settings.firestore_cases_collection).document(case_id).get()
#     if not doc.exists:
#         return None
#     return CaseDocument(**doc.to_dict())


# async def list_cases(db: firestore.AsyncClient, filters: dict, limit: int = 50) -> list[dict]:
#     settings = get_settings()
#     query    = db.collection(settings.firestore_cases_collection)
#     if filters.get("status"):
#         query = query.where("status", "==", filters["status"])
#     if filters.get("vcfEligibility"):
#         query = query.where("vcfEligibility", "==", filters["vcfEligibility"])
#     query = query.order_by("createdAt", direction=firestore.Query.DESCENDING).limit(limit)
#     return [doc.to_dict() async for doc in query.stream()]


# async def update_case_status(
#     case_id:    str,
#     new_status: str,
#     updated_by: str,
#     note:       str,
#     db:         firestore.AsyncClient,
# ) -> None:
#     settings      = get_settings()
#     now           = datetime.utcnow()
#     doc_ref       = db.collection(settings.firestore_cases_collection).document(case_id)
#     history_entry = {
#         "status":    new_status,
#         "timestamp": now.isoformat(),
#         "updatedBy": updated_by,
#         "note":      note,
#     }
#     await doc_ref.update({
#         "status":        new_status,
#         "statusHistory": firestore.ArrayUnion([history_entry]),
#         "updatedAt":     firestore.SERVER_TIMESTAMP,
#     })
#     logger.info(
#         "case_status_updated",
#         case_id=case_id,
#         new_status=new_status,
#         updated_by=updated_by,
#     )


# async def update_case_vcf_status(
#     case_id:           str,
#     vcf_eligibility:   str,
#     screening_details: dict,
#     db:                firestore.AsyncClient,
# ) -> None:
#     """Manual override — updates VCF fields without touching status history."""
#     settings = get_settings()
#     doc_ref  = db.collection(settings.firestore_cases_collection).document(case_id)
#     await doc_ref.update({
#         "vcfEligibility":      vcf_eligibility,
#         "vcfScreeningDetails": screening_details,
#         "updatedAt":           firestore.SERVER_TIMESTAMP,
#     })
#     logger.info("case_vcf_updated", case_id=case_id, vcf_eligibility=vcf_eligibility)
