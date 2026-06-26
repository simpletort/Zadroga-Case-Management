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

# Fallback used when firmSettings/case_statuses is absent or Firestore is unreachable
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
    Load closed/terminal case statuses from firmSettings/case_statuses.closedStatuses[].
    Cached for the lifetime of the function instance (cold-start load).

    Falls back to DEFAULT_SKIP_STATUSES when the document is absent or Firestore
    is unreachable so deadline recalculation is always correctly gated.
    """
    global _closed_statuses_cache
    if _closed_statuses_cache is not None:
        return _closed_statuses_cache
    try:
        db = _get_db()
        doc = db.collection("firmSettings").document("case_statuses").get()
        if doc.exists:
            all_statuses = (doc.to_dict() or {}).get("statuses", [])
            closed = [s["value"] for s in all_statuses if s.get("category") in ("closed", "terminal")]
            if closed:
                _closed_statuses_cache = frozenset(closed)
                return _closed_statuses_cache
    except Exception as exc:
        logger.warning(
            "Failed to load firmSettings/case_statuses.closedStatuses: %s; using defaults", exc
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


# ── Plain-dict base-date extractor (Firestore SDK returns plain Python dicts) ──

def _extract_base_date(case_data: dict, rule_type: str) -> date | None:
    """
    Extract the base date for the configured rule type from a plain Firestore
    document dict (as returned by DocumentSnapshot.to_dict()).

    Rule → field mapping:
      cert_date_offset      → medicalInfo.certificationDate  (ISO date string)
      injury_date_offset    → medicalInfo.injuryDate         (ISO date string)
      statute_of_limitations → createdAt                     (datetime or ISO string)

    Returns None when the field is absent, the rule_type is unknown, or the
    value cannot be parsed as a date.
    """
    try:
        if rule_type == "cert_date_offset":
            raw = (case_data.get("medicalInfo") or {}).get("certificationDate", "")
        elif rule_type == "injury_date_offset":
            raw = (case_data.get("medicalInfo") or {}).get("injuryDate", "")
        elif rule_type == "statute_of_limitations":
            created = case_data.get("createdAt")
            if created is None:
                return None
            # Firestore returns datetime objects for timestamp fields
            if isinstance(created, (datetime, date)):
                return created.date() if isinstance(created, datetime) else created
            raw = str(created)
        else:
            logger.warning("Unknown deadlineRuleType '%s' in _extract_base_date", rule_type)
            return None

        if not raw:
            return None
        return date.fromisoformat(str(raw)[:10])

    except (ValueError, TypeError) as exc:
        logger.warning(
            "Invalid base date for rule '%s': %s — %s", rule_type, raw, exc
        )
        return None


# ── Main entry point ───────────────────────────────────────────────────────────

@functions_framework.cloud_event
def calculate_filing_deadline(event: CloudEvent) -> None:
    """
    Triggered by Firestore document write on cases/{caseId}.

    The CloudEvent subject attribute reliably contains the document path
    (e.g. "documents/cases/ZAD-2026-01-7078") regardless of whether the
    event payload is JSON or protobuf.  We use that to look up the case
    directly from Firestore — avoiding all protobuf deserialization entirely.

    Idempotency: if the calculated deadline equals the value already stored
    in enrollment.filingDeadline we skip the write, which prevents an
    infinite trigger loop (our own writes would otherwise re-fire the event).
    """
    # ── Extract case ID from CloudEvent subject ───────────────────────────
    subject: str = event.get("subject") or ""
    # subject format: "documents/cases/{caseId}"
    case_id = subject.rsplit("/", 1)[-1] if "/" in subject else ""
    if not case_id:
        logger.info("Cannot determine caseId from subject='%s'; skipping", subject)
        return

    logger.info("calculate_filing_deadline triggered caseId=%s", case_id)

    # ── Read case document directly from Firestore ────────────────────────
    db       = _get_db()
    case_ref = db.collection("cases").document(case_id)
    snap     = case_ref.get()
    if not snap.exists:
        logger.info("Case document not found caseId=%s (delete event?); skipping", case_id)
        return
    case_data: dict = snap.to_dict() or {}

    # ── Skip closed/terminal cases ────────────────────────────────────────
    case_status = case_data.get("status", "")
    if case_status in _get_closed_statuses():
        logger.info("Skipping closed/final case caseId=%s status=%s", case_id, case_status)
        return

    # ── Calculate deadline using configured strategy ───────────────────────
    firm_config    = _get_firm_config()
    rule_type_used = firm_config.get("deadlineRuleType", "cert_date_offset")

    base_date = _extract_base_date(case_data, rule_type_used)
    if base_date is None:
        logger.info(
            "Base date unavailable for caseId=%s (rule=%s); skipping",
            case_id, rule_type_used,
        )
        return

    rule_fn  = DEADLINE_RULES.get(rule_type_used) or DEADLINE_RULES["cert_date_offset"]
    deadline = rule_fn(base_date, firm_config)

    # ── Idempotency check — prevents infinite write-back loop ─────────────
    existing_deadline = (case_data.get("enrollment") or {}).get("filingDeadline")
    if existing_deadline == deadline.isoformat():
        logger.info(
            "Deadline unchanged for caseId=%s (%s); skipping write",
            case_id, deadline.isoformat(),
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
                "trigger": "firestore_write",
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
