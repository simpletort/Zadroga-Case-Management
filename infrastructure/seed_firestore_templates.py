#!/usr/bin/env python3
"""
infrastructure/seed_firestore_templates.py
==========================================
Seeds the Firestore ``notification_templates`` collection with the initial
set of templates used by the ZAD Notification Service.

Templates seeded
----------------
  welcome_sms          — SMS sent immediately on new lead creation
  welcome_email        — Email sent immediately on new lead creation
  reminder_48hr_sms    — SMS reminder 48 hours before document submission deadline
  reminder_48hr_email  — Email reminder 48 hours before document submission deadline
  reminder_7day_sms    — SMS escalation 7 days after documents are overdue
  reminder_7day_email  — Email escalation 7 days after documents are overdue

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
    # Variables: clientName, caseId, portalUrl
    # Char count (with typical values): ~155 — stays within 1 GSM-7 segment (160)
    {
        "templateId": "welcome_sms",
        "name": "Welcome SMS",
        "channel": "SMS",
        "triggerEvent": "new_lead_created",
        "variables": ["clientName", "caseId", "portalUrl"],
        "body": (
            "Hi {{clientName}}, your Zadroga Act claim {{caseId}} has been "
            "received. View your portal: {{portalUrl}} "
            "Reply STOP to opt out."
        ),
        "subject": "",
        "htmlBody": "",
        "isActive": True,
    },

    # ── Welcome Email ──────────────────────────────────────────────────────────
    # Variables: clientName, caseId, portalUrl
    {
        "templateId": "welcome_email",
        "name": "Welcome Email",
        "channel": "EMAIL",
        "triggerEvent": "new_lead_created",
        "variables": ["clientName", "caseId", "portalUrl"],
        "body": (
            "Hi {{clientName}},\n\n"
            "Thank you for reaching out about your Zadroga Act claim. "
            "We have received your information and assigned case number "
            "{{caseId}} to your file.\n\n"
            "You can track your case and upload documents through your "
            "secure client portal:\n"
            "{{portalUrl}}\n\n"
            "One of our team members will contact you within 24 business "
            "hours to discuss the next steps.\n\n"
            "If you have immediate questions, please reply to this email "
            "or call our office.\n\n"
            "Sincerely,\n"
            "The Zadroga Case Management Team"
        ),
        "subject": "Your Zadroga Act Claim — Case {{caseId}} Received",
        "htmlBody": (
            "<!DOCTYPE html>"
            "<html><body style='font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto;padding:20px'>"
            "<h2 style='color:#1a3c6b'>Your Zadroga Act Claim Has Been Received</h2>"
            "<p>Hi {{clientName}},</p>"
            "<p>Thank you for reaching out about your Zadroga Act claim. "
            "We have received your information and assigned case number "
            "<strong>{{caseId}}</strong> to your file.</p>"
            "<p>You can track your case status and securely upload documents "
            "through your client portal:</p>"
            "<p style='text-align:center;margin:24px 0'>"
            "<a href='{{portalUrl}}' "
            "style='background:#1a3c6b;color:#fff;padding:12px 28px;"
            "border-radius:4px;text-decoration:none;font-weight:bold'>"
            "Access Your Portal</a></p>"
            "<p>One of our team members will contact you within "
            "<strong>24 business hours</strong> to discuss the next steps.</p>"
            "<p>If you have immediate questions, please reply to this email "
            "or call our office.</p>"
            "<hr style='border:none;border-top:1px solid #eee;margin:24px 0'>"
            "<p style='font-size:12px;color:#888'>"
            "The Zadroga Case Management Team<br>"
            "This message was sent regarding case {{caseId}}. "
            "If you did not submit a claim, please disregard this email.</p>"
            "</body></html>"
        ),
        "isActive": True,
    },

    # ── 48-Hour Document Reminder SMS ─────────────────────────────────────────
    # Variables: clientName, caseId, missingDocsList, portalUrl, deadline
    # Tone: friendly but firm — documents due in 48 hours
    # Note: missingDocsList may push this over 160 chars (multi-segment SMS)
    {
        "templateId": "reminder_48hr_sms",
        "name": "48-Hour Document Reminder SMS",
        "channel": "SMS",
        "triggerEvent": "document_reminder_48hr",
        "variables": ["clientName", "caseId", "missingDocsList", "portalUrl", "deadline"],
        "body": (
            "Hi {{clientName}}, your Zadroga claim {{caseId}} is missing required "
            "documents: {{missingDocsList}}. Please upload by {{deadline}} at "
            "{{portalUrl}} Reply STOP to opt out."
        ),
        "subject": "",
        "htmlBody": "",
        "isActive": True,
    },

    # ── 48-Hour Document Reminder Email ───────────────────────────────────────
    # Variables: clientName, caseId, missingDocsList, portalUrl, deadline
    # Tone: professional and helpful — clear action required
    {
        "templateId": "reminder_48hr_email",
        "name": "48-Hour Document Reminder Email",
        "channel": "EMAIL",
        "triggerEvent": "document_reminder_48hr",
        "variables": ["clientName", "caseId", "missingDocsList", "portalUrl", "deadline"],
        "body": (
            "Hi {{clientName}},\n\n"
            "This is a reminder that your Zadroga Act claim (case {{caseId}}) "
            "requires the following documents to proceed:\n\n"
            "{{missingDocsList}}\n\n"
            "Please upload these documents through your secure client portal "
            "by {{deadline}}:\n"
            "{{portalUrl}}\n\n"
            "Submitting your documents on time ensures there are no delays in "
            "processing your claim. If you have trouble uploading or need "
            "assistance, please contact our office right away.\n\n"
            "Sincerely,\n"
            "The Zadroga Case Management Team"
        ),
        "subject": "Action Required: Documents Needed for Case {{caseId}} — Due {{deadline}}",
        "htmlBody": (
            "<!DOCTYPE html>"
            "<html><body style='font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto;padding:20px'>"
            "<h2 style='color:#1a3c6b'>Action Required: Documents Needed</h2>"
            "<p>Hi {{clientName}},</p>"
            "<p>Your Zadroga Act claim (<strong>{{caseId}}</strong>) requires the "
            "following documents to proceed:</p>"
            "<div style='background:#fff8e1;border-left:4px solid #f59e0b;padding:12px 16px;margin:16px 0'>"
            "<p style='margin:0;font-weight:bold;color:#92400e'>Missing Documents:</p>"
            "<p style='margin:8px 0 0;white-space:pre-line'>{{missingDocsList}}</p>"
            "</div>"
            "<p><strong>Deadline: {{deadline}}</strong></p>"
            "<p>Please upload your documents through your secure client portal:</p>"
            "<p style='text-align:center;margin:24px 0'>"
            "<a href='{{portalUrl}}' "
            "style='background:#1a3c6b;color:#fff;padding:12px 28px;"
            "border-radius:4px;text-decoration:none;font-weight:bold'>"
            "Upload Documents Now</a></p>"
            "<p>Submitting on time ensures there are no delays in processing "
            "your claim. If you need assistance, please contact our office.</p>"
            "<hr style='border:none;border-top:1px solid #eee;margin:24px 0'>"
            "<p style='font-size:12px;color:#888'>"
            "The Zadroga Case Management Team<br>"
            "This message was sent regarding case {{caseId}}.</p>"
            "</body></html>"
        ),
        "isActive": True,
    },

    # ── 7-Day Overdue Document Reminder SMS ───────────────────────────────────
    # Variables: clientName, caseId, missingDocsList, portalUrl
    # Tone: escalation — urgent, case may be affected
    {
        "templateId": "reminder_7day_sms",
        "name": "7-Day Overdue Document Reminder SMS",
        "channel": "SMS",
        "triggerEvent": "document_reminder_7day",
        "variables": ["clientName", "caseId", "missingDocsList", "portalUrl"],
        "body": (
            "URGENT — {{clientName}}, your Zadroga claim {{caseId}} is overdue "
            "for: {{missingDocsList}}. Upload now to avoid delays: {{portalUrl}} "
            "Reply STOP to opt out."
        ),
        "subject": "",
        "htmlBody": "",
        "isActive": True,
    },

    # ── 7-Day Overdue Document Reminder Email ─────────────────────────────────
    # Variables: clientName, caseId, missingDocsList, portalUrl
    # Tone: escalation — firm, immediate action required, case at risk
    {
        "templateId": "reminder_7day_email",
        "name": "7-Day Overdue Document Reminder Email",
        "channel": "EMAIL",
        "triggerEvent": "document_reminder_7day",
        "variables": ["clientName", "caseId", "missingDocsList", "portalUrl"],
        "body": (
            "Hi {{clientName}},\n\n"
            "IMPORTANT: Your Zadroga Act claim (case {{caseId}}) is now overdue "
            "for required document submissions. Despite our previous reminder, "
            "the following documents have not yet been received:\n\n"
            "{{missingDocsList}}\n\n"
            "Please be advised that failure to submit the required documents may "
            "result in delays or jeopardize the processing of your claim. "
            "Immediate action is required.\n\n"
            "Please upload your documents now through your secure client portal:\n"
            "{{portalUrl}}\n\n"
            "If you are experiencing difficulties or have already submitted these "
            "documents, please contact our office immediately so we can update "
            "your file.\n\n"
            "Sincerely,\n"
            "The Zadroga Case Management Team"
        ),
        "subject": "URGENT: Overdue Documents Required for Case {{caseId}} — Immediate Action Needed",
        "htmlBody": (
            "<!DOCTYPE html>"
            "<html><body style='font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto;padding:20px'>"
            "<h2 style='color:#b91c1c'>Urgent: Overdue Documents Required</h2>"
            "<p>Hi {{clientName}},</p>"
            "<p><strong>Your Zadroga Act claim (<strong>{{caseId}}</strong>) is now "
            "overdue for required document submissions.</strong> Despite our previous "
            "reminder, the following documents have not yet been received:</p>"
            "<div style='background:#fef2f2;border-left:4px solid #dc2626;padding:12px 16px;margin:16px 0'>"
            "<p style='margin:0;font-weight:bold;color:#991b1b'>Overdue Documents:</p>"
            "<p style='margin:8px 0 0;white-space:pre-line'>{{missingDocsList}}</p>"
            "</div>"
            "<p style='color:#b91c1c;font-weight:bold'>Failure to submit the required "
            "documents may result in delays or jeopardize the processing of your claim. "
            "Immediate action is required.</p>"
            "<p style='text-align:center;margin:24px 0'>"
            "<a href='{{portalUrl}}' "
            "style='background:#b91c1c;color:#fff;padding:12px 28px;"
            "border-radius:4px;text-decoration:none;font-weight:bold'>"
            "Upload Documents Immediately</a></p>"
            "<p>If you are experiencing difficulties or have already submitted these "
            "documents, please contact our office immediately so we can update "
            "your file.</p>"
            "<hr style='border:none;border-top:1px solid #eee;margin:24px 0'>"
            "<p style='font-size:12px;color:#888'>"
            "The Zadroga Case Management Team<br>"
            "This message was sent regarding case {{caseId}}.</p>"
            "</body></html>"
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
