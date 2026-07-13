#!/usr/bin/env python3
"""
E2E test for welcome email flow.

Tests the full pipeline:
  1. POST /internal/email/preview  →  Cloud Run notification service
  2. Template fetched from Firestore (welcome_email)
  3. Variables substituted: clientName, caseId
  4. Rendered subject + HTML body returned (no email sent)

Usage — preview rendered email content (no email sent):
  python services/notification/tests/e2e_welcome_email.py \\
    --project <your-gcp-project-id> \\
    --database simpletort-dev \\
    --case-id ZAD-2024-01-0001

  # Preview a specific template (e.g. document reminders)
  python services/notification/tests/e2e_welcome_email.py \\
    --project <your-gcp-project-id> \\
    --database simpletort-dev \\
    --case-id ZAD-2024-01-0001 \\
    --template document_reminder_48hr_email

  # List available cases to pick one for testing
  python services/notification/tests/e2e_welcome_email.py \\
    --project <your-gcp-project-id> \\
    --database simpletort-dev \\
    --list-cases
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

# ── Config ─────────────────────────────────────────────────────────────────────

DEFAULT_SERVICE_URL  = "https://notification-dev-292736139819.us-central1.run.app"
DEFAULT_PROJECT      = os.environ.get("GCP_PROJECT_ID", "")
DEFAULT_DATABASE     = "simpletort-dev"
DEFAULT_COLLECTION   = "notificationTemplates"
DEFAULT_TEMPLATE     = "welcome_email"
CASES_COLLECTION     = "cases"
PORTAL_BASE_URL      = "https://portal.zadroga.com/c"

FALLBACK_VARIABLES = {
    "clientName":     "E2E Test Client",
    "caseId":         "ZAD-E2E-001",
    "portalUrl":      f"{PORTAL_BASE_URL}/ZAD-E2E-001",
    "missingDocs":    "Police Report, Medical Records",
    "deadlineLabel":  "within 48 hours",
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_firestore_client(project: str, database: str):
    try:
        from google.cloud import firestore
    except ImportError:
        print("ERROR: pip install google-cloud-firestore")
        sys.exit(1)
    return firestore.Client(project=project, database=database)


def _get_token(audience: str) -> str:
    # Try both "gcloud" and "gcloud.cmd" (Windows)
    for cmd in (["gcloud", "auth", "print-identity-token"],
                ["gcloud.cmd", "auth", "print-identity-token"]):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True,
            )
            token = result.stdout.strip()
            if token:
                return token
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    try:
        import google.auth.transport.requests
        import google.oauth2.id_token
        auth_req = google.auth.transport.requests.Request()
        token = google.oauth2.id_token.fetch_id_token(auth_req, audience)
        if token:
            return token
    except Exception:
        pass

    print("ERROR: Could not get identity token. Run: gcloud auth login")
    sys.exit(1)


def _fetch_case(project: str, database: str, case_id: str) -> dict:
    db = _get_firestore_client(project, database)
    doc = db.collection(CASES_COLLECTION).document(case_id).get()

    if not doc.exists:
        print(f"ERROR: Case '{case_id}' not found. Use --list-cases to see available cases.")
        sys.exit(1)

    data = doc.to_dict()
    lead = data.get("leadData") or {}

    first_name  = lead.get("firstName") or data.get("firstName", "")
    last_name   = lead.get("lastName")  or data.get("lastName", "")
    email       = lead.get("email")     or data.get("email", "")
    client_name = f"{first_name} {last_name}".strip() or "Client"
    portal_url  = data.get("portalAccessLink") or f"{PORTAL_BASE_URL}/{case_id}"
    missing_docs = data.get("missingDocuments", [])
    missing_docs_str = ", ".join(missing_docs) if isinstance(missing_docs, list) else str(missing_docs)

    print(f"\nPASS  Case found: {case_id}")
    print(f"      clientName   : {client_name}")
    print(f"      email        : {email or '(not set)'}")
    print(f"      status       : {data.get('status', 'unknown')}")
    print(f"      portalUrl    : {portal_url}")
    print(f"      missingDocs  : {missing_docs_str or '(none)'}")

    variables = {
        "clientName":    client_name,
        "caseId":        case_id,
        "portalUrl":     portal_url,
        "missingDocs":   missing_docs_str or "Required Documents",
        "deadlineLabel": "within 48 hours",
    }

    return {"variables": variables, "email": email}


def _list_cases(project: str, database: str, limit: int = 10) -> None:
    db = _get_firestore_client(project, database)
    print(f"\nRecent cases in '{CASES_COLLECTION}' (limit {limit}):\n")
    print(f"  {'CASE ID':<25} {'NAME':<25} {'EMAIL':<30} {'STATUS'}")
    print(f"  {'-'*25} {'-'*25} {'-'*30} {'-'*15}")

    docs = list(db.collection(CASES_COLLECTION).limit(limit).get())
    for doc in docs:
        d    = doc.to_dict()
        lead = d.get("leadData") or {}
        name  = f"{lead.get('firstName', d.get('firstName',''))} {lead.get('lastName', d.get('lastName',''))}".strip()
        email = lead.get("email") or d.get("email", "—")
        status = d.get("status", "—")
        print(f"  {doc.id:<25} {name:<25} {email:<30} {status}")

    print(f"\nRun with: --case-id <CASE_ID>")
    sys.exit(0)


def _strip_html(html: str) -> str:
    """Strip HTML tags for clean terminal output."""
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    return text


def _preview_email(
    service_url: str,
    token: str,
    template_id: str,
    variables: dict,
    case_id: str,
) -> dict:
    import urllib.request
    import urllib.error

    payload = {
        "templateId": template_id,
        "variables":  variables,
        "caseId":     case_id,
    }

    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        f"{service_url}/internal/email/preview",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"FAIL  HTTP {e.code} from service: {body}")
        sys.exit(1)


# ── Main ───────────────────────────────────────────────────────────────────────

def run_e2e(args: argparse.Namespace) -> None:
    print("=" * 65)
    print("  ZAD Notification — Email Preview E2E Test")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 65)

    if args.list_cases:
        _list_cases(args.project, args.database)

    # Step 0 — Fetch case or use fallback
    variables = FALLBACK_VARIABLES.copy()
    email_from_case = None

    if args.case_id:
        print(f"\n[0/3] Fetching case from Firestore: {args.case_id}...")
        result          = _fetch_case(args.project, args.database, args.case_id)
        variables       = result["variables"]
        email_from_case = result["email"]
    else:
        print(f"\n[0/3] No --case-id provided — using fallback test variables")
        print(f"      clientName : {variables['clientName']}")
        print(f"      caseId     : {variables['caseId']}")

    case_id = args.case_id or variables["caseId"]

    # Step 1 — Check template in Firestore
    print(f"\n[1/3] Checking Firestore template: {args.template}...")
    db  = _get_firestore_client(args.project, args.database)
    doc = db.collection(args.collection).document(args.template).get()

    if not doc.exists:
        print(f"FAIL  Template '{args.template}' not found in Firestore")
        print(f"      Collection: {args.collection}")
        sys.exit(1)

    tdata = doc.to_dict()
    print(f"PASS  Template found: {args.template}")
    print(f"      channel      : {tdata.get('channel', 'EMAIL')}")
    print(f"      isActive     : {tdata.get('isActive', True)}")
    print(f"      triggerEvent : {tdata.get('triggerEvent', '—')}")
    print(f"      subject      : {tdata.get('subject', '(none)')[:80]}")

    # Step 2 — Preview via service
    print(f"\n[2/3] Calling /internal/email/preview on notification service...")
    token    = _get_token(args.service_url)
    response = _preview_email(
        service_url=args.service_url,
        token=token,
        template_id=args.template,
        variables=variables,
        case_id=case_id,
    )

    print(f"PASS  Template rendered successfully")

    # Step 3 — Show full output
    print(f"\n[3/3] Rendered email output:")
    print("=" * 65)
    print(f"  FROM     : {response.get('from')}")
    print(f"  TEMPLATE : {response.get('templateId')}")
    print(f"  SUBJECT  : {response.get('subject')}")
    print("-" * 65)
    print("  BODY (plain text):")
    print()
    plain = _strip_html(response.get("htmlBody", ""))
    for line in plain.splitlines():
        print(f"    {line}")
    print()
    print("-" * 65)
    print("  HTML BODY (raw — first 500 chars):")
    print()
    html_preview = response.get("htmlBody", "")[:500]
    print(f"    {html_preview}")
    if len(response.get("htmlBody", "")) > 500:
        print(f"    ... [{len(response.get('htmlBody',''))} total chars]")
    print()
    print("=" * 65)
    print()
    print(f"  To       : {args.to or email_from_case or '(no email — preview only)'}")
    print()
    print("  NOTE: No email was sent. This is a preview only.")
    print("        To send, verify sender in SendGrid then use /internal/email/send")
    print("=" * 65)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="E2E preview test for email templates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--service-url", default=DEFAULT_SERVICE_URL)
    p.add_argument("--project",     default=DEFAULT_PROJECT)
    p.add_argument("--database",    default=DEFAULT_DATABASE)
    p.add_argument("--collection",  default=DEFAULT_COLLECTION)
    p.add_argument("--template",    default=DEFAULT_TEMPLATE,
                   help="Template ID to preview (default: welcome_email)")
    p.add_argument("--case-id",     default=None,
                   help="Real case ID to fetch from Firestore")
    p.add_argument("--to",          default=None,
                   help="Recipient email address (display only — no email sent)")
    p.add_argument("--list-cases",  action="store_true",
                   help="List available cases from Firestore and exit")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_e2e(args)
