"""
functions/followup_monitor/main.py — Cloud Function 2nd Gen
Triggered hourly by Cloud Scheduler via HTTP.

Monitors new leads for portal engagement. If a lead:
  1. Has status "New Lead"
  2. Was created >= 48 hours ago
  3. Has NOT logged into the portal (portalLoginAt is null)
  4. Does NOT already have a followup task (followupTaskCreated == false)

→ Creates a follow-up task in Firestore assigned to the responsible paralegal.
→ Marks the case followupTaskCreated=true to prevent duplicate tasks.

No duplicate tasks are created for the same case (idempotent).

Schedule: every hour via Cloud Scheduler
  Target: https://<region>-<project>.cloudfunctions.net/followup-monitor
  Method: POST
  Body: {}
  Auth: OIDC service account
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import functions_framework
from flask import Request
from google.cloud import firestore


GCP_PROJECT = os.environ["GCP_PROJECT_ID"]
CASES_COLLECTION = os.environ.get("FIRESTORE_CASES_COLLECTION", "cases")
FOLLOWUP_DELAY_HOURS = int(os.environ.get("FOLLOWUP_DELAY_HOURS", "48"))
DEFAULT_ASSIGNEE = os.environ.get("DEFAULT_ASSIGNEE_EMAIL", "paralegal@zadlegal.com")

db = firestore.Client(project=GCP_PROJECT)


@functions_framework.http
def followup_monitor(request: Request):
    """
    Hourly monitor: scans for leads that need follow-up tasks created.
    Returns JSON summary of tasks created.
    """
    print(f"Follow-up monitor started at {datetime.utcnow().isoformat()}")

    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=FOLLOWUP_DELAY_HOURS)

    # Query: New Lead cases older than cutoff, no followup task yet
    query = (
        db.collection(CASES_COLLECTION)
        .where("status", "==", "New Lead")
        .where("followupTaskCreated", "==", False)
        .where("createdAt", "<=", cutoff_time)
        .limit(100)  # Process in batches of 100
    )

    docs = list(query.stream())
    print(f"Found {len(docs)} leads needing follow-up")

    created_tasks = []
    skipped = []
    errors = []

    for doc in docs:
        case_data = doc.to_dict()
        case_id = case_data.get("caseId", doc.id)

        # Skip if portal login has occurred
        if case_data.get("portalLoginAt"):
            skipped.append(case_id)
            continue

        try:
            task_id = _create_followup_task(case_id, case_data)
            created_tasks.append({"caseId": case_id, "taskId": task_id})
            print(f"Created follow-up task {task_id} for case {case_id}")
        except Exception as exc:
            print(f"ERROR creating follow-up task for {case_id}: {exc}")
            errors.append({"caseId": case_id, "error": str(exc)})

    summary = {
        "timestamp": datetime.utcnow().isoformat(),
        "processed": len(docs),
        "tasksCreated": len(created_tasks),
        "skipped": len(skipped),
        "errors": len(errors),
        "tasks": created_tasks,
    }
    print(f"Follow-up monitor complete: {json.dumps(summary)}")
    return (json.dumps(summary), 200, {"Content-Type": "application/json"})


def _create_followup_task(case_id: str, case_data: dict) -> str:
    """
    Create a follow-up task in Firestore and mark case as task-created.
    Returns the task ID.
    """
    # Determine assignee: use case.assignedTo or fall back to default paralegal pool
    assigned_to = case_data.get("assignedTo") or DEFAULT_ASSIGNEE

    # Create task document
    task_ref = db.collection("tasks").document()
    task_ref.set({
        "taskId": task_ref.id,
        "type": "FOLLOWUP_LEAD",
        "priority": "high",
        "caseId": case_id,
        "assignedTo": assigned_to,
        "clientName": f"{case_data.get('firstName', '')} {case_data.get('lastName', '')}".strip(),
        "clientEmail": case_data.get("email", ""),
        "clientPhone": case_data.get("phone", ""),
        "marketingSource": case_data.get("marketingSource", ""),
        "caseCreatedAt": case_data.get("createdAt"),
        "status": "pending",
        "suggestedActions": [
            "Call client to confirm receipt of welcome email",
            "Resend portal login link if client has not logged in",
            "Confirm VCF interest and exposure dates",
            "Verify WTC Health Program enrollment status",
            "Schedule intake appointment if qualified",
        ],
        "createdAt": firestore.SERVER_TIMESTAMP,
        "dueAt": firestore.SERVER_TIMESTAMP,
    })

    # Mark case as having follow-up task (prevents duplicates)
    db.collection(CASES_COLLECTION).document(case_id).update({
        "followupTaskCreated": True,
        "followupTaskId": task_ref.id,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })

    return task_ref.id
