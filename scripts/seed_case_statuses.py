"""
seed_case_statuses.py — Seed firmSettings/case_statuses for the case-development service.

Creates / overwrites the case status registry used by the UI for live dropdown options.
Status values are kept in sync with firmSettings/pipeline (activeStatuses + closedStatuses).

Run once per environment:
    python scripts/seed_case_statuses.py --project <your-gcp-project-id>

Options
-------
  --project PROJECT   GCP project ID (default: $GCP_PROJECT_ID)
  --database DB       Firestore database ID (default: simpletort-dev)
"""
import argparse
import os
import sys
from google.cloud import firestore
from datetime import datetime, timezone

parser = argparse.ArgumentParser(description="Seed firmSettings/case_statuses into Firestore.")
parser.add_argument("--project",  default=os.environ.get("GCP_PROJECT_ID"), help="GCP project ID")
parser.add_argument("--database", default="simpletort-dev",                 help="Firestore database ID")
args = parser.parse_args()

if not args.project:
    print("ERROR: --project is required (or set GCP_PROJECT_ID).")
    sys.exit(1)

db = firestore.Client(project=args.project, database=args.database)

statuses = [
    # ── Active statuses ────────────────────────────────────────────────────────
    {"value": "New Lead",                   "label": "New Lead",                   "category": "active",   "order": 1,  "color": "#6B7280"},
    {"value": "Pending Client Information", "label": "Pending Client Information", "category": "active",   "order": 2,  "color": "#F59E0B"},
    {"value": "Pending Paralegal Review",   "label": "Pending Paralegal Review",   "category": "active",   "order": 3,  "color": "#3B82F6"},
    {"value": "Pending Attorney Review",    "label": "Pending Attorney Review",    "category": "active",   "order": 4,  "color": "#8B5CF6"},
    {"value": "Pending Senior Review",      "label": "Pending Senior Review",      "category": "active",   "order": 5,  "color": "#EC4899"},
    {"value": "Approved for Filing",        "label": "Approved for Filing",        "category": "active",   "order": 6,  "color": "#10B981"},
    {"value": "VCF - Submitted",            "label": "VCF Submitted",              "category": "active",   "order": 7,  "color": "#06B6D4"},
    {"value": "Awarded",                    "label": "Awarded",                    "category": "active",   "order": 8,  "color": "#22C55E"},
    {"value": "On Hold",                    "label": "On Hold",                    "category": "active",   "order": 9,  "color": "#D97706"},
    # ── Closed / terminal statuses ─────────────────────────────────────────────
    {"value": "Settled",                    "label": "Settled",                    "category": "closed",   "order": 10, "color": "#16A34A"},
    {"value": "Rejected",                   "label": "Rejected",                   "category": "closed",   "order": 11, "color": "#EF4444"},
    {"value": "Does Not Qualify",           "label": "Does Not Qualify",           "category": "terminal", "order": 12, "color": "#DC2626"},
    {"value": "Withdrawn",                  "label": "Withdrawn",                  "category": "terminal", "order": 13, "color": "#9CA3AF"},
    {"value": "Closed",                     "label": "Closed",                     "category": "terminal", "order": 14, "color": "#4B5563"},
]

ref = db.collection("firmSettings").document("case_statuses")
ref.set({
    "statuses":  statuses,
    "updatedAt": datetime.now(tz=timezone.utc),
    "updatedBy": "seed_script",
})

print("Seeded firmSettings/case_statuses")
for s in statuses:
    print(f"  [{s['category']:8}] {s['order']:2}. {s['value']}")

print(f"\nTotal: {len(statuses)} statuses. Done.")
