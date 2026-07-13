#!/usr/bin/env python3
"""
send_sms.py — CLI runner for the Notification SMS service.

Runs the real service code directly (sms_service, template_service,
firestore_client, twilio_client) without going through HTTP.

Usage:
    python services/notification/send_sms.py \
        --case-id ZAD-2024-01-0001 \
        --template welcome_sms

    # Override destination phone
    python services/notification/send_sms.py \
        --case-id ZAD-2024-01-0001 \
        --template welcome_sms \
        --to +917275624118

    # List available cases
    python services/notification/send_sms.py --list-cases

Environment variables required (or set in .env):
    FIRESTORE_DATABASE_ID=simpletort-dev
    FIRESTORE_SMS_TEMPLATES_COLLECTION=notificationTemplates
    GCP_PROJECT_ID=<your-gcp-project-id>
    TWILIO_ACCOUNT_SID=...
    TWILIO_AUTH_TOKEN=...
    TWILIO_FROM_NUMBER=...
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
os.environ.setdefault("FIRESTORE_DATABASE_ID",               "simpletort-dev")
os.environ.setdefault("GCP_PROJECT_ID",                      "")
os.environ.setdefault("FIRESTORE_SMS_TEMPLATES_COLLECTION",  "notificationTemplates")

CASES_COLLECTION = "cases"
PORTAL_BASE_URL  = "https://portal.zadroga.com/c"


# ── Firestore helpers (sync — for CLI case lookup only) ───────────────────────

def _get_sync_firestore():
    try:
        from google.cloud import firestore
    except ImportError:
        print("ERROR: pip install google-cloud-firestore")
        sys.exit(1)
    project  = os.environ.get("GCP_PROJECT_ID") or exit("ERROR: GCP_PROJECT_ID is not set")
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
    phone       = lead.get("phone")     or data.get("phone", "")
    email       = lead.get("email")     or data.get("email", "")
    client_name = f"{first_name} {last_name}".strip() or "Client"
    portal_url  = data.get("portalAccessLink") or f"{PORTAL_BASE_URL}/{case_id}"

    print(f"PASS  Case found: {case_id}")
    print(f"      clientName   : {client_name}")
    print(f"      phone        : {phone}")
    print(f"      status       : {data.get('status', 'unknown')}")
    print(f"      email        : {email}")
    print(f"      portalUrl    : {portal_url}")

    return {
        "variables": {
            "clientName": client_name,
            "caseId":     case_id,
            "portalUrl":  portal_url,
        },
        "phone": phone,
        "email": email,
    }


def _list_cases(limit: int = 10) -> None:
    db   = _get_sync_firestore()
    docs = list(db.collection(CASES_COLLECTION).limit(limit).get())
    print(f"\nRecent cases (limit {limit}):\n")
    print(f"  {'CASE ID':<25} {'NAME':<25} {'PHONE':<18} {'STATUS'}")
    print(f"  {'-'*25} {'-'*25} {'-'*18} {'-'*15}")
    for doc in docs:
        d    = doc.to_dict()
        lead = d.get("leadData") or {}
        name = f"{lead.get('firstName', d.get('firstName',''))} {lead.get('lastName', d.get('lastName',''))}".strip()
        phone  = lead.get("phone") or d.get("phone", "—")
        status = d.get("status", "—")
        print(f"  {doc.id:<25} {name:<25} {phone:<18} {status}")
    print(f"\nRun with: --case-id <CASE_ID>")
    sys.exit(0)


# ── Main async runner ─────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> None:
    print("=" * 60)
    print("  ZAD Notification — SMS Service Runner")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    if args.list_cases:
        _list_cases()

    # ── Step 0: Fetch case from Firestore ─────────────────────────────────
    print(f"\n[0/4] Fetching case from Firestore: {args.case_id}…")
    case_result = _fetch_case(args.case_id)
    variables   = case_result["variables"]
    phone       = args.to or case_result["phone"]

    if not phone:
        print("\nERROR: No phone number found for this case.")
        print("       Use --to +E164NUMBER to override.")
        sys.exit(1)

    # ── Step 1: Check template in Firestore ───────────────────────────────
    print(f"\n[1/4] Checking Firestore template…")
    from services.firestore_client import get_db
    from services.template_service import fetch_template, TemplateNotFoundError, TemplateDisabledError

    db = get_db()
    try:
        template = await fetch_template(args.template, db)
        print(f"PASS  Template found: {args.template}")
        print(f"      channel      : {template.get('channel')}")
        print(f"      isActive     : {template.get('isActive')}")
        print(f"      triggerEvent : {template.get('triggerEvent')}")
        print(f"      variables    : {template.get('variables', [])}")
        print(f"      body preview : {template.get('body', '')[:80]}…")
    except TemplateNotFoundError:
        print(f"FAIL  Template '{args.template}' not found in Firestore")
        sys.exit(1)
    except TemplateDisabledError:
        print(f"FAIL  Template '{args.template}' is disabled (isActive: false)")
        sys.exit(1)

    # ── Step 2: Render template ───────────────────────────────────────────
    print(f"\n[2/4] Rendering template with variables…")
    from services.template_service import render_template, MissingVariableError

    try:
        rendered = await render_template(args.template, variables, db)
        char_count = len(rendered.sms_safe)
        under_160  = char_count <= 160
        print(f"PASS  Template rendered successfully")
        print(f"      Char count   : {char_count} ({'OK under 160' if under_160 else 'OVER 160 - multi-segment'})")
        print(f"      Rendered SMS : {rendered.sms_safe}")
        if not under_160:
            print(f"\nWARN  SMS exceeds 160 chars — will send as {-(-char_count // 153)} segments")
    except MissingVariableError as exc:
        print(f"FAIL  Missing variables: {exc}")
        sys.exit(1)

    # ── Step 3: Send via real sms_service ─────────────────────────────────
    import uuid
    print(f"\n[3/4] Sending SMS to {phone}…")
    from services.sms_service import send_sms

    request_id = f"cli-{uuid.uuid4().hex[:8]}"
    result     = await send_sms(
        to          = phone,
        template_id = args.template,
        variables   = variables,
        db          = db,
        case_id     = args.case_id,
        request_id  = request_id,
    )

    print(f"PASS  SMS service responded:")
    print(f"      status       : {result.status}")
    print(f"      success      : {result.success}")
    print(f"      deliveryId   : {result.delivery_id}")
    print(f"      messageSid   : {result.message_sid}")
    print(f"      segmentCount : {result.segment_count}")
    if result.error_message:
        print(f"      error        : {result.error_message}")

    # ── Step 4: Verify Firestore delivery record ───────────────────────────
    print(f"\n[4/4] Verifying Firestore delivery record…")
    import asyncio as _asyncio
    await _asyncio.sleep(2)

    from config import get_settings
    settings   = get_settings()
    record_ref = db.collection(settings.delivery_records_collection).document(result.delivery_id)
    record_doc = await record_ref.get()

    if not record_doc.exists:
        print(f"FAIL  Delivery record not found in Firestore")
    else:
        rec = record_doc.to_dict()
        print(f"PASS  Delivery record found in Firestore")
        print(f"      deliveryId   : {rec.get('deliveryId')}")
        print(f"      status       : {rec.get('status')}")
        print(f"      templateId   : {rec.get('templateId')}")
        print(f"      messageSid   : {rec.get('twilioMessageSid')}")
        print(f"      segmentCount : {rec.get('segmentCount')}")
        print(f"      attemptedAt  : {rec.get('attemptedAt')}")

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if result.status == "sent":
        print("  ALL CHECKS PASSED - SMS sent successfully")
        print(f"      Sent to         : {phone}")
        print(f"      Case            : {args.case_id}")
        print(f"      Twilio Console  : https://console.twilio.com/us1/monitor/logs/sms")
    elif result.status == "failed":
        print(f"  SMS FAILED - Twilio rejected the send")
        print(f"      Error           : {result.error_message}")
        print(f"      Check Twilio    : https://console.twilio.com/us1/monitor/logs/sms")
    elif result.status == "template_error":
        print(f"  TEMPLATE ERROR - {result.error_message}")
    elif result.status == "opted_out":
        print(f"  OPTED OUT - {phone} has opted out of SMS")
    else:
        print(f"  STATUS: {result.status}")
    print("=" * 60)


# ── Arg parser ────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the SMS notification service directly from CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--case-id",    default=None,        help="Firestore case ID (e.g. ZAD-2024-01-0001)")
    p.add_argument("--template",   default="welcome_sms", help="Template ID (default: welcome_sms)")
    p.add_argument("--to",         default=None,        help="Override destination phone in E.164 format")
    p.add_argument("--list-cases", action="store_true", help="List available cases and exit")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if not args.list_cases and not args.case_id:
        print("ERROR: --case-id is required (or use --list-cases to browse)")
        sys.exit(1)
    asyncio.run(run(args))
