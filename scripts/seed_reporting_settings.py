"""
seed_reporting_settings.py — Seed firmSettings documents for the reporting service.

Creates / updates the three firmSettings documents read by reporting-service:
    firmSettings/pipeline   — activeStatuses[]
    firmSettings/intake     — scoreFieldName
    firmSettings/reporting  — metricLabels{}

Run once per environment:
    python scripts/seed_reporting_settings.py
"""
from google.cloud import firestore

db = firestore.Client(project="simpletort-zadroga-dev", database="simpletort-dev")

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
