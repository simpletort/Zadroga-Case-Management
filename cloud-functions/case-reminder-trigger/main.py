"""
SimpleTort — Case Reminder Trigger Cloud Function

Firestore-triggered Cloud Function (Gen 2) that watches the ``cases``
collection for two events and calls the notification service accordingly:

Trigger 1 — Status → "Pending Client Info"
    Any service (intake-form-dispatcher, staff API, admin portal, etc.)
    that moves a case to "Pending Client Info" automatically schedules
    a 48-hour and a 7-day document reminder SMS via the notification service.

Trigger 2 — Status leaves "Pending Client Info" (documents received)
    When a case advances past "Pending Client Info" to any other status
    (e.g. "Active", "Screened"), both pending reminder tasks are cancelled
    so the client does not receive reminders after they have complied.

Trigger 3 — Missing documents field updated
    When ``missingDocuments`` is set to a non-empty list while the case is
    still in "Pending Client Info", reminders are re-scheduled so the updated
    document list is reflected in the next SMS.

Architecture
------------
This function is the **single, central trigger** for document reminders.
It does not care which service changed the case — it reacts to the Firestore
document state change itself.  This ensures:

* No service needs to know about the notification service directly.
* Reminders fire even from admin-console edits, bulk imports, or new services
  added in the future.
* Cancellation is guaranteed when documents are received regardless of the
  upload path (portal, email, paralegal manual update, etc.).

Firestore document path:  cases/{caseId}
Trigger type:             google.cloud.firestore.document.v1.updated

Environment variables
---------------------
    GCP_PROJECT_ID             — GCP project ID
    FIRESTORE_DATABASE_ID      — Firestore named database (default: simpletort-dev)
    NOTIFICATION_SERVICE_URL   — Base URL of the notification Cloud Run service
    APP_ENV                    — "production" | "development" (default: development)
"""

import json
import logging
import os
import sys
import urllib.request as _urllib_request
from datetime import datetime, timedelta, timezone

import functions_framework
from cloudevents.http import CloudEvent
from google.cloud import firestore
from google.events.cloud.firestore_v1.types import DocumentEventData

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
FIRESTORE_DB = os.environ.get("FIRESTORE_DATABASE_ID", "simpletort-dev")
NOTIFICATION_SERVICE_URL = os.environ.get("NOTIFICATION_SERVICE_URL", "")
APP_ENV = os.environ.get("APP_ENV", "development")

PENDING_CLIENT_INFO = "Pending Client Info"

# ── Firestore client (lazy singleton) ─────────────────────────────────────────

_db: firestore.Client | None = None


def _get_db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client(project=PROJECT_ID, database=FIRESTORE_DB)
    return _db


# ── OIDC token helper ──────────────────────────────────────────────────────────

def _get_oidc_token(audience: str) -> str:
    """
    Fetch an OIDC identity token from the GCP metadata server.
    Always attempted — works in Cloud Run regardless of APP_ENV.
    Returns empty string if metadata server is unreachable (local dev).
    """
    try:
        url = (
            "http://metadata.google.internal/computeMetadata/v1/instance/"
            f"service-accounts/default/identity?audience={audience}"
        )
        req = _urllib_request.Request(url, headers={"Metadata-Flavor": "Google"})
        with _urllib_request.urlopen(req, timeout=5) as resp:
            return resp.read().decode("utf-8")
    except Exception as exc:
        logger.warning("Could not get OIDC token (local dev?): %s", exc)
        return ""


# ── Notification service callers ───────────────────────────────────────────────

def _call_notification_service(method: str, path: str, body: dict | None = None) -> bool:
    """
    Make an authenticated HTTP call to the notification service.

    Parameters
    ----------
    method : "POST" | "DELETE"
    path   : e.g. "/internal/reminders/schedule"
    body   : JSON-serialisable dict (POST only)

    Returns True on success (2xx), False on any error.
    """
    if not NOTIFICATION_SERVICE_URL:
        logger.warning("NOTIFICATION_SERVICE_URL not configured — skipping call to %s", path)
        return False

    url = f"{NOTIFICATION_SERVICE_URL}{path}"
    try:
        token = _get_oidc_token(NOTIFICATION_SERVICE_URL)
        data = json.dumps(body).encode("utf-8") if body else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        req = _urllib_request.Request(url, data=data, headers=headers, method=method)
        with _urllib_request.urlopen(req, timeout=15) as resp:
            logger.info(
                "notification_service_call_ok method=%s path=%s status=%s",
                method, path, resp.status,
            )
            return True
    except Exception as exc:
        logger.error(
            "notification_service_call_failed method=%s path=%s error=%s",
            method, path, exc,
        )
        return False


def _schedule_reminders(case_id: str, case_data: dict) -> None:
    """
    Call POST /internal/reminders/schedule on the notification service.

    Pulls client name, phone, portalUrl, and missingDocuments directly from
    the Firestore case document so the reminder SMS always reflects the
    latest known state.
    """
    lead = case_data.get("leadData", {})
    first_name = lead.get("firstName", "")
    last_name = lead.get("lastName", "")
    client_name = f"{first_name} {last_name}".strip() or "Client"
    phone = lead.get("phone", "")

    if not phone:
        logger.warning("no phone on case %s — cannot schedule reminders", case_id)
        return

    portal_url = case_data.get(
        "portalAccessLink",
        f"https://portal.zadroga.com/c/{case_id}",
    )

    # Build missing-docs list from Firestore field (updated by paralegal)
    # or fall back to a generic message.
    raw_missing: list = case_data.get("missingDocuments", [])
    if raw_missing:
        missing_docs = "\n".join(f"• {doc}" for doc in raw_missing)
    else:
        missing_docs = (
            "• Required authorization forms\n"
            "• Supporting documentation for your Zadroga Act claim"
        )

    deadline = (datetime.now(tz=timezone.utc) + timedelta(hours=48)).strftime(
        "%B %-d, %Y at %I:%M %p UTC"
    )

    payload = {
        "caseId": case_id,
        "phone": phone,
        "clientName": client_name,
        "missingDocsList": missing_docs,
        "portalUrl": portal_url,
        "deadlineLabel": deadline,
        "requestId": case_id,
    }

    ok = _call_notification_service("POST", "/internal/reminders/schedule", payload)
    if ok:
        logger.info("reminders_scheduled case_id=%s", case_id)
    else:
        logger.error("reminders_schedule_failed case_id=%s", case_id)


def _cancel_reminders(case_id: str) -> None:
    """Call DELETE /internal/reminders/{case_id} on the notification service."""
    ok = _call_notification_service("DELETE", f"/internal/reminders/{case_id}")
    if ok:
        logger.info("reminders_cancelled case_id=%s", case_id)
    else:
        logger.error("reminders_cancel_failed case_id=%s", case_id)


# ── Change detection helpers ───────────────────────────────────────────────────

def _extract_field(doc_dict: dict, field: str):
    """
    Safely extract a field value from a Firestore document dict
    (supports both raw dict and proto-decoded dicts).
    """
    return doc_dict.get(field)


def _missing_docs_changed(old_data: dict, new_data: dict) -> bool:
    """Return True if missingDocuments field changed to a non-empty list."""
    old_docs = old_data.get("missingDocuments", [])
    new_docs = new_data.get("missingDocuments", [])
    return new_docs != old_docs and bool(new_docs)


# ── Cloud Function entrypoint ──────────────────────────────────────────────────

@functions_framework.cloud_event
def on_case_updated(cloud_event: CloudEvent) -> None:
    """
    Firestore trigger: fires on every update to cases/{caseId}.

    Decision table
    --------------
    Old status          New status              Action
    ──────────────────  ──────────────────────  ─────────────────────────────
    anything            Pending Client Info     Schedule 48hr + 7day reminders
    Pending Client Info anything else           Cancel pending reminders
    Pending Client Info Pending Client Info     Re-schedule if missingDocuments changed
    anything else       anything else           No-op
    """
    # Extract case ID from the resource path
    # Resource format: projects/{proj}/databases/{db}/documents/cases/{caseId}
    resource: str = cloud_event.get("subject") or cloud_event.get("source", "")
    case_id = resource.split("/")[-1] if resource else ""

    if not case_id:
        logger.warning("on_case_updated: could not determine case_id from event subject")
        return

    logger.info("on_case_updated case_id=%s", case_id)

    # Decode the protobuf event payload
    try:
        event_data = DocumentEventData()
        event_data._pb.MergeFromString(cloud_event.data)
        old_data = dict(event_data.old_value.fields) if event_data.old_value else {}
        new_data = dict(event_data.value.fields) if event_data.value else {}
    except Exception as exc:
        logger.error("on_case_updated: failed to decode event data error=%s", exc)
        return

    old_status = old_data.get("status", {})
    new_status = new_data.get("status", {})

    # Protobuf StringValue wraps the string — unwrap if needed
    if hasattr(old_status, "string_value"):
        old_status = old_status.string_value
    if hasattr(new_status, "string_value"):
        new_status = new_status.string_value

    logger.info(
        "case_status_change case_id=%s old=%s new=%s",
        case_id, old_status, new_status,
    )

    # ── Fetch full case document for template variables ────────────────────
    # The event payload contains proto-encoded field values which are complex
    # to decode for nested objects (leadData, etc.).  A direct Firestore read
    # is simpler and guarantees we get the latest state.
    db = _get_db()
    case_snap = db.collection("cases").document(case_id).get()
    if not case_snap.exists:
        logger.warning("on_case_updated: case %s not found in Firestore", case_id)
        return
    case_data = case_snap.to_dict()

    # ── Decision table ─────────────────────────────────────────────────────

    if new_status == PENDING_CLIENT_INFO and old_status != PENDING_CLIENT_INFO:
        # Case just entered "Pending Client Info" from any previous state
        logger.info("trigger: status → Pending Client Info — scheduling reminders")
        _schedule_reminders(case_id, case_data)

    elif old_status == PENDING_CLIENT_INFO and new_status != PENDING_CLIENT_INFO:
        # Case left "Pending Client Info" — documents received or case advanced
        logger.info(
            "trigger: status Pending Client Info → %s — cancelling reminders", new_status
        )
        _cancel_reminders(case_id)

    elif new_status == PENDING_CLIENT_INFO and _missing_docs_changed(old_data, new_data):
        # Status unchanged but missingDocuments updated — re-schedule so the
        # updated list appears in the next reminder SMS.
        logger.info("trigger: missingDocuments updated — re-scheduling reminders")
        _cancel_reminders(case_id)
        _schedule_reminders(case_id, case_data)

    else:
        logger.info(
            "no_reminder_action_needed case_id=%s old=%s new=%s",
            case_id, old_status, new_status,
        )
