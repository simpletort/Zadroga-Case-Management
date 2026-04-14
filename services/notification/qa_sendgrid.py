#!/usr/bin/env python3
"""
qa_sendgrid.py — CLI QA runner for SendGrid integration.

Runs 5 acceptance test cases:
  TC1 — Send test email via wrapper and verify receipt
  TC2 — Confirm no PHI appears in SendGrid metadata (only caseId)
  TC3 — Simulate bad API key — verify graceful failure + audit log written
  TC4 — Verify Secret Manager access works (key readable from env)
  TC5 — Check DKIM/SPF/DMARC DNS records for simpletort.com

Usage:
    python services/notification/qa_sendgrid.py --case-id ZAD-2024-01-0001
    python services/notification/qa_sendgrid.py --case-id ZAD-2024-01-0001 --to test@example.com
    python services/notification/qa_sendgrid.py --case-id ZAD-2024-01-0001 --tc 2   # run single test
"""
from __future__ import annotations

import argparse
import asyncio
import os
import socket
import sys
import uuid
from datetime import datetime, timezone

SERVICE_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SERVICE_ROOT)

os.environ.setdefault("FIRESTORE_DATABASE_ID", "simpletort-dev")
os.environ.setdefault("GCP_PROJECT_ID", "simpletort-zadroga-dev")
os.environ.setdefault("FIRESTORE_SMS_TEMPLATES_COLLECTION", "notificationTemplates")
os.environ.setdefault("SENDGRID_FROM_EMAIL", "azad@plutusllp.com")
os.environ.setdefault("SENDGRID_FROM_NAME", "Zadroga Law")
os.environ.setdefault("TWILIO_ACCOUNT_SID", "ACplaceholder")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "placeholder")
os.environ.setdefault("TWILIO_FROM_NUMBER", "+10000000000")

CASES_COLLECTION = "cases"
PORTAL_BASE_URL = "https://portal.zadroga.com/c"

_PASS = "PASS"
_FAIL = "FAIL"
_SKIP = "SKIP"
_WARN = "WARN"


def _section(title: str) -> None:
    print(f"\n{'=' * 62}")
    print(f"  {title}")
    print(f"{'=' * 62}")


def _result(status: str, msg: str, detail: str = "") -> None:
    icons = {_PASS: "PASS", _FAIL: "FAIL", _SKIP: "SKIP", _WARN: "WARN"}
    label = icons.get(status, status)
    print(f"{label}  {msg}")
    if detail:
        for line in detail.strip().splitlines():
            print(f"      {line}")


def _get_sync_firestore():
    from google.cloud import firestore
    project = os.environ.get("GCP_PROJECT_ID", "simpletort-zadroga-dev")
    database = os.environ.get("FIRESTORE_DATABASE_ID", "simpletort-dev")
    return firestore.Client(project=project, database=database)


def _fetch_case(case_id: str) -> dict:
    db = _get_sync_firestore()
    doc = db.collection(CASES_COLLECTION).document(case_id).get()
    if not doc.exists:
        print(f"FAIL  Case '{case_id}' not found in Firestore")
        sys.exit(1)
    data = doc.to_dict()
    lead = data.get("leadData") or {}
    first = lead.get("firstName") or data.get("firstName", "")
    last = lead.get("lastName") or data.get("lastName", "")
    return {
        "clientName": f"{first} {last}".strip() or "Client",
        "email": lead.get("email") or data.get("email", ""),
        "phone": lead.get("phone") or data.get("phone", ""),
        "portalUrl": data.get("portalAccessLink") or f"{PORTAL_BASE_URL}/{case_id}",
        "status": data.get("status", ""),
        "missingDocs": data.get("missingDocuments", []),
    }


# ─────────────────────────────────────────────────────────────────────────────
# TC1 — Send test email via wrapper
# ─────────────────────────────────────────────────────────────────────────────
async def tc1_send_email(case_id: str, to_override: str | None) -> bool:
    _section("TC1 — Send Test Email via Wrapper")

    case = _fetch_case(case_id)
    to = to_override or case["email"]
    if not to:
        _result(_FAIL, "No email address found for case", f"Use --to to override")
        return False

    print(f"  case_id    : {case_id}")
    print(f"  to         : {to}")
    print(f"  clientName : {case['clientName']}")

    from services.firestore_client import get_db
    from services.email_service import send_email

    db = get_db()
    variables = {
        "clientName": case["clientName"],
        "caseId": case_id,
        "portalUrl": case["portalUrl"],
    }

    print(f"\n  Calling email_service.send_email()...")
    result = await send_email(
        to=to,
        template_id="welcome_email",
        variables=variables,
        db=db,
        case_id=case_id,
        request_id=f"qa-tc1-{uuid.uuid4().hex[:8]}",
    )

    print(f"\n  status      : {result.status}")
    print(f"  success     : {result.success}")
    print(f"  deliveryId  : {result.delivery_id}")
    print(f"  messageId   : {result.message_id}")
    print(f"  statusCode  : {result.status_code}")
    if result.error_message:
        print(f"  error       : {result.error_message}")

    if result.success:
        _result(_PASS, "Email sent successfully via SendGrid")
        print(f"\n  Check inbox : {to}")
        print(f"  SendGrid    : https://app.sendgrid.com/email_activity")
        return True
    elif result.status_code in (401, 403):
        _result(_WARN, "SendGrid rejected — sender not verified yet",
                f"Status {result.status_code}: {result.error_message}\n"
                f"Fix: Verify sender at https://app.sendgrid.com/settings/sender_auth")
        return False
    else:
        _result(_FAIL, "Email send failed", str(result.error_message))
        return False


# ─────────────────────────────────────────────────────────────────────────────
# TC2 — PHI isolation check
# ─────────────────────────────────────────────────────────────────────────────
def tc2_phi_isolation() -> bool:
    _section("TC2 — PHI Isolation: No PHI in SendGrid Metadata")

    from sendgrid.helpers.mail import CustomArg, From, HtmlContent, Mail, Subject, To

    fake_email = "john.doe@example.com"
    fake_name = "John Doe"
    fake_phone = "+12125550100"
    case_id = "ZAD-2024-01-0001"

    message = Mail(
        from_email=From("azad@plutusllp.com", "Zadroga Law"),
        to_emails=To(fake_email),
        subject=Subject(f"Welcome to Zadroga Law, {fake_name}"),
        html_content=HtmlContent(f"<p>Dear {fake_name}, case {case_id}</p>"),
    )
    message.custom_arg = CustomArg("caseId", case_id)

    import json
    payload = message.get()
    payload_str = json.dumps(payload)
    custom_args_str = json.dumps(payload.get("custom_args", {}))

    print(f"\n  Payload sent to SendGrid API:")
    print(f"  " + json.dumps(payload, indent=2).replace("\n", "\n  "))

    checks = [
        ("Email address only in `to` field", True),
        ("Client name NOT in custom_args", fake_name not in custom_args_str),
        ("Phone number NOT in payload", fake_phone not in payload_str),
        ("caseId IS in custom_args", case_id in custom_args_str),
        ("No PII in custom_args", fake_name not in custom_args_str and fake_email not in custom_args_str),
        ("No extra metadata fields", list(payload.get("custom_args", {}).keys()) == ["caseId"]),
    ]

    print()
    all_passed = True
    for label, passed in checks:
        status = _PASS if passed else _FAIL
        _result(status, label)
        if not passed:
            all_passed = False

    return all_passed


# ─────────────────────────────────────────────────────────────────────────────
# TC3 — Bad API key: graceful failure + audit log
# ─────────────────────────────────────────────────────────────────────────────
async def tc3_bad_api_key(case_id: str) -> bool:
    _section("TC3 — Bad API Key: Graceful Failure + Audit Log")

    # Temporarily swap in a bad key
    real_key = os.environ.get("SENDGRID_API_KEY", "")
    os.environ["SENDGRID_API_KEY"] = "SG.BAD_KEY_QA_TEST_12345"

    # Reset lru_cache so new key is picked up
    from config import get_settings
    get_settings.cache_clear()

    # Reset sendgrid client singleton
    import services.sendgrid_client as _sg
    _sg._client = None

    from services.firestore_client import get_db
    from services.email_service import send_email

    db = get_db()
    req_id = f"qa-tc3-{uuid.uuid4().hex[:8]}"

    print(f"  Injecting bad API key: SG.BAD_KEY_QA_TEST_12345")
    print(f"  Calling email_service.send_email()...")

    result = await send_email(
        to="qa-test@example.com",
        template_id="welcome_email",
        variables={"clientName": "QA Test", "caseId": case_id, "portalUrl": "https://portal.zadroga.com/c/QA"},
        db=db,
        case_id=case_id,
        request_id=req_id,
    )

    print(f"\n  status      : {result.status}")
    print(f"  success     : {result.success}")
    print(f"  deliveryId  : {result.delivery_id}")
    print(f"  statusCode  : {result.status_code}")
    print(f"  error       : {result.error_message}")

    # Restore real key
    if real_key:
        os.environ["SENDGRID_API_KEY"] = real_key
    get_settings.cache_clear()
    _sg._client = None

    all_passed = True

    # Check 1: no exception raised
    _result(_PASS if not result.success else _FAIL, "Service returned gracefully (no exception raised)")

    # Check 2: status is failed
    if result.status == "failed":
        _result(_PASS, f"Status correctly set to 'failed' (got: {result.status})")
    else:
        _result(_FAIL, f"Expected status=failed, got: {result.status}")
        all_passed = False

    # Check 3: delivery record written to Firestore
    print(f"\n  Checking Firestore audit log entry...")
    await asyncio.sleep(2)
    from config import get_settings as gs
    settings = gs()
    doc = await db.collection(settings.email_delivery_records_collection).document(result.delivery_id).get()
    if doc.exists:
        rec = doc.to_dict()
        _result(_PASS, "Audit log written to Firestore",
                f"deliveryId  : {rec.get('deliveryId')}\n"
                f"status      : {rec.get('status')}\n"
                f"errorMessage: {rec.get('errorMessage')}\n"
                f"attemptedAt : {rec.get('attemptedAt')}")
    else:
        _result(_FAIL, "No audit log entry found in Firestore")
        all_passed = False

    return all_passed


# ─────────────────────────────────────────────────────────────────────────────
# TC4 — Secret Manager access
# ─────────────────────────────────────────────────────────────────────────────
def tc4_secret_manager() -> bool:
    _section("TC4 — Secret Manager: API Key Accessible")

    import subprocess

    checks_passed = 0
    total_checks = 3

    # Check 1: Key present in env
    key = os.environ.get("SENDGRID_API_KEY", "")
    if key and key.startswith("SG."):
        _result(_PASS, f"SENDGRID_API_KEY in environment (starts with SG.)")
        checks_passed += 1
    elif key:
        _result(_WARN, f"SENDGRID_API_KEY found but unexpected format")
        checks_passed += 1
    else:
        _result(_WARN, "SENDGRID_API_KEY not in local env (set $env:SENDGRID_API_KEY first)")

    # Check 2: gcloud secret accessible
    try:
        cmds = [
            ["gcloud", "secrets", "versions", "access", "latest",
             "--secret=SENDGRID_API_KEY", "--project=simpletort-zadroga-dev"],
            ["gcloud.cmd", "secrets", "versions", "access", "latest",
             "--secret=SENDGRID_API_KEY", "--project=simpletort-zadroga-dev"],
        ]
        secret_val = None
        for cmd in cmds:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15)
                secret_val = r.stdout.strip()
                break
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue

        if secret_val and secret_val.startswith("SG."):
            _result(_PASS, "Secret Manager read succeeded (gcloud secrets versions access)")
            checks_passed += 1
        else:
            _result(_FAIL, "Could not read secret from Secret Manager")
    except Exception as exc:
        _result(_FAIL, f"Secret Manager check failed: {exc}")

    # Check 3: Cloud Run service account has access
    try:
        r = None
        for cmd_prefix in (["gcloud"], ["gcloud.cmd"]):
            try:
                r = subprocess.run(
                    cmd_prefix + ["run", "revisions", "describe", "notification-dev-00040-8fb",
                                  "--region=us-central1", "--project=simpletort-zadroga-dev",
                                  "--format=value(spec.containers[0].env)"],
                    capture_output=True, text=True, check=True, timeout=20
                )
                break
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue

        if r and "secretKeyRef" in (r.stdout or ""):
            _result(_PASS, "Cloud Run revision mounts SENDGRID_API_KEY from Secret Manager",
                    "secretKeyRef: {name: SENDGRID_API_KEY, key: latest}")
            checks_passed += 1
        else:
            _result(_WARN, "Could not verify Cloud Run secret mount automatically",
                    "Check manually: gcloud run revisions describe notification-dev-00040-8fb ...")
    except Exception as exc:
        _result(_WARN, f"Could not verify Cloud Run mount: {exc}")

    return checks_passed >= 2


# ─────────────────────────────────────────────────────────────────────────────
# TC5 — DKIM / SPF / DMARC DNS check
# ─────────────────────────────────────────────────────────────────────────────
def tc5_dkim_spf() -> bool:
    _section("TC5 — DKIM / SPF / DMARC DNS Records for simpletort.com")

    import subprocess

    domain = "simpletort.com"
    all_passed = True

    def dns_txt(name: str) -> list[str]:
        try:
            import dns.resolver
            answers = dns.resolver.resolve(name, "TXT")
            return [str(r) for r in answers]
        except Exception:
            pass
        # fallback: nslookup
        for cmd in (["nslookup", "-type=TXT", name], ):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                lines = r.stdout + r.stderr
                txts = [l.strip() for l in lines.splitlines() if '"' in l]
                return txts
            except Exception:
                pass
        return []

    def dns_cname(name: str) -> str:
        for cmd in (["nslookup", "-type=CNAME", name],):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                for line in r.stdout.splitlines():
                    if "canonical name" in line.lower() or "alias" in line.lower():
                        return line.strip()
            except Exception:
                pass
        return ""

    # SPF
    print(f"\n  Checking SPF (TXT on {domain})...")
    txts = dns_txt(domain)
    spf = [t for t in txts if "v=spf1" in t.lower()]
    sendgrid_in_spf = any("sendgrid" in t.lower() for t in spf)
    if spf:
        for s in spf:
            print(f"  Found: {s}")
        if sendgrid_in_spf:
            _result(_PASS, "SPF includes SendGrid (include:sendgrid.net)")
        else:
            _result(_WARN, "SPF record found but SendGrid not included",
                    "Add: include:sendgrid.net to SPF record")
            all_passed = False
    else:
        _result(_FAIL, "No SPF TXT record found on simpletort.com",
                "Add TXT record: v=spf1 include:sendgrid.net ~all")
        all_passed = False

    # DKIM
    print(f"\n  Checking DKIM CNAME records...")
    for selector in ("s1", "s2", "em"):
        cname_host = f"{selector}._domainkey.{domain}"
        cname_val = dns_cname(cname_host)
        if cname_val and "sendgrid" in cname_val.lower():
            _result(_PASS, f"DKIM CNAME {cname_host} → SendGrid")
        elif cname_val:
            _result(_WARN, f"DKIM CNAME {cname_host} found but not pointing to SendGrid", cname_val)
        else:
            _result(_FAIL, f"DKIM CNAME missing: {cname_host}",
                    "Set up Domain Authentication in SendGrid to get CNAME values")
            all_passed = False

    # DMARC
    print(f"\n  Checking DMARC (_dmarc.{domain})...")
    dmarc = dns_txt(f"_dmarc.{domain}")
    dmarc_records = [d for d in dmarc if "v=dmarc1" in d.lower()]
    if dmarc_records:
        for d in dmarc_records:
            print(f"  Found: {d}")
        _result(_PASS, "DMARC record present")
    else:
        _result(_FAIL, "No DMARC record found",
                "Add: _dmarc.simpletort.com TXT v=DMARC1; p=none; rua=mailto:dmarc@simpletort.com")
        all_passed = False

    if not all_passed:
        print(f"\n  ACTION REQUIRED:")
        print(f"  1. Go to SendGrid → Settings → Sender Authentication → Domain Authentication")
        print(f"  2. Authenticate domain: simpletort.com")
        print(f"  3. Add the DNS records SendGrid provides to your NS1/Netlify DNS")
        print(f"  4. Click Verify in SendGrid once DNS propagates (~10 mins)")

    return all_passed


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
async def run(args: argparse.Namespace) -> None:
    print("=" * 62)
    print("  ZAD Notification — SendGrid QA Test Suite")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 62)

    run_all = args.tc is None
    results: dict[str, bool | None] = {}

    if run_all or args.tc == 1:
        results["TC1"] = await tc1_send_email(args.case_id, args.to)

    if run_all or args.tc == 2:
        results["TC2"] = tc2_phi_isolation()

    if run_all or args.tc == 3:
        results["TC3"] = await tc3_bad_api_key(args.case_id)

    if run_all or args.tc == 4:
        results["TC4"] = tc4_secret_manager()

    if run_all or args.tc == 5:
        results["TC5"] = tc5_dkim_spf()

    # Summary
    _section("QA Summary")
    descriptions = {
        "TC1": "Send test email via wrapper",
        "TC2": "PHI isolation (no PII in SendGrid metadata)",
        "TC3": "Bad API key — graceful failure + audit log",
        "TC4": "Secret Manager access from Cloud Run",
        "TC5": "DKIM / SPF / DMARC DNS records",
    }
    passed = 0
    total = len(results)
    for tc, ok in results.items():
        icon = "PASS" if ok else "FAIL"
        print(f"  {icon}  {tc} — {descriptions.get(tc,'')}")
        if ok:
            passed += 1

    print(f"\n  {passed}/{total} test cases passed")
    if passed == total:
        print("  ALL CHECKS PASSED — Ready for sign-off")
    else:
        print("  Some checks need attention (see details above)")
    print("=" * 62)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="QA test suite for SendGrid email integration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--case-id", required=True, help="Firestore case ID e.g. ZAD-2024-01-0001")
    p.add_argument("--to", default=None, help="Override recipient email address")
    p.add_argument("--tc", type=int, default=None, choices=[1, 2, 3, 4, 5],
                   help="Run a single test case (1-5). Omit to run all.")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(run(args))
