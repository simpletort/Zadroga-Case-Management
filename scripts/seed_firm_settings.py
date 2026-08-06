"""
seed_firm_settings.py — Seed firmSettings documents not covered by the other
seed_*.py scripts (seed_reporting_settings.py, seed_case_statuses.py,
seed_assignment_settings.py already handle pipeline/intake/reporting,
case_statuses, assignment_mode).

Creates / updates:
    firmSettings/firm_name                  — value (DUMMY — replace before prod use)
    firmSettings/firm_email                 — value (DUMMY — replace before prod use)
    firmSettings/firm_phone                 — value (DUMMY — replace before prod use)
    firmSettings/firm_address               — value (DUMMY — replace before prod use)
    firmSettings/fee_config                 — flat-percentage attorney fee (DUMMY — replace before prod use)
    firmSettings/feature_flags              — require_ai_summary
    firmSettings/document_checklists        — default[] + overrides{}
    firmSettings/case_profile_editable_fields — enabledFields[] (all catalog fields)
    firmSettings/notifications              — fromName / replyTo / logoUrl
    firmSettings/case_id_prefix             — prefix
    firmSettings/max_file_size              — maxFileSizeMb
    firmSettings/expense_categories         — custom_categories[]

pdf_service.py (settlement-financial) raises ConfigError without firm_name;
this is the script it points to. fee_config is read by the settlement fee
calculator — the values below are placeholders for dev/test only.

Run once per environment:
    python scripts/seed_firm_settings.py --project <your-gcp-project-id>

Options
-------
  --project PROJECT   GCP project ID (default: $GCP_PROJECT_ID)
  --database DB       Firestore database ID (default: simpletort-dev)
"""
import argparse
import os
import sys
import uuid
from datetime import datetime, timezone

from google.cloud import firestore

parser = argparse.ArgumentParser(description="Seed firmSettings documents into Firestore.")
parser.add_argument("--project",  default=os.environ.get("GCP_PROJECT_ID"), help="GCP project ID")
parser.add_argument("--database", default="simpletort-dev",                 help="Firestore database ID")
args = parser.parse_args()

if not args.project:
    print("ERROR: --project is required (or set GCP_PROJECT_ID).")
    sys.exit(1)

db = firestore.Client(project=args.project, database=args.database)

# Fixed catalog from services/case-development/app/models/case_profile.py —
# keep in sync if that file's FIELD_CATALOG changes.
CASE_PROFILE_ALLOWED_FIELDS = [
    "phone", "email", "address", "notes", "assigned_attorney",
    "first_name", "last_name", "date_of_birth", "exposure_location",
    "exposure_date_start", "exposure_date_end", "conditions",
    "prior_attorney", "questionnaire_complete",
]

documents = [
    {
        "id": "firm_name",
        "data": {"value": "SimpleTort Test Firm, LLP"},  # DUMMY
    },
    {
        "id": "firm_email",
        "data": {"value": "contact@simpletort-test.com"},  # DUMMY
    },
    {
        "id": "firm_phone",
        "data": {"value": "(555) 010-1234"},  # DUMMY
    },
    {
        "id": "firm_address",
        "data": {"value": "123 Main Street, Suite 400, New York, NY 10001"},  # DUMMY
    },
    {
        "id": "fee_config",
        "data": {
            # DUMMY flat 33.33% fee, no cap — replace with real firm terms before prod use.
            "config_id":       str(uuid.uuid4()),
            "structure_type":  "flat",
            "flat_percentage": "33.3300",
            "graduated_tiers": [],
            "cap_type":        "none",
            "cap_amount":      None,
            "cap_percentage":  None,
            "effective_date":  datetime.now(tz=timezone.utc),
            "notes":           "Dummy dev/test seed value — replace before prod use.",
            "updated_by":      "seed_firm_settings.py",
            "updated_at":      firestore.SERVER_TIMESTAMP,
        },
    },
    {
        "id": "feature_flags",
        "data": {
            "require_ai_summary": True,
        },
    },
    {
        "id": "document_checklists",
        "data": {
            "default":   ["medical records", "proof of presence", "id documents"],
            "overrides": {},
        },
    },
    {
        "id": "case_profile_editable_fields",
        "data": {
            "enabledFields": sorted(CASE_PROFILE_ALLOWED_FIELDS),
        },
    },
    {
        "id": "notifications",
        "data": {
            "fromName": "SimpleTort Test Firm, LLP",       # DUMMY — mirrors firm_name
            "replyTo":  "contact@simpletort-test.com",     # DUMMY — mirrors firm_email
            "logoUrl":  "",
        },
    },
    {
        "id": "case_id_prefix",
        "data": {
            "prefix": "CASE",
        },
    },
    {
        "id": "max_file_size",
        "data": {
            "maxFileSizeMb": 25,
        },
    },
    {
        "id": "expense_categories",
        "data": {
            "custom_categories": [],
        },
    },
]

for doc in documents:
    ref = db.collection("firmSettings").document(doc["id"])
    ref.set(doc["data"], merge=True)
    print(f"Seeded firmSettings/{doc['id']}")

print("\nDone.")
print("\nNOTE: firm_name/firm_email/firm_phone/firm_address, notifications, and")
print("fee_config were seeded with DUMMY values — update them with real firm")
print("data before generating any real settlement statement or fee calculation.")
