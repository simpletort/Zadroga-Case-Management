#!/usr/bin/env python3
"""
E2E test for welcome SMS flow.

Tests the full pipeline:
  1. POST /tasks/sms  →  Cloud Run notification service
  2. Template fetched from Firestore (welcome-sms)
  3. Variables substituted: clientName, caseId, portalUrl
  4. SMS dispatched via Twilio
  5. Delivery record written to Firestore sms_delivery_records

Usage (Cloud Shell or local with gcloud auth):
  # Against deployed dev service
  python services/notification/tests/e2e_welcome_sms.py \
    --service-url https://notification-dev-292736139819.us-central1.run.app \
    --project simpletort-zadroga-dev \
    --database simpletort-dev \
    --to +1YOURPHONENUMBER

  # Dry run (no SMS sent, just template rendering check)
  python services/notification/tests/e2e_welcome_sms.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone

# ── Config ─────────────────────────────────────────────────────────────────────

DEFAULT_SERVICE_URL = "https://notification-dev-292736139819.us-central1.run.app"
DEFAULT_PROJECT     = "simpletort-zadroga-dev"
DEFAULT_DATABASE    = "simpletort-dev"
DEFAULT_COLLECTION  = "notificationTemplates"
DELIVERY_COLLECTION = "sms_delivery_records"

TEST_VARIABLES = {
    "clientName": "E2E Test Client",
    "caseId":     "ZAD-E2E-001",
    "portalUrl":  "https://portal.zadroga.com/c/ZAD-E2E-001",
}

# ── Helpers ────────────────────────────────────────────────────────────────────

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

    # Method 2: google-auth with service account impersonation
    try:
        import google.auth
        import google.auth.transport.requests
        import google.oauth2.id_token

        # Works on GCP (Cloud Shell, Cloud Run, GCE)
        auth_req = google.auth.transport.requests.Request()
        token = google.oauth2.id_token.fetch_id_token(auth_req, audience)
        if token:
            return token
    except Exception:
        pass

    print("ERROR: Could not get identity token.")
    print("       Run: gcloud auth login")
    print("       Then: gcloud auth print-identity-token  (verify it works)")
    sys.exit(1)


def _check_template(project: str, database: str, collection: str) -> dict:
    """Fetch welcome-sms template from Firestore and validate it."""
    try:
        from google.cloud import firestore
    except ImportError:
        print("ERROR: pip install google-cloud-firestore")
        sys.exit(1)

    db = firestore.Client(project=project, database=database)
    doc = db.collection(collection).document("welcome-sms").get()

    if not doc.exists:
        print("FAIL  Template 'welcome-sms' not found in Firestore")
        print(f"      Collection: {collection}")
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

    # Check for unreplaced placeholders
    remaining = re.findall(r"\{\{(\w+)\}\}", rendered)
    if remaining:
        print(f"FAIL  Unreplaced variables in template: {remaining}")
        sys.exit(1)

    char_count = len(rendered)
    print(f"\nPASS  Template rendered successfully")
    print(f"      Char count   : {char_count} ({'✓ under 160' if char_count <= 160 else '✗ OVER 160'})")
    print(f"      Rendered SMS : {rendered}")
    return rendered


def _send_sms_request(
    service_url: str,
    token: str,
    to: str,
    request_id: str,
) -> dict:
    """POST to /tasks/sms and return the response body."""
    import urllib.request
    import urllib.error

    payload = {
        "to":         to,
        "templateId": "welcome-sms",
        "variables":  TEST_VARIABLES,
        "caseId":     TEST_VARIABLES["caseId"],
        "requestId":  request_id,
    }

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
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
            body = json.loads(resp.read())
            return body
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"FAIL  HTTP {e.code} from service: {body}")
        sys.exit(1)


def _check_delivery_record(
    project: str,
    database: str,
    delivery_id: str,
) -> None:
    """Verify Firestore delivery record was written correctly."""
    from google.cloud import firestore

    db = firestore.Client(project=project, database=database)
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

    status = data.get("status")
    if status == "sent":
        print(f"\nPASS  SMS delivered successfully ✓")
    elif status == "failed":
        print(f"\nWARN  SMS status is 'failed' — check Twilio console for error")
    elif status == "opted_out":
        print(f"\nWARN  Phone number is opted out — use a different test number")
    else:
        print(f"\nWARN  Unexpected status: {status}")


# ── Main ───────────────────────────────────────────────────────────────────────

def run_e2e(args: argparse.Namespace) -> None:
    print("=" * 60)
    print("  ZAD Notification — Welcome SMS E2E Test")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    # Step 1 — Check template in Firestore
    print("\n[1/4] Checking Firestore template…")
    template_data = _check_template(args.project, args.database, args.collection)

    # Step 2 — Render template locally (validate variables)
    print("\n[2/4] Rendering template with test variables…")
    _render_template(template_data.get("body", ""), TEST_VARIABLES)

    if args.dry_run:
        print("\n✓ Dry run complete — no SMS sent.")
        return

    # Step 3 — Send via deployed service
    print(f"\n[3/4] Sending SMS to {args.to}…")
    token      = _get_token(args.service_url)
    request_id = f"e2e-{int(time.time())}"
    response   = _send_sms_request(args.service_url, token, args.to, request_id)

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
    time.sleep(2)   # brief pause for write to propagate
    _check_delivery_record(args.project, args.database, delivery_id)

    # Summary
    print("\n" + "=" * 60)
    status = response.get("status")
    if status == "sent":
        print("  ✅  ALL CHECKS PASSED — Welcome SMS E2E test complete")
        print(f"      Check your phone: {args.to}")
        print(f"      Twilio Console  : https://console.twilio.com/us1/monitor/logs/sms")
        print(f"      Firestore record: sms_delivery_records/{delivery_id}")
    else:
        print(f"  ⚠️  SMS STATUS: {status} — review logs above")
    print("=" * 60)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="E2E test for welcome SMS flow")
    p.add_argument("--service-url", default=DEFAULT_SERVICE_URL)
    p.add_argument("--project",     default=DEFAULT_PROJECT)
    p.add_argument("--database",    default=DEFAULT_DATABASE)
    p.add_argument("--collection",  default=DEFAULT_COLLECTION)
    p.add_argument("--to",          default=None,
                   help="Destination phone number in E.164 format e.g. +12025550100")
    p.add_argument("--dry-run",     action="store_true",
                   help="Validate template locally without sending SMS")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if not args.dry_run and not args.to:
        print("ERROR: --to is required unless --dry-run is set")
        print("       Example: --to +12025550100")
        sys.exit(1)
    run_e2e(args)
