"""
Enrollment Workflow — Filing Deadline Alerter Cloud Function (Gen 2)

Trigger: Cloud Scheduler HTTP (runs daily at 8:00 AM ET = 13:00 UTC)
         POST https://{region}-{project}.cloudfunctions.net/deadline-alerter

Flow:
  1. Scan all active cases with enrollment.filingDeadline set
  2. For each case, check if it falls within a 90/60/30-day alert window
  3. Skip cases where this milestone alert was already sent (lastAlertMilestone)
  4. For newly-triggered alerts:
     a. Create paralegal task with urgency
     b. Publish Pub/Sub notification request (email to paralegal + attorney)
     c. Update case.enrollment.lastAlertMilestone
     d. Write timeline event
  5. Return summary JSON

No duplicate alerts: once a milestone is recorded, it is not re-fired.
Alert progression: 90 → 60 → 30 (each fires exactly once).

Generic field name used: enrollment.filingDeadline (replaces enrollment.vcfFilingDeadline)

Environment variables:
  GCP_PROJECT_ID              — GCP project
  FIRESTORE_DATABASE_ID       — default: (default)
  PUBSUB_TOPIC_NOTIFICATIONS  — default: notification-requests
  PUBSUB_TOPIC_ENROLLMENT     — default: enrollment-status-changes
  ALERT_DAYS                  — comma-separated thresholds, default: 90,60,30
"""

import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone

import functions_framework
from google.cloud import firestore, pubsub_v1

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ["GCP_PROJECT_ID"]
FIRESTORE_DB = os.environ.get("FIRESTORE_DATABASE_ID", "simpletort-dev")
PUBSUB_TOPIC_NOTIF = os.environ.get("PUBSUB_TOPIC_NOTIFICATIONS", "notification-requested")
PUBSUB_TOPIC_ENROLL = os.environ.get("PUBSUB_TOPIC_ENROLLMENT", "enrollment-status-changes")
ALERT_DAYS = [
    int(x) for x in os.environ.get("ALERT_DAYS", "90,60,30").split(",")
]

SKIP_STATUSES = {"Closed", "Settled", "Does Not Qualify", "Rejected"}

_db: firestore.Client | None = None
_publisher: pubsub_v1.PublisherClient | None = None


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


@functions_framework.http
def deadline_alerter(request):
    """
    HTTP Cloud Function triggered daily by Cloud Scheduler.
    Scans all cases with approaching filing deadlines and fires alerts.
    """
    today = date.today()
    logger.info("deadline_alerter_started date=%s thresholds=%s", today.isoformat(), ALERT_DAYS)

    db = _get_db()
    stats = {
        "scanned": 0,
        "alerts_fired": 0,
        "skipped_duplicate": 0,
        "skipped_final_status": 0,
        "errors": 0,
        "by_threshold": {str(d): 0 for d in ALERT_DAYS},
    }

    try:
        # Query on generic field name: enrollment.filingDeadline
        cases = (
            db.collection("cases")
            .where("enrollment.filingDeadline", "!=", None)
            .stream()
        )

        for case_doc in cases:
            stats["scanned"] += 1
            try:
                _process_case(db, case_doc, today, stats)
            except Exception as exc:
                stats["errors"] += 1
                logger.error("Error processing caseId=%s: %s", case_doc.id, exc)

    except Exception as exc:
        logger.error("deadline_alerter_scan_failed: %s", exc)
        return {"status": "error", "message": str(exc)}, 500

    logger.info(
        "deadline_alerter_complete date=%s stats=%s",
        today.isoformat(), json.dumps(stats),
    )
    return {"status": "ok", "date": today.isoformat(), "stats": stats}, 200


def _process_case(
    db: firestore.Client,
    case_doc,
    today: date,
    stats: dict,
) -> None:
    """Process a single case for deadline alerts."""
    data = case_doc.to_dict() or {}
    case_id = case_doc.id
    enrollment = data.get("enrollment", {})
    case_status = data.get("status", "")

    # Skip final-state cases
    if case_status in SKIP_STATUSES:
        stats["skipped_final_status"] += 1
        return

    # Read from generic field name
    deadline_str = enrollment.get("filingDeadline")
    if not deadline_str:
        return

    try:
        deadline = date.fromisoformat(deadline_str[:10])
    except (ValueError, TypeError):
        logger.warning("Invalid deadline format caseId=%s value=%s", case_id, deadline_str)
        return

    days_remaining = (deadline - today).days
    last_alert = enrollment.get("lastAlertMilestone")

    # Find the highest applicable alert threshold for this case
    applicable_threshold = None
    for threshold in sorted(ALERT_DAYS, reverse=True):
        if days_remaining <= threshold:
            # Only alert if we haven't already sent this milestone
            if last_alert is None or last_alert > threshold:
                applicable_threshold = threshold
            else:
                stats["skipped_duplicate"] += 1
            break

    if applicable_threshold is None:
        return

    # ── Fire alert ──────────────────────────────────────────────────────
    assigned_paralegal = data.get("assignment", {}).get("assignedParalegal")
    supervising_attorney = data.get("assignment", {}).get("assignedAttorney")

    logger.info(
        "firing_deadline_alert caseId=%s threshold=%d daysRemaining=%d",
        case_id, applicable_threshold, days_remaining,
    )

    # 1. Create paralegal task
    _create_alert_task(
        db, case_id, applicable_threshold, days_remaining, deadline_str, assigned_paralegal
    )

    # 2. Publish notification request (email to assigned staff)
    _publish_notification(
        case_id, applicable_threshold, days_remaining, deadline_str,
        assigned_paralegal, supervising_attorney,
    )

    # 3. Write timeline event
    _write_alert_timeline(db, case_id, applicable_threshold, days_remaining, deadline_str)

    # 4. Update lastAlertMilestone (prevent duplicate alerts for this milestone)
    try:
        db.collection("cases").document(case_id).update({
            "enrollment.lastAlertMilestone": applicable_threshold,
            "enrollment.lastAlertSentAt": firestore.SERVER_TIMESTAMP,
            "enrollment.deadlineStatus": _compute_status(days_remaining),
            "enrollment.daysUntilDeadline": days_remaining,
        })
    except Exception as exc:
        logger.warning("Failed to update lastAlertMilestone caseId=%s: %s", case_id, exc)

    # 5. Publish enrollment event for downstream services
    _publish_enrollment_event(case_id, applicable_threshold, days_remaining, deadline_str)

    stats["alerts_fired"] += 1
    stats["by_threshold"][str(applicable_threshold)] += 1


def _create_alert_task(
    db: firestore.Client,
    case_id: str,
    threshold: int,
    days_remaining: int,
    deadline_str: str,
    assigned_to: str | None,
) -> str:
    """Create an urgent paralegal task for the deadline alert."""
    if days_remaining <= 30:
        priority = "urgent"
        due_days = min(days_remaining - 3, 5)
    elif days_remaining <= 60:
        priority = "high"
        due_days = 10
    else:
        priority = "high"
        due_days = 14

    due_date = datetime.now(tz=timezone.utc) + timedelta(days=max(due_days, 1))

    task_ref = (
        db.collection("cases")
        .document(case_id)
        .collection("tasks")
        .document()
    )
    task_id = task_ref.id

    task_ref.set({
        "taskId": task_id,
        "caseId": case_id,
        "title": f"DEADLINE ALERT: Filing Due in {days_remaining} Days ({deadline_str})",
        "instructions": (
            f"Program registration filing deadline is {deadline_str} — "
            f"{days_remaining} days remaining.\n\n"
            f"This is a {threshold}-day advance warning.\n\n"
            "IMMEDIATE ACTION REQUIRED:\n"
            "1. Review current claim filing status in the program portal.\n"
            "2. Contact client to confirm all documents are ready for filing.\n"
            "3. Verify medical records, exposure proof, and certification are complete.\n"
            "4. Notify supervising attorney of pending deadline.\n"
            "5. Schedule filing meeting if not already scheduled.\n\n"
            "CRITICAL: Missing the filing deadline may be FATAL to the claim."
        ),
        "category": "Deadline Alert",
        "workflowType": "enrollment",
        "workflowStep": "deadline_alert",
        "status": "pending",
        "priority": priority,
        "assignedTo": assigned_to,
        "dueDate": due_date,
        "createdAt": firestore.SERVER_TIMESTAMP,
        "completedAt": None,
        "metadata": {
            "alertThreshold": threshold,
            "daysRemaining": days_remaining,
            "filingDeadline": deadline_str,
            "alertType": f"deadline_{threshold}d",
        },
    })

    logger.info(
        "alert_task_created caseId=%s taskId=%s threshold=%d",
        case_id, task_id, threshold,
    )
    return task_id


def _write_alert_timeline(
    db: firestore.Client,
    case_id: str,
    threshold: int,
    days_remaining: int,
    deadline_str: str,
) -> None:
    """Write timeline event for deadline alert."""
    try:
        timeline_ref = (
            db.collection("cases").document(case_id).collection("timeline").document()
        )
        timeline_ref.set({
            "eventId": timeline_ref.id,
            "caseId": case_id,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "eventType": "DeadlineAlert",
            "description": (
                f"Filing deadline alert ({threshold} days): "
                f"deadline is {deadline_str} ({days_remaining} days remaining)"
            ),
            "performedBy": "system",
            "metadata": {
                "alertThreshold": threshold,
                "daysRemaining": days_remaining,
                "filingDeadline": deadline_str,
            },
        })
    except Exception as exc:
        logger.warning(
            "Failed to write alert timeline for caseId=%s threshold=%d: %s",
            case_id, threshold, exc,
        )


def _publish_notification(
    case_id: str,
    threshold: int,
    days_remaining: int,
    deadline_str: str,
    paralegal_id: str | None,
    attorney_id: str | None,
) -> None:
    """Publish notification request to alert paralegal and attorney by email."""
    recipients = [r for r in [paralegal_id, attorney_id] if r]
    if not recipients:
        logger.warning("No recipients for alert caseId=%s threshold=%d", case_id, threshold)
        return

    try:
        publisher = _get_publisher()
        topic_path = publisher.topic_path(PROJECT_ID, PUBSUB_TOPIC_NOTIF)
        payload = json.dumps({
            "caseId": case_id,
            "notificationType": "filing_deadline_alert",
            "templateId": f"filing_deadline_{threshold}d",
            "recipientIds": recipients,
            "variables": {
                "daysRemaining": days_remaining,
                "filingDeadline": deadline_str,
                "alertThreshold": threshold,
            },
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }).encode("utf-8")
        publisher.publish(topic_path, data=payload, notification_type="filing_deadline_alert")
        logger.info(
            "notification_published caseId=%s threshold=%d recipients=%d",
            case_id, threshold, len(recipients),
        )
    except Exception as exc:
        logger.warning(
            "notification_publish_failed caseId=%s threshold=%d: %s",
            case_id, threshold, exc,
        )


def _publish_enrollment_event(
    case_id: str,
    threshold: int,
    days_remaining: int,
    deadline_str: str,
) -> None:
    """Publish enrollment event for downstream services."""
    try:
        publisher = _get_publisher()
        topic_path = publisher.topic_path(PROJECT_ID, PUBSUB_TOPIC_ENROLL)
        payload = json.dumps({
            "caseId": case_id,
            "eventType": "FilingDeadlineAlert",
            "workflowType": "enrollment",
            "alertThreshold": threshold,
            "daysRemaining": days_remaining,
            "filingDeadline": deadline_str,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }).encode("utf-8")
        publisher.publish(topic_path, data=payload)
    except Exception as exc:
        logger.warning(
            "enrollment_event_publish_failed caseId=%s: %s", case_id, exc
        )


def _compute_status(days_remaining: int) -> str:
    if days_remaining < 0:
        return "expired"
    elif days_remaining <= 30:
        return "warning_30"
    elif days_remaining <= 60:
        return "warning_60"
    elif days_remaining <= 90:
        return "warning_90"
    return "active"
