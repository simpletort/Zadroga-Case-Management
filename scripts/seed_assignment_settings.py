"""
seed_assignment_settings.py — Add assignToRole to firmSettings/assignment_mode.

The case-assignment Cloud Function now reads assignToRole from this document
to determine which staff role receives newly created cases.  Run this once to
add the field to the existing document without overwriting the mode value.

    python scripts/seed_assignment_settings.py
"""
import os
from google.cloud import firestore

db = firestore.Client(
    project=os.environ["GCP_PROJECT_ID"],
    database=os.environ.get("FIRESTORE_DATABASE_ID", "simpletort-dev"),
)

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
