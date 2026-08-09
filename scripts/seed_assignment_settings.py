"""
seed_assignment_settings.py — Add assignToRole to firmSettings/assignment_mode.

The case-assignment Cloud Function now reads assignToRole from this document
to determine which staff role receives newly created cases.  Run this once to
add the field to the existing document without overwriting the mode value.

    python scripts/seed_assignment_settings.py --project <your-gcp-project-id>

Options
-------
  --project PROJECT   GCP project ID (default: $GCP_PROJECT_ID)
  --database DB       Firestore database ID (default: simpletort-dev)
"""
import argparse
import os
import sys
from google.cloud import firestore

parser = argparse.ArgumentParser(description="Seed firmSettings/assignment_mode into Firestore.")
parser.add_argument("--project",  default=os.environ.get("GCP_PROJECT_ID"), help="GCP project ID")
parser.add_argument("--database", default="simpletort-dev",                 help="Firestore database ID")
args = parser.parse_args()

if not args.project:
    print("ERROR: --project is required (or set GCP_PROJECT_ID).")
    sys.exit(1)

db = firestore.Client(project=args.project, database=args.database)

ref = db.collection("firmSettings").document("assignment_mode")
ref.set(
    {
        # value: assignment algorithm — "load_balancing" or "round_robin"
        "value": "load_balancing",
        # assignToRole: which staff role new cases are auto-assigned to.
        # Change to "admin_staff" or "junior_partner" without a redeploy.
        "assignToRole": "paralegal",
    },
    merge=True,
)
print("Seeded firmSettings/assignment_mode  { value: load_balancing, assignToRole: paralegal }")
print("\nDone.")
