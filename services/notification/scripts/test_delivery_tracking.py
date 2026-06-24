#!/usr/bin/env python3
"""
scripts/test_delivery_tracking.py

Writes a sample notification delivery record to Firestore so you can
verify the schema at:
  Firestore Console → simpletort-dev → cases/{caseId}/notifications
  Firestore Console → simpletort-dev → notifications

Usage:
    python services/notification/scripts/test_delivery_tracking.py --case-id ZAD-2024-01-0001
"""
import argparse
import asyncio
import os
import sys
import uuid

SERVICE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, SERVICE_ROOT)

os.environ.setdefault("FIRESTORE_DATABASE_ID",              "simpletort-dev")
os.environ.setdefault("GCP_PROJECT_ID",                     "")
os.environ.setdefault("FIRESTORE_SMS_TEMPLATES_COLLECTION", "notificationTemplates")
os.environ.setdefault("SENDGRID_FROM_EMAIL",                "azad@plutusllp.com")
os.environ.setdefault("SENDGRID_FROM_NAME",                 "Zadroga Law")
os.environ.setdefault("TWILIO_ACCOUNT_SID",                 "ACplaceholder")
os.environ.setdefault("TWILIO_AUTH_TOKEN",                  "placeholder")
os.environ.setdefault("TWILIO_FROM_NUMBER",                 "+10000000000")
os.environ.setdefault("SENDGRID_API_KEY",                   "SG.placeholder")


async def run(case_id: str):
    from services.firestore_client import get_db
    from services.delivery_tracking_service import (
        CHANNEL_EMAIL, CHANNEL_SMS,
        STATUS_DELIVERED, STATUS_FAILED,
        write_notification_record,
    )

    db = get_db()

    print("=" * 60)
    print("  Delivery Tracking Schema — Firestore Seed Test")
    print("=" * 60)

    # ── Record 1: SMS sent + delivered ────────────────────────────
    sms_id = str(uuid.uuid4())
    print(f"\n[1/2] Writing SMS delivery record...")
    print(f"      notificationId : {sms_id}")
    print(f"      channel        : SMS")
    print(f"      status         : delivered")

    await write_notification_record(
        notification_id=sms_id,
        case_id=case_id,
        client_id="lead-john-doe-001",
        channel=CHANNEL_SMS,
        template_id="welcome_sms",
        status=STATUS_DELIVERED,
        request_id="test-seed-sms-001",
        sent_at="2026-04-09T08:00:00Z",
        delivered_at="2026-04-09T08:00:04Z",
        error_message=None,
        error_code=None,
        retry_count=0,
        provider_message_id="SMabc123def456",
        sms_segment_count=1,
        sms_char_count=122,
        twilio_status="delivered",
        db=db,
    )
    print(f"PASS  SMS record written")

    # ── Record 2: Email failed ─────────────────────────────────────
    email_id = str(uuid.uuid4())
    print(f"\n[2/2] Writing EMAIL delivery record...")
    print(f"      notificationId : {email_id}")
    print(f"      channel        : EMAIL")
    print(f"      status         : failed")

    await write_notification_record(
        notification_id=email_id,
        case_id=case_id,
        client_id="lead-john-doe-001",
        channel=CHANNEL_EMAIL,
        template_id="welcome_email",
        status=STATUS_FAILED,
        request_id="test-seed-email-001",
        sent_at="2026-04-09T08:05:00Z",
        delivered_at=None,
        error_message="HTTP Error 403: Forbidden",
        error_code=403,
        retry_count=1,
        provider_message_id=None,
        email_subject="Welcome to Zadroga Law, John Doe — Your Case ZAD-2024-01-0001",
        sendgrid_status_code=403,
        db=db,
    )
    print(f"PASS  Email record written")

    print(f"\n{'=' * 60}")
    print(f"  Records written to Firestore. Verify at:")
    print(f"")
    print(f"  Subcollection (per-case):")
    print(f"  https://console.cloud.google.com/firestore/databases/simpletort-dev/data/panel/cases/{case_id}/notifications?project={os.environ.get('GCP_PROJECT_ID', '<GCP_PROJECT_ID>')}")
    print(f"")
    print(f"  Top-level collection (cross-case):")
    print(f"  https://console.cloud.google.com/firestore/databases/simpletort-dev/data/panel/notifications?project={os.environ.get('GCP_PROJECT_ID', '<GCP_PROJECT_ID>')}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--case-id", required=True)
    args = p.parse_args()
    asyncio.run(run(args.case_id))
