"""
seed_reporting_settings.py — Seed firmSettings documents for the reporting service.

Creates / updates the three firmSettings documents read by reporting-service:
    firmSettings/pipeline   — activeStatuses[]
    firmSettings/intake     — scoreFieldName
    firmSettings/reporting  — metricLabels{}

Run once per environment:
    python scripts/seed_reporting_settings.py --project <your-gcp-project-id>

Options
-------
  --project PROJECT   GCP project ID (default: $GCP_PROJECT_ID)
  --database DB       Firestore database ID (default: simpletort-dev)
"""
import argparse
import os
import sys
from google.cloud import firestore

parser = argparse.ArgumentParser(description="Seed reporting-service firmSettings documents into Firestore.")
parser.add_argument("--project",  default=os.environ.get("GCP_PROJECT_ID"), help="GCP project ID")
parser.add_argument("--database", default="simpletort-dev",                 help="Firestore database ID")
args = parser.parse_args()

if not args.project:
    print("ERROR: --project is required (or set GCP_PROJECT_ID).")
    sys.exit(1)

db = firestore.Client(project=args.project, database=args.database)

documents = [
    {
        "id": "pipeline",
        "data": {
            # Statuses considered "active" for KPI counts and bottleneck analysis.
            # Update this list when pipeline stages change — no redeploy needed.
            "activeStatuses": [
                "New Lead",
                "Pending Client Information",
                "Pending Paralegal Review",
                "Pending Attorney Review",
                "Ready for Filing",
                "VCF - Submitted",
                "Awarded",
                "On Hold",
            ],
            "closedStatuses": [
                "Settled",
                "Does Not Qualify",
                "Withdrawn",
                "Rejected",
                "Closed",
            ],
        },
    },
    {
        "id": "intake",
        "data": {
            # Field name on the case document that holds the qualification score.
            # VCF era used "qualificationScore"; generic default is "caseScore".
            "scoreFieldName": "caseScore",
        },
    },
    {
        "id": "reporting",
        "data": {
            # Display labels for KPI dashboard metrics.
            # Override per firm without a code change.
            "metricLabels": {
                "avgScore": "Avg Case Score",
            },
        },
    },
]

for doc in documents:
    ref = db.collection("firmSettings").document(doc["id"])
    ref.set(doc["data"], merge=True)
    print(f"Seeded firmSettings/{doc['id']}")

print("\nDone.")
