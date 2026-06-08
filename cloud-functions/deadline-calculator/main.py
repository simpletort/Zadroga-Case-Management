"""
Enrollment Workflow — Deadline Calculator Cloud Function (Gen 2)

Trigger: Firestore Eventarc — google.cloud.firestore.document.v1.written
         on: projects/{PROJECT_ID}/databases/{db}/documents/cases/{caseId}

Calculates the program registration filing deadline whenever:
  1. A case is created WITH a certificationDate
  2. The medicalInfo.certificationDate field changes
  3. The enrollment.certificationStatus changes to 'Enrolled'

Deadline rule type is read from firmSettings/deadlines.deadlineRuleType:
  cert_date_offset      — certificationDate + N years  (VCF / WTC pattern)
  injury_date_offset    — medicalInfo.injuryDate + N days  (Workers' Comp pattern)
  statute_of_limitations — createdAt + N years  (general statute clock)

Generic field names used (not program-specific):
  enrollment.certificationStatus   — replaces enrollment.wtcEnrollmentStatus
  enrollment.filingDeadline        — replaces enrollment.vcfFilingDeadline
  enrollment.deadlineStatus        — unchanged
  enrollment.daysUntilDeadline     — unchanged
  enrollment.deadlineCalculatedAt  — unchanged

Edge cases handled:
  - No base date: skip (deadline set later when date arrives)
  - Invalid date format: log warning, skip
  - Deadline already in the past: set status = 'expired', write timeline warning
  - Case in closed/terminal status: skip recalculation (loaded from firmSettings)

Environment variables:
  GCP_PROJECT_ID          — GCP project
  FIRESTORE_DATABASE_ID   — Firestore database (default: (default))
  PUBSUB_TOPIC_ENROLLMENT — Pub/Sub topic for enrollment events
  DEADLINE_YEARS          — fallback years offset when firmSettings/deadlines is absent
"""

import json
import logging
import os
import sys
from datetime import date, datetime, timezone

import functions_framework
from cloudevents.http import CloudEvent
from dateutil.relativedelta import relativedelta
from google.cloud import firestore, pubsub_v1

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ID   = os.environ["GCP_PROJECT_ID"]
FIRESTORE_DB = os.environ.get("FIRESTORE_DATABASE_ID", "simpletort-dev")
PUBSUB_TOPIC = os.environ.get("PUBSUB_TOPIC_ENROLLMENT", "enrollment-status-changes")

# Kept as ultimate fallback; primary source is firmSettings/deadlines.deadlineYears
DEADLINE_YEARS = int(os.environ.get("DEADLINE_YEARS", "2"))

# Fallback used when firmSettings/pipeline is absent or Firestore is unreachable
DEFAULT_SKIP_STATUSES: frozenset = frozenset({
    "Closed", "Settled", "Does Not Qualify", "Rejected"
})

_db: firestore.Client | None = None
_publisher: pubsub_v1.PublisherClient | None = None
_firm_config_cache: dict | None = None
_closed_statuses_cache: frozenset | None = None


def _get_db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client(project=PROJECT_ID, database=FIRESTORE_DB)
    return _db


def _get_publisher() -> pubsub_v1.PublisherClient:
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def _get_firm_config() -> dict:
    """
    Load deadline configuration from firmSettings/deadlines.
    Cached for the lifetime of the function instance (cold-start load).

    Falls back to env var DEADLINE_YEARS / hardcoded defaults when Firestore
    is unreachable so the function always has a usable configuration.

    Keys used:
      deadlineRuleType  — "cert_date_offset" | "injury_date_offset" | "statute_of_limitations"
      deadlineYears     — int, years offset for cert_date_offset / statute_of_limitations
      deadlineDays      — int, days offset for injury_date_offset
      statuteYears      — int, years offset for statute_of_limitations (falls back to deadlineYears)
    """
    global _firm_config_cache
    if _firm_config_cache is not None:
        return _firm_config_cache
    try:
        db = _get_db()
        doc = db.collection("firmSettings").document("deadlines").get()
        cfg = doc.to_dict() if doc.exists else {}
    except Exception as exc:
        logger.warning("Failed to load firmSettings/deadlines: %s; using defaults", exc)
        cfg = {}

    # Inject env-var fallback so existing deployments keep working without re-seeding
    cfg.setdefault("deadlineYears", DEADLINE_YEARS)
    _firm_config_cache = cfg
    return _firm_config_cache


def _get_closed_statuses() -> frozenset:
    """
    Load closed/terminal case statuses from firmSettings/pipeline.closedStatuses[].
    Cached for the lifetime of the function instance (cold-start load).

    Falls back to DEFAULT_SKIP_STATUSES when the document is absent or Firestore
    is unreachable so deadline recalculation is always correctly gated.
    """
    global _closed_statuses_cache
    if _closed_statuses_cache is not None:
        return _closed_statuses_cache
    try:
        db = _get_db()
        doc = db.collection("firmSettings").document("pipeline").get()
        statuses = (doc.to_dict() or {}).get("closedStatuses") if doc.exists else None
        if statuses:
            _closed_statuses_cache = frozenset(statuses)
            return _closed_statuses_cache
    except Exception as exc:
        logger.warning(
            "Failed to load firmSettings/pipeline.closedStatuses: %s; using defaults", exc
        )
    _closed_statuses_cache = DEFAULT_SKIP_STATUSES
    return _closed_statuses_cache


# ── Deadline calculation strategies ───────────────────────────────────────────

DEADLINE_RULES: dict = {
    "cert_date_offset": lambda base, cfg: (
        base + relativedelta(years=cfg.get("deadlineYears", 2))
    ),
    "injury_date_offset": lambda base, cfg: (
        base + relativedelta(days=cfg.get("deadlineDays", 730))
    ),
    "statute_of_limitations": lambda base, cfg: (
        base + relativedelta(years=cfg.get("statuteYears", cfg.get("deadlineYears", 3)))
    ),
}


def _get_base_date(new_fields: dict, rule_type: str) -> date | None:
    """
    Extract the base date for the configured rule type from Firestore proto fields.

    Rule → field mapping:
      cert_date_offset      → medicalInfo.certificationDate
      injury_date_offset    → medicalInfo.injuryDate
      statute_of_limitations → createdAt (top-level)

    Returns None when the field is absent or cannot be parsed.
    """
    if rule_type == "cert_date_offset":
        medical = _map_field(new_fields, "medicalInfo")
        raw = _str_field(medical, "certificationDate")
    elif rule_type == "injury_date_offset":
        medical = _map_field(new_fields, "medicalInfo")
        raw = _str_field(medical, "injuryDate")
    elif rule_type == "statute_of_limitations":
        raw = _str_field(new_fields, "createdAt")
    else:
        logger.warning("Unknown deadlineRuleType '%s' in _get_base_date", rule_type)
        return None

    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except (ValueError, TypeError) as exc:
        logger.warning(
            "Invalid date for rule '%s': '%s' — %s", rule_type, raw, exc
        )
        return None


def calculate_deadline(new_fields: dict, firm_config: dict) -> date | None:
    """
    Select and apply the configured deadline rule to the Firestore proto fields.

    Returns the calculated deadline date, or None if the required base date is missing.
    """
    rule_type = firm_config.get("deadlineRuleType", "cert_date_offset")
    rule_fn = DEADLINE_RULES.get(rule_type)

    if rule_fn is None:
        logger.warning(
            "Unknown deadlineRuleType '%s'; falling back to cert_date_offset", rule_type
        )
        rule_fn = DEADLINE_RULES["cert_date_offset"]
        rule_type = "cert_date_offset"

    base_date = _get_base_date(new_fields, rule_type)
    if base_date is None:
        return None

    return rule_fn(base_date, firm_config)


# ── Main entry point ───────────────────────────────────────────────────────────

@functions_framework.cloud_event
def calculate_filing_deadline(event: CloudEvent) -> None:
    """
    Triggered by Firestore document write on cases/{caseId}.
    Calculates and stores the program filing deadline when the relevant date field is present.
    """
    data = event.data or {}

    doc_name: str = (data.get("value") or {}).get("name", "")
    if not doc_name:
        logger.info("No document value in event; skipping (delete event)")
        return

    case_id = doc_name.rsplit("/", 1)[-1]
    logger.info("calculate_filing_deadline triggered caseId=%s", case_id)

    new_fields = (data.get("value") or {}).get("fields", {})
    old_fields = (data.get("oldValue") or {}).get("fields", {})

    # ── Skip closed/terminal cases ────────────────────────────────────────
    case_status = _str_field(new_fields, "status")
    if case_status in _get_closed_statuses():
        logger.info("Skipping closed/final case caseId=%s status=%s", case_id, case_status)
        return

    # ── Check triggering conditions ───────────────────────────────────────
    new_medical = _map_field(new_fields, "medicalInfo")
    old_medical = _map_field(old_fields, "medicalInfo")
    new_cert    = _str_field(new_medical, "certificationDate")
    old_cert    = _str_field(old_medical, "certificationDate")

    new_enrollment  = _map_field(new_fields, "enrollment")
    old_enrollment  = _map_field(old_fields, "enrollment")
    new_cert_status = _str_field(new_enrollment, "certificationStatus")
    old_cert_status = _str_field(old_enrollment, "certificationStatus")

    cert_date_changed = new_cert != old_cert and bool(new_cert)
    just_enrolled     = new_cert_status == "Enrolled" and old_cert_status != "Enrolled"
    is_new_doc        = not old_fields

    if not (cert_date_changed or just_enrolled or (is_new_doc and new_cert)):
        logger.info("No relevant change for deadline calc caseId=%s; skipping", case_id)
        return

    # ── Calculate deadline using configured strategy ───────────────────────
    firm_config   = _get_firm_config()
    deadline      = calculate_deadline(new_fields, firm_config)
    rule_type_used = firm_config.get("deadlineRuleType", "cert_date_offset")

    if deadline is None:
        logger.info(
            "Base date unavailable for caseId=%s (rule=%s); skipping",
            case_id, rule_type_used,
        )
        return

    today          = date.today()
    days_remaining = (deadline - today).days

    if days_remaining < 0:
        deadline_status = "expired"
    elif days_remaining <= 30:
        deadline_status = "warning_30"
    elif days_remaining <= 60:
        deadline_status = "warning_60"
    elif days_remaining <= 90:
        deadline_status = "warning_90"
    else:
        deadline_status = "active"

    logger.info(
        "filing_deadline_calculated caseId=%s deadline=%s daysRemaining=%d status=%s rule=%s",
        case_id, deadline.isoformat(), days_remaining, deadline_status, rule_type_used,
    )

    # ── Persist deadline to case document ────────────────────────────────
    db       = _get_db()
    case_ref = db.collection("cases").document(case_id)

    try:
        case_ref.update({
            "enrollment.filingDeadline":       deadline.isoformat(),
            "enrollment.deadlineStatus":       deadline_status,
            "enrollment.daysUntilDeadline":    days_remaining,
            "enrollment.deadlineCalculatedAt": firestore.SERVER_TIMESTAMP,
        })
    except Exception as exc:
        logger.error("Failed to update deadline for caseId=%s: %s", case_id, exc)
        return

    # ── Write timeline event ───────────────────────────────────────────────
    try:
        timeline_ref = case_ref.collection("timeline").document()
        description  = (
            "Filing deadline calculated: {} ({} days remaining)".format(
                deadline.isoformat(), days_remaining
            )
            if days_remaining >= 0
            else "Filing deadline EXPIRED: {} ({} days ago)".format(
                deadline.isoformat(), abs(days_remaining)
            )
        )
        timeline_ref.set({
            "eventId":     timeline_ref.id,
            "caseId":      case_id,
            "timestamp":   firestore.SERVER_TIMESTAMP,
            "eventType":   "DeadlineCalculated",
            "description": description,
            "performedBy": "system",
            "metadata": {
                "filingDeadline":    deadline.isoformat(),
                "daysRemaining":     days_remaining,
                "deadlineStatus":    deadline_status,
                "deadlineRuleType":  rule_type_used,
                "trigger": (
                    "certification_date_change" if cert_date_changed
                    else "certification_enrolled"
                ),
            },
        })
    except Exception as exc:
        logger.warning("Failed to write timeline event for caseId=%s: %s", case_id, exc)

    # ── Publish Pub/Sub event ──────────────────────────────────────────────
    try:
        publisher  = _get_publisher()
        topic_path = publisher.topic_path(PROJECT_ID, PUBSUB_TOPIC)
        payload    = json.dumps({
            "caseId":         case_id,
            "eventType":      "FilingDeadlineCalculated",
            "filingDeadline": deadline.isoformat(),
            "deadlineStatus": deadline_status,
            "daysRemaining":  days_remaining,
            "timestamp":      datetime.now(tz=timezone.utc).isoformat(),
        }).encode("utf-8")
        publisher.publish(topic_path, data=payload)
    except Exception as exc:
        logger.warning("Pub/Sub publish failed for caseId=%s: %s", case_id, exc)

    # ── Warn if expired ────────────────────────────────────────────────────
    if deadline_status == "expired":
        logger.warning(
            "EXPIRED_DEADLINE caseId=%s deadline=%s daysOverdue=%d",
            case_id, deadline.isoformat(), abs(days_remaining),
        )


# ── Firestore proto field helpers ──────────────────────────────────────────────

def _str_field(fields: dict, key: str) -> str:
    """Extract a string value from a Firestore proto fields map."""
    val = fields.get(key, {})
    return val.get("stringValue") or val.get("timestampValue", "")


def _map_field(fields: dict, key: str) -> dict:
    """Extract a nested map from a Firestore proto fields map."""
    return fields.get(key, {}).get("mapValue", {}).get("fields", {})
