#!/usr/bin/env python3
"""
E2E test for welcome SMS flow.

Tests the full pipeline:
  1. POST /tasks/sms  →  Cloud Run notification service
  2. Template fetched from Firestore (welcome-sms)
  3. Variables substituted: clientName, caseId, portalUrl
  4. SMS dispatched via Twilio
  5. Delivery record written to Firestore sms_delivery_records

Usage — with a real case from Firestore:
  python services/notification/tests/e2e_welcome_sms.py \
    --project simpletort-zadroga-dev \
    --database simpletort-dev \
    --case-id ZAD-2025-03-0001

  # Override the destination phone (useful if case phone is not verified in Twilio)
  python services/notification/tests/e2e_welcome_sms.py \
    --project simpletort-zadroga-dev \
    --database simpletort-dev \
    --case-id ZAD-2025-03-0001 \
    --to +917275624118

  # List available cases to pick one for testing
  python services/notification/tests/e2e_welcome_sms.py \
    --project simpletort-zadroga-dev \
    --database simpletort-dev \
    --list-cases

  # Dry run (no SMS sent, just template rendering check)
  python services/notification/tests/e2e_welcome_sms.py \
    --project simpletort-zadroga-dev \
    --database simpletort-dev \
    --case-id ZAD-2025-03-0001 \
    --dry-run
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone

# ── Config ─────────────────────────────────────────────────────────────────────

DEFAULT_SERVICE_URL  = "https://notification-dev-292736139819.us-central1.run.app"
DEFAULT_PROJECT      = "simpletort-zadroga-dev"
DEFAULT_DATABASE     = "simpletort-dev"
DEFAULT_COLLECTION   = "notificationTemplates"
DELIVERY_COLLECTION  = "sms_delivery_records"
CASES_COLLECTION     = "cases"
PORTAL_BASE_URL      = "https://portal.zadroga.com/c"

# Fallback test data used only when --case-id is not provided
FALLBACK_VARIABLES = {
    "clientName": "E2E Test Client",
    "caseId":     "ZAD-E2E-001",
    "portalUrl":  f"{PORTAL_BASE_URL}/ZAD-E2E-001",
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
    """Get a Google ID token for calling Cloud Run services."""
    # Method 1: gcloud CLI (most reliable for local dev)
    try:
        result = subprocess.run(
            ["gcloud", "auth", "print-identity-token"],
            capture_output=True, text=True, check=True,
        )
        token = result.stdout.strip()
        if token:
            return token
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Method 2: google-auth library (works on GCP metadata server)
    try:
        import google.auth.transport.requests
        import google.oauth2.id_token
        auth_req = google.auth.transport.requests.Request()
        token = google.oauth2.id_token.fetch_id_token(auth_req, audience)
        if token:
            return token
    except Exception:
        pass

    print("ERROR: Could not get identity token.")
    print("       Run: gcloud auth login")
    print("       Then verify: gcloud auth print-identity-token")
    sys.exit(1)


def _fetch_case(project: str, database: str, case_id: str) -> dict:
    """Fetch a real case from Firestore and build template variables."""
    db = _get_firestore_client(project, database)
    doc = db.collection(CASES_COLLECTION).document(case_id).get()

    if not doc.exists:
        print(f"ERROR: Case '{case_id}' not found in Firestore collection '{CASES_COLLECTION}'")
        print(f"       Use --list-cases to see available cases")
        sys.exit(1)

    data = doc.to_dict()
    first_name = data.get("firstName", "")
    last_name  = data.get("lastName", "")
    client_name = f"{first_name} {last_name}".strip() or "Client"
    phone       = data.get("phone", "")
    portal_url  = f"{PORTAL_BASE_URL}/{case_id}"

    print(f"\nPASS  Case found: {case_id}")
    print(f"      clientName   : {client_name}")
    print(f"      phone        : {phone}")
    print(f"      status       : {data.get('status', 'unknown')}")
    print(f"      email        : {data.get('email', '')}")
    print(f"      portalUrl    : {portal_url}")

    variables = {
        "clientName": client_name,
        "caseId":     case_id,
        "portalUrl":  portal_url,
    }

    return {"variables": variables, "phone": phone, "case_data": data}


def _list_cases(project: str, database: str, limit: int = 10) -> None:
    """List recent cases available for testing."""
    db = _get_firestore_client(project, database)
    print(f"\nRecent cases in '{CASES_COLLECTION}' (limit {limit}):\n")
    print(f"  {'CASE ID':<25} {'NAME':<25} {'PHONE':<18} {'STATUS'}")
    print(f"  {'-'*25} {'-'*25} {'-'*18} {'-'*15}")

    docs = db.collection(CASES_COLLECTION).limit(limit).stream()
    count = 0
    for doc in docs:
        d = doc.to_dict()
        name   = f"{d.get('firstName','')} {d.get('lastName','')}".strip()
        phone  = d.get("phone", "—")
        status = d.get("status", "—")
        print(f"  {doc.id:<25} {name:<25} {phone:<18} {status}")
        count += 1

    if count == 0:
        print("  (no cases found)")
    print(f"\nRun with: --case-id <CASE_ID>")
    sys.exit(0)


def _check_template(project: str, database: str, collection: str) -> dict:
    """Fetch welcome-sms template from Firestore and validate it."""
    db = _get_firestore_client(project, database)
    doc = db.collection(collection).document("welcome-sms").get()

    if not doc.exists:
        print(f"FAIL  Template 'welcome-sms' not found in Firestore")
        print(f"      Collection: {collection}")
        print(f"      Run: python infrastructure/seed_firestore_templates.py --project {project} --database {database} --collection {collection}")
        sys.exit(1)

    data = doc.to_dict()
    print(f"PASS  Template found: welcome-sms")
    print(f"      channel      : {data.get('channel')}")
    print(f"      isActive     : {data.get('isActive')}")
    print(f"      triggerEvent : {data.get('triggerEvent')}")
    print(f"      variables    : {data.get('variables', [])}")
    print(f"      body preview : {data.get('body', '')[:80]}…")
    return data


def _render_template(body: str, variables: dict) -> str:
    """Substitute {{placeholders}} and verify result."""
    import re
    rendered = body
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))

    remaining = re.findall(r"\{\{(\w+)\}\}", rendered)
    if remaining:
        print(f"FAIL  Unreplaced variables in template: {remaining}")
        print(f"      Provided variables: {list(variables.keys())}")
        sys.exit(1)

    char_count = len(rendered)
    under_160  = char_count <= 160
    print(f"\nPASS  Template rendered successfully")
    print(f"      Char count   : {char_count} ({'✓ under 160' if under_160 else '✗ OVER 160 — will be multi-segment'})")
    print(f"      Rendered SMS : {rendered}")
    if not under_160:
        print(f"\nWARN  SMS exceeds 160 chars — will be sent as {-(-char_count // 153)} segments")
    return rendered


def _send_sms_request(
    service_url: str,
    token: str,
    to: str,
    variables: dict,
    case_id: str,
    request_id: str,
) -> dict:
    """POST to /tasks/sms and return the response body."""
    import urllib.request
    import urllib.error

    payload = {
        "to":         to,
        "templateId": "welcome-sms",
        "variables":  variables,
        "caseId":     case_id,
        "requestId":  request_id,
    }

    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        f"{service_url}/tasks/sms",
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


def _check_delivery_record(project: str, database: str, delivery_id: str) -> str:
    """Verify Firestore delivery record was written correctly. Returns status."""
    db  = _get_firestore_client(project, database)
    doc = db.collection(DELIVERY_COLLECTION).document(delivery_id).get()

    if not doc.exists:
        print(f"FAIL  Delivery record '{delivery_id}' not found in Firestore")
        sys.exit(1)

    data = doc.to_dict()
    print(f"\nPASS  Delivery record found in Firestore")
    print(f"      deliveryId   : {data.get('deliveryId')}")
    print(f"      status       : {data.get('status')}")
    print(f"      templateId   : {data.get('templateId')}")
    print(f"      to           : {data.get('to')}")
    print(f"      messageSid   : {data.get('messageSid')}")
    print(f"      segmentCount : {data.get('segmentCount')}")
    print(f"      attemptedAt  : {data.get('attemptedAt')}")

    return data.get("status", "unknown")


# ── Main ───────────────────────────────────────────────────────────────────────

def run_e2e(args: argparse.Namespace) -> None:
    print("=" * 60)
    print("  ZAD Notification — Welcome SMS E2E Test")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    # Optional: list cases and exit
    if args.list_cases:
        _list_cases(args.project, args.database)

    # Step 0 — Fetch real case data or use fallback
    variables = FALLBACK_VARIABLES.copy()
    phone_from_case = None

    if args.case_id:
        print(f"\n[0/4] Fetching case from Firestore: {args.case_id}…")
        result          = _fetch_case(args.project, args.database, args.case_id)
        variables       = result["variables"]
        phone_from_case = result["phone"]
    else:
        print(f"\n[0/4] No --case-id provided — using fallback test variables")
        print(f"      clientName : {variables['clientName']}")
        print(f"      caseId     : {variables['caseId']}")

    # Resolve destination phone: --to overrides case phone
    to_number = args.to or phone_from_case
    if not to_number and not args.dry_run:
        print("\nERROR: No phone number available.")
        print("       Either provide --to +E164NUMBER or use --case-id with a case that has a phone field")
        sys.exit(1)

    # Step 1 — Check template in Firestore
    print(f"\n[1/4] Checking Firestore template…")
    template_data = _check_template(args.project, args.database, args.collection)

    # Step 2 — Render template locally
    print(f"\n[2/4] Rendering template with variables…")
    _render_template(template_data.get("body", ""), variables)

    if args.dry_run:
        print("\n✓ Dry run complete — no SMS sent.")
        return

    # Step 3 — Send via deployed service
    case_id    = variables["caseId"]
    request_id = f"e2e-{int(time.time())}"
    print(f"\n[3/4] Sending SMS to {to_number}…")
    token    = _get_token(args.service_url)
    response = _send_sms_request(
        service_url=args.service_url,
        token=token,
        to=to_number,
        variables=variables,
        case_id=case_id,
        request_id=request_id,
    )

    print(f"PASS  Service responded:")
    print(f"      status       : {response.get('status')}")
    print(f"      deliveryId   : {response.get('deliveryId')}")
    print(f"      success      : {response.get('success')}")
    print(f"      messageSid   : {response.get('messageSid')}")
    print(f"      segmentCount : {response.get('segmentCount')}")

    delivery_id = response.get("deliveryId")
    if not delivery_id:
        print("FAIL  No deliveryId in response")
        sys.exit(1)

    # Step 4 — Verify Firestore delivery record
    print(f"\n[4/4] Verifying Firestore delivery record…")
    time.sleep(2)
    status = _check_delivery_record(args.project, args.database, delivery_id)

    # Summary
    print("\n" + "=" * 60)
    if status == "sent":
        print("  ✅  ALL CHECKS PASSED — Welcome SMS E2E test complete")
        print(f"      Sent to         : {to_number}")
        print(f"      Case            : {case_id}")
        print(f"      Twilio Console  : https://console.twilio.com/us1/monitor/logs/sms")
        print(f"      Firestore record: {DELIVERY_COLLECTION}/{delivery_id}")
    elif status == "failed":
        print(f"  ⚠️   SMS FAILED — check Twilio console for error details")
        print(f"      This may be because {to_number} is not verified in your Twilio trial account")
        print(f"      Verify at: https://console.twilio.com/us1/develop/phone-numbers/verified")
    elif status == "opted_out":
        print(f"  ⚠️   OPTED OUT — {to_number} has opted out of SMS")
    else:
        print(f"  ⚠️   SMS STATUS: {status}")
    print("=" * 60)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="E2E test for welcome SMS flow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--service-url", default=DEFAULT_SERVICE_URL,
                   help="Cloud Run service URL")
    p.add_argument("--project",     default=DEFAULT_PROJECT,
                   help="GCP project ID")
    p.add_argument("--database",    default=DEFAULT_DATABASE,
                   help="Firestore database name")
    p.add_argument("--collection",  default=DEFAULT_COLLECTION,
                   help="Firestore templates collection name")
    p.add_argument("--case-id",     default=None,
                   help="Real case ID to fetch from Firestore (e.g. ZAD-2025-03-0001)")
    p.add_argument("--to",          default=None,
                   help="Override destination phone in E.164 format (e.g. +917275624118)")
    p.add_argument("--list-cases",  action="store_true",
                   help="List available cases from Firestore and exit")
    p.add_argument("--dry-run",     action="store_true",
                   help="Validate template locally without sending SMS")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_e2e(args)
