#!/usr/bin/env python3
"""
send_email.py — CLI runner for the Notification Email service.

Runs the real service code directly (email_service, template_service,
firestore_client, sendgrid_client) without going through HTTP.

Usage:
    python services/notification/send_email.py \
        --case-id ZAD-2024-01-0001 \
        --template welcome_email

    # Override destination email
    python services/notification/send_email.py \
        --case-id ZAD-2024-01-0001 \
        --template welcome_email \
        --to azad@plutusllp.com

    # List available cases
    python services/notification/send_email.py --list-cases

Environment variables required (or set defaults below):
    FIRESTORE_DATABASE_ID=simpletort-dev
    FIRESTORE_SMS_TEMPLATES_COLLECTION=notificationTemplates
    GCP_PROJECT_ID=simpletort-zadroga-dev
    SENDGRID_API_KEY=...
    SENDGRID_FROM_EMAIL=...
    SENDGRID_FROM_NAME=...
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

# ── Make sure imports resolve from the notification service root ───────────────
SERVICE_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SERVICE_ROOT)

# ── Set required env vars if not already present ──────────────────────────────
os.environ.setdefault("FIRESTORE_DATABASE_ID",                    "simpletort-dev")
os.environ.setdefault("GCP_PROJECT_ID",                           "simpletort-zadroga-dev")
os.environ.setdefault("FIRESTORE_SMS_TEMPLATES_COLLECTION",       "notificationTemplates")
os.environ.setdefault("FIRESTORE_EMAIL_DELIVERY_RECORDS_COLLECTION", "email_delivery_records")

CASES_COLLECTION = "cases"
PORTAL_BASE_URL  = "https://portal.zadroga.com/c"


# ── Firestore helpers (sync — for CLI case lookup only) ───────────────────────

def _get_sync_firestore():
    try:
        from google.cloud import firestore
    except ImportError:
        print("ERROR: pip install google-cloud-firestore")
        sys.exit(1)
    project  = os.environ.get("GCP_PROJECT_ID", "simpletort-zadroga-dev")
    database = os.environ.get("FIRESTORE_DATABASE_ID", "simpletort-dev")
    return firestore.Client(project=project, database=database)


def _fetch_case(case_id: str) -> dict:
    db  = _get_sync_firestore()
    doc = db.collection(CASES_COLLECTION).document(case_id).get()

    if not doc.exists:
        print(f"FAIL  Case '{case_id}' not found in Firestore")
        print(f"      Use --list-cases to see available cases")
        sys.exit(1)

    data        = doc.to_dict()
    lead        = data.get("leadData") or {}
    first_name  = lead.get("firstName") or data.get("firstName", "")
    last_name   = lead.get("lastName")  or data.get("lastName", "")
    email       = lead.get("email")     or data.get("email", "")
    client_name = f"{first_name} {last_name}".strip() or "Client"
    portal_url  = data.get("portalAccessLink") or f"{PORTAL_BASE_URL}/{case_id}"
    missing_docs = data.get("missingDocuments", [])
    missing_docs_str = ", ".join(missing_docs) if isinstance(missing_docs, list) else str(missing_docs)

    print(f"PASS  Case found: {case_id}")
    print(f"      clientName   : {client_name}")
    print(f"      email        : {email or '(not set)'}")
    print(f"      status       : {data.get('status', 'unknown')}")
    print(f"      portalUrl    : {portal_url}")
    print(f"      missingDocs  : {missing_docs_str or '(none)'}")

    return {
        "variables": {
            "clientName":     client_name,
            "caseId":         case_id,
            "portalUrl":      portal_url,
            "missingDocs":    missing_docs_str or "Required Documents",
            "missingDocsList": missing_docs_str or "Required Documents",
            "deadlineLabel":  "within 48 hours",
            "deadline":       "within 48 hours",
        },
        "email": email,
    }


def _list_cases(limit: int = 10) -> None:
    db   = _get_sync_firestore()
    docs = list(db.collection(CASES_COLLECTION).limit(limit).get())
    print(f"\nRecent cases (limit {limit}):\n")
    print(f"  {'CASE ID':<25} {'NAME':<25} {'EMAIL':<30} {'STATUS'}")
    print(f"  {'-'*25} {'-'*25} {'-'*30} {'-'*15}")
    for doc in docs:
        d    = doc.to_dict()
        lead = d.get("leadData") or {}
        name  = f"{lead.get('firstName', d.get('firstName',''))} {lead.get('lastName', d.get('lastName',''))}".strip()
        email = lead.get("email") or d.get("email", "—")
        status = d.get("status", "—")
        print(f"  {doc.id:<25} {name:<25} {email:<30} {status}")
    print(f"\nRun with: --case-id <CASE_ID>")
    sys.exit(0)


# ── Main async runner ─────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> None:
    print("=" * 62)
    print("  ZAD Notification — Email Service Runner")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 62)

    if args.list_cases:
        _list_cases()

    # ── Step 0: Fetch case from Firestore ─────────────────────────────────
    print(f"\n[0/4] Fetching case from Firestore: {args.case_id}...")
    case_result = _fetch_case(args.case_id)
    variables   = case_result["variables"]
    to_email    = args.to or case_result["email"]

    # Auto-set deadlineLabel based on template
    if "7day" in args.template:
        variables["deadlineLabel"] = "within 7 days"
        variables["deadline"]      = "within 7 days"
    elif "48hr" in args.template:
        variables["deadlineLabel"] = "within 48 hours"
        variables["deadline"]      = "within 48 hours"

    if not to_email:
        print("\nERROR: No email address found for this case.")
        print("       Use --to email@example.com to override.")
        sys.exit(1)

    # ── Step 1: Check template in Firestore ───────────────────────────────
    print(f"\n[1/4] Checking Firestore template: {args.template}...")
    from services.firestore_client import get_db
    from services.template_service import fetch_template, TemplateNotFoundError, TemplateDisabledError

    db = get_db()
    try:
        template = await fetch_template(args.template, db)
        print(f"PASS  Template found: {args.template}")
        print(f"      channel      : {template.get('channel', 'EMAIL')}")
        print(f"      isActive     : {template.get('isActive', True)}")
        print(f"      triggerEvent : {template.get('triggerEvent', '—')}")
        print(f"      subject      : {template.get('subject', '')[:80]}")
        print(f"      body preview : {template.get('body', '')[:80]}...")
    except TemplateNotFoundError:
        print(f"FAIL  Template '{args.template}' not found in Firestore")
        sys.exit(1)
    except TemplateDisabledError:
        print(f"FAIL  Template '{args.template}' is disabled (isActive: false)")
        sys.exit(1)

    # ── Step 2: Render template ───────────────────────────────────────────
    print(f"\n[2/4] Rendering template with variables...")
    from services.template_service import render_template, MissingVariableError

    try:
        rendered = await render_template(args.template, variables, db)
        print(f"PASS  Template rendered successfully")
        print(f"      subject      : {rendered.subject}")
        print(f"      html chars   : {len(rendered.html_body)}")
        print(f"      sms chars    : {len(rendered.sms_safe)}")
        print(f"      body preview : {rendered.sms_safe[:100]}...")
    except MissingVariableError as exc:
        print(f"FAIL  Missing variables: {exc}")
        sys.exit(1)

    # ── Step 3: Send via real email_service ───────────────────────────────
    import uuid
    from config import get_settings
    settings   = get_settings()

    print(f"\n[3/4] Sending email to {to_email}...")
    print(f"      from         : {settings.sendgrid_from_name} <{settings.sendgrid_from_email}>")
    print(f"      subject      : {rendered.subject}")
    from services.email_service import send_email

    request_id = f"cli-{uuid.uuid4().hex[:8]}"
    result     = await send_email(
        to          = to_email,
        template_id = args.template,
        variables   = variables,
        db          = db,
        case_id     = args.case_id,
        request_id  = request_id,
    )

    if result.success:
        print(f"PASS  Email sent successfully via SendGrid")
        print(f"      status       : {result.status}")
        print(f"      deliveryId   : {result.delivery_id}")
        print(f"      messageId    : {result.message_id}")
        print(f"      statusCode   : {result.status_code}")
    else:
        print(f"FAIL  Email send failed")
        print(f"      status       : {result.status}")
        print(f"      deliveryId   : {result.delivery_id}")
        print(f"      statusCode   : {result.status_code}")
        print(f"      error        : {result.error_message}")

    # ── Step 4: Verify Firestore delivery record ───────────────────────────
    print(f"\n[4/4] Verifying Firestore delivery record...")
    await asyncio.sleep(2)

    record_ref = db.collection(settings.email_delivery_records_collection).document(result.delivery_id)
    record_doc = await record_ref.get()

    if not record_doc.exists:
        print(f"FAIL  Delivery record not found in Firestore")
    else:
        rec = record_doc.to_dict()
        print(f"PASS  Delivery record written to Firestore")
        print(f"      deliveryId   : {rec.get('deliveryId')}")
        print(f"      status       : {rec.get('status')}")
        print(f"      templateId   : {rec.get('templateId')}")
        print(f"      messageId    : {rec.get('sendgridMessageId')}")
        print(f"      statusCode   : {rec.get('sendgridStatusCode')}")
        print(f"      attemptedAt  : {rec.get('attemptedAt')}")

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    if result.status == "sent":
        print("  ALL CHECKS PASSED — Email sent successfully")
        print(f"      Sent to         : {to_email}")
        print(f"      Case            : {args.case_id}")
        print(f"      SendGrid        : https://app.sendgrid.com/email_activity")
        print(f"      Firestore       : email_delivery_records/{result.delivery_id}")
    elif result.status == "failed":
        print(f"  EMAIL FAILED — SendGrid rejected the send")
        print(f"      Error           : {result.error_message}")
        if "403" in str(result.error_message):
            print(f"")
            print(f"  FIX: Verify sender in SendGrid:")
            print(f"       https://app.sendgrid.com/settings/sender_auth")
            print(f"       Add '{settings.sendgrid_from_email}' as a verified sender")
    elif result.status == "template_error":
        print(f"  TEMPLATE ERROR — {result.error_message}")
    else:
        print(f"  STATUS: {result.status}")
    print("=" * 62)


# ── Arg parser ────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the Email notification service directly from CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--case-id",    default=None,           help="Firestore case ID (e.g. ZAD-2024-01-0001)")
    p.add_argument("--template",   default="welcome_email", help="Template ID (default: welcome_email)")
    p.add_argument("--to",         default=None,           help="Override destination email address")
    p.add_argument("--list-cases", action="store_true",    help="List available cases and exit")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if not args.list_cases and not args.case_id:
        print("ERROR: --case-id is required (or use --list-cases to browse)")
        sys.exit(1)
    asyncio.run(run(args))
