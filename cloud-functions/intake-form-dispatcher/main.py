"""
SimpleTort — Intake Form Dispatcher Cloud Function

HTTP trigger. Called by the staff UI (or admin endpoint) when a paralegal
clicks "Send Intake Form" on a case.

Endpoint: POST /send
Body:     { "caseId": "ZAD-2026-03-0001" }
Response: { "tokenId": "...", "previewUrl": "...", "emailSent": true }

Flow:
  1. Validate request body — caseId present and safe to use as a Firestore
     document ID (no format requirement beyond that — see _case_id_is_safe)
  2. Fetch case document from Firestore — confirm it exists and is in a
     status that allows intake dispatch ("New Lead" or "Pending Client Info")
  3. Load form field mapping from Firestore config/intake_form (cached per instance)
  4. Generate UUID v4 token; write intake_tokens/{tokenId}
  5. Build Google Forms pre-fill URL from the Firestore field mapping
  6. Send email via SendGrid with the pre-fill link
  7. Update token with emailSent outcome
  8. Advance case status "New Lead" → "Pending Client Info" if applicable
  9. Return { tokenId, previewUrl, emailSent }

Form field mapping (JotForm-style — configurable without redeploy):
  Stored in Firestore at config/intake_form:
    {
      "formBaseUrl":    "https://docs.google.com/forms/d/<FORM_ID>/viewform",
      "fieldMappings": {
        "firstName":   "entry.1111111111",
        "lastName":    "entry.2222222222",
        "email":       "entry.3333333333",
        "phone":       "entry.4444444444",
        "intakeToken": "entry.5555555555"
      }
    }
  To update form entry IDs: edit the Firestore document in Firebase Console.
  The change takes effect on the next Cloud Run instance cold start — no redeploy.

Environment variables (set via Cloud Run --set-env-vars / Secret Manager):
  GCP_PROJECT_ID         — GCP project ID
  FIRESTORE_DATABASE_ID  — default: (default)
  SENDGRID_API_KEY       — injected from Secret Manager
  FROM_EMAIL             — sender address, e.g. noreply@simpletort.com
  ADMIN_EMAIL            — alert recipient, e.g. admin@simpletort.com
  TOKEN_EXPIRY_DAYS      — default: 30
"""

import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, quote

import flask
import functions_framework
from google.cloud import firestore

try:
    import sendgrid
    from sendgrid.helpers.mail import Mail

    _SENDGRID_AVAILABLE = True
except ImportError:
    _SENDGRID_AVAILABLE = False

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
PROJECT_ID = os.environ["GCP_PROJECT_ID"]
FIRESTORE_DB = os.environ.get("FIRESTORE_DATABASE_ID", "(default)")
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "noreply@simpletort.com")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@simpletort.com")
TOKEN_EXPIRY_DAYS = int(os.environ.get("TOKEN_EXPIRY_DAYS", "30"))

ALLOWED_STATUSES = {"New Lead", "Pending Client Information"}
RESEND_STATUSES = {"Pending Client Information"}

# Module-level singletons (reused across warm invocations)
_db: firestore.Client | None = None
_form_config: dict | None = None   # cached after first Firestore read


def _get_db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client(project=PROJECT_ID, database=FIRESTORE_DB)
    return _db


def _case_id_is_safe(case_id: str) -> bool:
    """
    Minimal Firestore document-ID safety check — deliberately NOT a case-ID
    format check (no ZAD-YYYY-MM-XXXX requirement).

    case_id is passed straight into db.collection("cases").document(case_id)
    below. Firestore's .document() splits its argument on "/", so an embedded
    slash would silently target a different document path instead of cleanly
    404ing. Also rejects the couple of literal values Firestore itself
    disallows as a document ID.
    """
    if not case_id:
        return False
    if "/" in case_id:
        return False
    if case_id in (".", ".."):
        return False
    if case_id.startswith("__") and case_id.endswith("__"):
        return False
    if len(case_id.encode("utf-8")) > 1500:
        return False
    return True


def _get_form_config() -> dict:
    """
    Load form field mapping from Firestore config/intake_form.

    Cached per Cloud Run instance — editing the Firestore document takes effect
    on the next cold start without requiring a redeploy. This mirrors JotForm's
    field-mapping configuration: the mapping of case data fields to Google Form
    entry IDs is stored centrally and is editable at runtime via Firebase Console.

    Expected document shape:
      {
        "formBaseUrl":    "https://docs.google.com/forms/d/<FORM_ID>/viewform",
        "fieldMappings": {
          "firstName":   "entry.1111111111",
          "lastName":    "entry.2222222222",
          "email":       "entry.3333333333",
          "phone":       "entry.4444444444",
          "intakeToken": "entry.5555555555"
        }
      }
    """
    global _form_config
    if _form_config is None:
        snap = _get_db().collection("config").document("intake_form").get()
        if not snap.exists:
            raise RuntimeError(
                "Firestore document 'config/intake_form' not found. "
                "Create it with 'formBaseUrl' and 'fieldMappings' before using this function."
            )
        data = snap.to_dict()
        if not data.get("formBaseUrl") or not data.get("fieldMappings"):
            raise RuntimeError(
                "config/intake_form is missing 'formBaseUrl' or 'fieldMappings'."
            )
        _form_config = data
        logger.info("Form config loaded: formBaseUrl=%s", _form_config["formBaseUrl"])
    return _form_config


def _build_prefill_url(
    *,
    form_config: dict,
    first_name: str,
    last_name: str,
    email: str,
    phone: str,
    token_id: str,
) -> str:
    """
    Construct a Google Forms pre-fill URL using the field mapping stored in
    Firestore (config/intake_form.fieldMappings). Only maps fields that have
    a corresponding entry ID configured — missing mappings are skipped silently.
    """
    mappings: dict = form_config["fieldMappings"]
    params: dict[str, str] = {}

    field_values = {
        "firstName":   first_name,
        "lastName":    last_name,
        "email":       email,
        "phone":       phone,
        "intakeToken": token_id,
    }
    for field_key, value in field_values.items():
        entry_id = mappings.get(field_key, "")
        if entry_id and value:
            params[entry_id] = value

    return "{}?{}".format(form_config["formBaseUrl"], urlencode(params, quote_via=quote))


def _send_intake_email(to_email: str, client_name: str, prefill_url: str) -> bool:
    """Send the intake form link via SendGrid. Returns True on success."""
    if not _SENDGRID_AVAILABLE or not SENDGRID_API_KEY:
        logger.error("SendGrid unavailable or not configured — intake email not sent")
        return False

    html_body = """
    <p>Dear {name},</p>

    <p>Thank you for contacting SimpleTort regarding your Zadroga Act / 9/11 VCF claim.
    To move forward we need a few more details from you.</p>

    <p>Please complete your client intake form by clicking the button below.
    Your information has been pre-filled where possible.</p>

    <p style="margin: 24px 0;">
      <a href="{url}"
         style="background:#1A3C6B;color:#fff;padding:12px 24px;
                text-decoration:none;border-radius:4px;font-weight:bold;">
        Complete Your Intake Form
      </a>
    </p>

    <p>Or copy this link into your browser:<br>
    <small>{url}</small></p>

    <p>This link will expire in {days} days. If you have any questions,
    please contact our office and reference the link in your email.</p>

    <p>SimpleTort Legal Services</p>
    """.format(
        name=client_name or "Client",
        url=prefill_url,
        days=TOKEN_EXPIRY_DAYS,
    )

    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=to_email,
        subject="Action Required: Complete Your Client Intake Form",
        html_content=html_body,
    )

    try:
        sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
        response = sg.send(message)
        if response.status_code in (200, 202):
            logger.info(
                "Intake email sent: to=%s status=%d", to_email, response.status_code
            )
            return True
        logger.error(
            "SendGrid returned unexpected status %d for %s",
            response.status_code,
            to_email,
        )
        return False
    except Exception as exc:
        logger.error("SendGrid exception for %s: %s", to_email, exc)
        return False


# ── HTTP Cloud Function entry point ───────────────────────────────────────────

@functions_framework.http
def send_intake_form(request: flask.Request) -> flask.Response:
    """
    POST /send
    Body: { "caseId": "ZAD-2026-03-0001" }
    """

    # CORS preflight
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Staff-UID",
        "Access-Control-Max-Age": "3600",
    }
    if request.method == "OPTIONS":
        return flask.Response(status=204, headers=cors_headers)

    if request.method != "POST":
        return flask.make_response(
            flask.jsonify({"error": "Method not allowed"}), 405, cors_headers
        )

    # Parse body
    try:
        body = request.get_json(force=True) or {}
    except Exception:
        return flask.make_response(
            flask.jsonify({"error": "Invalid JSON body"}), 400, cors_headers
        )

    case_id: str = body.get("caseId", "").strip()
    if not _case_id_is_safe(case_id):
        return flask.make_response(
            flask.jsonify({"error": "caseId is required and must not contain '/'."}),
            400,
            cors_headers,
        )

    # Staff UID passed by internal caller (staff API sets this header)
    triggered_by: str = request.headers.get("X-Staff-UID", "system")

    db = _get_db()

    # Fetch case
    case_ref = db.collection("cases").document(case_id)
    case_snap = case_ref.get()

    if not case_snap.exists:
        logger.warning("send_intake_form: case not found case_id=%s", case_id)
        return flask.make_response(
            flask.jsonify({"error": "Case not found"}), 404, cors_headers
        )

    case_data = case_snap.to_dict()
    current_status: str = case_data.get("status", "")

    if current_status not in ALLOWED_STATUSES:
        logger.warning(
            "send_intake_form: case %s status=%s — intake not allowed",
            case_id,
            current_status,
        )
        return flask.make_response(
            flask.jsonify(
                {
                    "error": "Intake form can only be sent for cases in status: {}".format(
                        ", ".join(sorted(ALLOWED_STATUSES))
                    )
                }
            ),
            409,
            cors_headers,
        )

    lead_data: dict = case_data.get("leadData") or {}
    first_name: str = lead_data.get("firstName") or case_data.get("firstName", "")
    last_name: str = lead_data.get("lastName") or case_data.get("lastName", "")
    email: str = lead_data.get("email") or case_data.get("email", "")
    phone: str = lead_data.get("phone") or case_data.get("phone", "")

    if not email:
        return flask.make_response(
            flask.jsonify({"error": "Case has no email address — cannot send intake form"}),
            422,
            cors_headers,
        )

    # Load form field mapping from Firestore config/intake_form
    try:
        form_config = _get_form_config()
    except RuntimeError as exc:
        logger.error("Form config error: %s", exc)
        return flask.make_response(
            flask.jsonify({"error": "Form configuration error", "detail": str(exc)}),
            500,
            cors_headers,
        )

    is_resend = current_status in RESEND_STATUSES

    # For resend, reuse existing token if one exists and is unused; otherwise create new one
    now = datetime.now(tz=timezone.utc)
    client_name = "{} {}".format(first_name, last_name).strip() or email
    token_id = None
    token_ref = None

    if is_resend:
        existing_tokens = (
            db.collection("intake_tokens")
            .where("caseId", "==", case_id)
            .where("used", "==", False)
            .limit(1)
            .stream()
        )
        for doc in existing_tokens:
            token_id = doc.id
            token_ref = db.collection("intake_tokens").document(token_id)
            logger.info("resend: reusing existing token=%s for case=%s", token_id, case_id)
            break

    if token_id is None:
        token_id = str(uuid.uuid4())
        expires_at = now + timedelta(days=TOKEN_EXPIRY_DAYS)

        prefill_url = _build_prefill_url(
            form_config=form_config,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            token_id=token_id,
        )

        token_ref = db.collection("intake_tokens").document(token_id)
        token_ref.set(
            {
                "tokenId": token_id,
                "caseId": case_id,
                "clientEmail": email,
                "clientName": client_name,
                "createdAt": firestore.SERVER_TIMESTAMP,
                "expiresAt": expires_at,
                "used": False,
                "usedAt": None,
                "submissionId": None,
                "reminderSentAt": None,
                "generatedBy": triggered_by,
                "dispatchedAt": firestore.SERVER_TIMESTAMP,
                "emailSent": False,
                "previewUrl": prefill_url,
                "auditLog": [
                    {
                        "event": "token_created",
                        "timestamp": now.isoformat(),
                        "detail": "generated by {}".format(triggered_by),
                    }
                ],
            }
        )
        logger.info(
            "intake_token_created: tokenId=%s caseId=%s email=%s",
            token_id,
            case_id,
            email,
        )
    else:
        # Rebuild prefill URL with fresh case data using existing token ID
        prefill_url = _build_prefill_url(
            form_config=form_config,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            token_id=token_id,
        )
        token_ref.update(
            {
                "dispatchedAt": firestore.SERVER_TIMESTAMP,
                "previewUrl": prefill_url,
                "auditLog": firestore.ArrayUnion(
                    [
                        {
                            "event": "resent",
                            "timestamp": now.isoformat(),
                            "detail": "resent by {}".format(triggered_by),
                        }
                    ]
                ),
            }
        )
        logger.info("intake_token_resent: tokenId=%s caseId=%s", token_id, case_id)

    # Send email
    email_sent = _send_intake_email(email, client_name, prefill_url)

    # Update token with email outcome
    token_ref.update(
        {
            "emailSent": email_sent,
            "auditLog": firestore.ArrayUnion(
                [
                    {
                        "event": "email_sent" if email_sent else "email_failed",
                        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                        "detail": "SendGrid dispatch",
                    }
                ]
            ),
        }
    )

    # Advance case status only for "New Lead" — resend cases stay in "Pending Client Information"
    if current_status == "New Lead":
        case_ref.update(
            {
                "status": "Pending Client Information",
                "updatedAt": firestore.SERVER_TIMESTAMP,
            }
        )
        logger.info(
            "case status advanced to Pending Client Information: %s", case_id
        )

    return flask.make_response(
        flask.jsonify(
            {
                "tokenId": token_id,
                "previewUrl": prefill_url,
                "emailSent": email_sent,
            }
        ),
        200,
        cors_headers,
    )
