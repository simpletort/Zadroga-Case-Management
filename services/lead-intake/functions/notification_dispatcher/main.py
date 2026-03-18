"""
functions/notification_dispatcher/main.py — Cloud Function 2nd Gen
Triggered by Pub/Sub 'lead-screened' topic.

Dispatches notifications based on VCF screening result:
  - ELIGIBLE → Notify assigned paralegal: "Case ready for conversion"
  - INELIGIBLE → Notify lead: "Does not meet VCF criteria at this time"
  - NEEDS_REVIEW → Create internal review task, notify paralegal
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime

import functions_framework
from google.cloud import firestore
from cloudevents.http import CloudEvent


GCP_PROJECT = os.environ["GCP_PROJECT_ID"]
CASES_COLLECTION = os.environ.get("FIRESTORE_CASES_COLLECTION", "cases")

db = firestore.Client(project=GCP_PROJECT)


@functions_framework.cloud_event
def notification_dispatcher(cloud_event: CloudEvent) -> None:
    """
    Triggered by 'lead-screened' Pub/Sub event.
    Creates Firestore notification documents for the Admin UI and assigned staff.
    """
    raw = base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
    message = json.loads(raw)

    case_id = message.get("caseId")
    eligibility = message.get("eligibility")
    score = message.get("score", 0)
    flags = message.get("flags", [])

    if not case_id:
        print(f"ERROR: No caseId in message: {message}")
        return

    print(f"Notification dispatch started: {case_id}, eligibility={eligibility}")

    # Fetch case for contact info
    case_ref = db.collection(CASES_COLLECTION).document(case_id)
    case_doc = case_ref.get()

    if not case_doc.exists:
        print(f"ERROR: Case not found: {case_id}")
        return

    case_data = case_doc.to_dict()
    assigned_to = case_data.get("assignedTo", "unassigned")

    now = datetime.utcnow().isoformat()

    if eligibility == "eligible":
        _create_notification(
            notification_type="CASE_QUALIFIED",
            title=f"Case {case_id} qualified for VCF",
            body=f"{case_data.get('firstName')} {case_data.get('lastName')} has passed VCF screening (score: {score}). Ready to convert to active case.",
            assigned_to=assigned_to,
            case_id=case_id,
            priority="high",
        )
    elif eligibility == "ineligible":
        _create_notification(
            notification_type="CASE_DISQUALIFIED",
            title=f"Case {case_id} did not qualify",
            body=f"{case_data.get('firstName')} {case_data.get('lastName')} did not meet VCF eligibility criteria.",
            assigned_to=assigned_to,
            case_id=case_id,
            priority="normal",
        )
    elif eligibility == "needs_review":
        flag_summary = "; ".join(flags[:3]) if flags else "See screening details"
        _create_notification(
            notification_type="CASE_NEEDS_REVIEW",
            title=f"Case {case_id} requires manual review",
            body=f"Flags: {flag_summary}",
            assigned_to=assigned_to,
            case_id=case_id,
            priority="high",
        )

    print(f"Notification dispatched for {case_id}: {eligibility}")


def _create_notification(
    notification_type: str,
    title: str,
    body: str,
    assigned_to: str,
    case_id: str,
    priority: str = "normal",
) -> None:
    """Write a notification document to /notifications/{id}."""
    notif_ref = db.collection("notifications").document()
    notif_ref.set({
        "notificationId": notif_ref.id,
        "type": notification_type,
        "title": title,
        "body": body,
        "caseId": case_id,
        "assignedTo": assigned_to,
        "priority": priority,
        "read": False,
        "createdAt": firestore.SERVER_TIMESTAMP,
    })
    print(f"Notification created: {notification_type} for case {case_id}, assigned={assigned_to}")
