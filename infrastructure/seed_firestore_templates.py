#!/usr/bin/env python3
"""
infrastructure/seed_firestore_templates.py
==========================================
Seeds the Firestore ``notification_templates`` collection with the initial
set of templates used by the ZAD Notification Service.

Templates seeded
----------------
  welcome-sms          — SMS sent immediately on new lead creation
  welcome-email        — Email sent immediately on new lead creation
  reminder-48hr-sms    — SMS reminder 48 hours before appointment
  reminder-48hr-email  — Email reminder 48 hours before appointment
  reminder-7day-sms    — SMS reminder 7 days after no contact
  reminder-7day-email  — Email reminder 7 days after no contact

Usage
-----
  # Authenticate first (ADC)
  gcloud auth application-default login

  # Seed dev project (dry-run first)
  python infrastructure/seed_firestore_templates.py --project simpletort-zadroga-dev --dry-run
  python infrastructure/seed_firestore_templates.py --project simpletort-zadroga-dev

  # Seed production project
  python infrastructure/seed_firestore_templates.py --project simpletort-prod

  # Force overwrite existing templates
  python infrastructure/seed_firestore_templates.py --project simpletort-prod --overwrite

Environment variables (alternative to --project)
-------------------------------------------------
  GOOGLE_CLOUD_PROJECT   — GCP project ID

Options
-------
  --project PROJECT      GCP project ID (required if env var not set)
  --collection NAME      Firestore collection name (default: notification_templates)
  --dry-run              Print what would be written without writing
  --overwrite            Overwrite existing template documents (default: skip)
  --template-id ID       Seed only the specified template ID
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# ── Template definitions ───────────────────────────────────────────────────────
# All placeholders use {{double-brace}} syntax.
# Fields:
#   templateId   — Firestore document ID (snake_case)
#   name         — Human-readable label
#   channel      — "SMS" | "EMAIL" | "BOTH"
#   triggerEvent — event that triggers this template
#   body         — Plain-text SMS body ({{placeholders}})
#   subject      — Email subject line ({{placeholders}})
#   htmlBody     — HTML email body ({{placeholders}})
#   isActive     — bool; False disables dispatch
#   createdBy    — who seeded this record

TEMPLATES: list[dict] = [
    # ── Welcome SMS ────────────────────────────────────────────────────────────
    {
        "templateId": "welcome-sms",
        "name": "Welcome SMS",
        "channel": "SMS",
        "triggerEvent": "new_lead_created",
        "body": (
            "Hi {{clientName}}, thank you for contacting us about your Zadroga "
            "Act claim. Your case {{caseId}} has been received. A team member "
            "will contact you within 24 hours. Reply STOP to opt out."
        ),
        "subject": "",
        "htmlBody": "",
        "isActive": True,
    },

    # ── Welcome Email ──────────────────────────────────────────────────────────
    {
        "templateId": "welcome-email",
        "name": "Welcome Email",
        "channel": "EMAIL",
        "triggerEvent": "new_lead_created",
        "body": (
            "Hi {{clientName}},\n\n"
            "Thank you for reaching out about your Zadroga Act claim. "
            "We have received your information and assigned case number {{caseId}} "
            "to your file.\n\n"
            "One of our team members will contact you within 24 business hours "
            "to discuss the next steps.\n\n"
            "If you have immediate questions, please reply to this email or call "
            "our office.\n\n"
            "Sincerely,\n"
            "The Zadroga Case Management Team"
        ),
        "subject": "Your Zadroga Act Claim — Case {{caseId}} Received",
        "htmlBody": (
            "<p>Hi {{clientName}},</p>"
            "<p>Thank you for reaching out about your Zadroga Act claim. "
            "We have received your information and assigned case number "
            "<strong>{{caseId}}</strong> to your file.</p>"
            "<p>One of our team members will contact you within 24 business hours "
            "to discuss the next steps.</p>"
            "<p>If you have immediate questions, please reply to this email or "
            "call our office.</p>"
            "<p>Sincerely,<br>The Zadroga Case Management Team</p>"
        ),
        "isActive": True,
    },

    # ── 48-Hour Reminder SMS ───────────────────────────────────────────────────
    {
        "templateId": "reminder-48hr-sms",
        "name": "48-Hour Appointment Reminder SMS",
        "channel": "SMS",
        "triggerEvent": "appointment_reminder_48hr",
        "body": (
            "Hi {{clientName}}, this is a reminder that your Zadroga claim "
            "consultation is scheduled for {{appointmentDate}} at {{appointmentTime}}. "
            "Case: {{caseId}}. Reply STOP to opt out."
        ),
        "subject": "",
        "htmlBody": "",
        "isActive": True,
    },

    # ── 48-Hour Reminder Email ─────────────────────────────────────────────────
    {
        "templateId": "reminder-48hr-email",
        "name": "48-Hour Appointment Reminder Email",
        "channel": "EMAIL",
        "triggerEvent": "appointment_reminder_48hr",
        "body": (
            "Hi {{clientName}},\n\n"
            "This is a reminder that your Zadroga Act claim consultation is "
            "scheduled for {{appointmentDate}} at {{appointmentTime}}.\n\n"
            "Case number: {{caseId}}\n"
            "Location / call-in details: {{appointmentLocation}}\n\n"
            "Please contact us if you need to reschedule.\n\n"
            "Sincerely,\n"
            "The Zadroga Case Management Team"
        ),
        "subject": "Reminder: Zadroga Claim Consultation on {{appointmentDate}} — Case {{caseId}}",
        "htmlBody": (
            "<p>Hi {{clientName}},</p>"
            "<p>This is a reminder that your Zadroga Act claim consultation is "
            "scheduled for <strong>{{appointmentDate}}</strong> at "
            "<strong>{{appointmentTime}}</strong>.</p>"
            "<ul>"
            "<li><strong>Case number:</strong> {{caseId}}</li>"
            "<li><strong>Location / call-in:</strong> {{appointmentLocation}}</li>"
            "</ul>"
            "<p>Please <a href='mailto:{{contactEmail}}'>contact us</a> if you "
            "need to reschedule.</p>"
            "<p>Sincerely,<br>The Zadroga Case Management Team</p>"
        ),
        "isActive": True,
    },

    # ── 7-Day Follow-Up SMS ────────────────────────────────────────────────────
    {
        "templateId": "reminder-7day-sms",
        "name": "7-Day Follow-Up SMS",
        "channel": "SMS",
        "triggerEvent": "follow_up_7day",
        "body": (
            "Hi {{clientName}}, we wanted to follow up on your Zadroga Act claim "
            "(case {{caseId}}). Please call us or reply to this message so we can "
            "assist you. Reply STOP to opt out."
        ),
        "subject": "",
        "htmlBody": "",
        "isActive": True,
    },

    # ── 7-Day Follow-Up Email ──────────────────────────────────────────────────
    {
        "templateId": "reminder-7day-email",
        "name": "7-Day Follow-Up Email",
        "channel": "EMAIL",
        "triggerEvent": "follow_up_7day",
        "body": (
            "Hi {{clientName}},\n\n"
            "We wanted to follow up regarding your Zadroga Act claim (case {{caseId}}) "
            "that was submitted on {{submittedDate}}.\n\n"
            "We have been unable to reach you and want to make sure you have all "
            "the support you need. Please contact us at your earliest convenience "
            "so we can move forward with your case.\n\n"
            "You can reply to this email, call our office, or visit our website.\n\n"
            "Sincerely,\n"
            "The Zadroga Case Management Team"
        ),
        "subject": "Following Up on Your Zadroga Act Claim — Case {{caseId}}",
        "htmlBody": (
            "<p>Hi {{clientName}},</p>"
            "<p>We wanted to follow up regarding your Zadroga Act claim "
            "(case <strong>{{caseId}}</strong>) submitted on {{submittedDate}}.</p>"
            "<p>We have been unable to reach you and want to make sure you have "
            "all the support you need. Please contact us at your earliest "
            "convenience so we can move forward with your case.</p>"
            "<p>You can reply to this email, call our office, or visit our website.</p>"
            "<p>Sincerely,<br>The Zadroga Case Management Team</p>"
        ),
        "isActive": True,
    },
]


# ── Seeder logic ───────────────────────────────────────────────────────────────

def _build_doc(template: dict, now_iso: str) -> dict:
    """Return the Firestore document dict for a template, adding timestamps."""
    doc = {k: v for k, v in template.items() if k != "templateId"}
    doc["createdBy"] = "seed_script"
    doc["createdAt"] = now_iso
    doc["updatedAt"] = now_iso
    return doc


def seed_templates(
    project: str,
    collection: str,
    database: str,
    dry_run: bool,
    overwrite: bool,
    only_id: str | None,
) -> None:
    """Write template documents to Firestore."""
    try:
        from google.cloud import firestore
    except ImportError:
        print("ERROR: google-cloud-firestore is not installed.")
        print("       Run: pip install google-cloud-firestore")
        sys.exit(1)

    db = firestore.Client(project=project, database=database)
    now_iso = datetime.now(timezone.utc).isoformat()

    templates_to_seed = [
        t for t in TEMPLATES
        if only_id is None or t["templateId"] == only_id
    ]

    if not templates_to_seed:
        print(f"No templates matched template-id filter '{only_id}'")
        sys.exit(1)

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Seeding {len(templates_to_seed)} "
          f"template(s) → {project}/{collection}\n")

    skipped = 0
    written = 0

    for template in templates_to_seed:
        template_id = template["templateId"]
        doc_ref = db.collection(collection).document(template_id)

        if not dry_run and not overwrite:
            snap = doc_ref.get()
            if snap.exists:
                print(f"  SKIP  {template_id}  (already exists — use --overwrite to replace)")
                skipped += 1
                continue

        doc_data = _build_doc(template, now_iso)

        if dry_run:
            print(f"  WOULD WRITE  {template_id}")
            print(f"    channel      : {template.get('channel')}")
            print(f"    triggerEvent : {template.get('triggerEvent')}")
            print(f"    body preview : {template.get('body', '')[:80]}…")
            print()
        else:
            if overwrite:
                doc_ref.set(doc_data)
            else:
                doc_ref.set(doc_data)
            print(f"  WROTE  {template_id}")
            written += 1

    print()
    if dry_run:
        print(f"Dry run complete — {len(templates_to_seed)} template(s) would be written.")
    else:
        print(f"Done — {written} written, {skipped} skipped.")


# ── CLI ────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed Firestore notification_templates collection.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--project",
        default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
        help="GCP project ID (or set GOOGLE_CLOUD_PROJECT env var)",
    )
    parser.add_argument(
        "--collection",
        default="notificationTemplates",
        help="Firestore collection name (default: notificationTemplates)",
    )
    parser.add_argument(
        "--database",
        default="(default)",
        help="Firestore database name (default: '(default)'). Use named DB e.g. 'simpletort-dev'",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without writing anything",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing template documents (default: skip existing)",
    )
    parser.add_argument(
        "--template-id",
        default=None,
        metavar="ID",
        help="Seed only this specific template ID",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all template IDs defined in this script and exit",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.list:
        print("Defined template IDs:")
        for t in TEMPLATES:
            print(f"  {t['templateId']:<30}  channel={t['channel']:<6}  "
                  f"event={t['triggerEvent']}")
        return

    if not args.project:
        print("ERROR: --project is required (or set GOOGLE_CLOUD_PROJECT env var).")
        sys.exit(1)

    seed_templates(
        project=args.project,
        collection=args.collection,
        database=args.database,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
        only_id=args.template_id,
    )


if __name__ == "__main__":
    main()
