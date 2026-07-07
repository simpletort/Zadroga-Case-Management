"""
find_intake_tokens.py — Lookup intake form tokens by case ID or case status.

Usage:
    python scripts/find_intake_tokens.py --case-id ZAD-2026-03-0001
    python scripts/find_intake_tokens.py --status "New Lead"
    python scripts/find_intake_tokens.py  (lists all tokens)
"""

import argparse
from google.cloud import firestore

PROJECT_ID = "simpletort-zadroga-dev"
DATABASE_ID = "simpletort-dev"

db = firestore.Client(project=PROJECT_ID, database=DATABASE_ID)

parser = argparse.ArgumentParser()
parser.add_argument("--case-id", help="ZAD case ID to look up")
parser.add_argument("--status", help="Filter by case status")
args = parser.parse_args()

tokens = db.collection("intake_tokens").stream()
results = []

for doc in tokens:
    data = doc.to_dict()
    case_id = data.get("caseId", "")

    if args.case_id and case_id != args.case_id:
        continue

    if args.status:
        case_doc = db.collection("cases").document(case_id).get()
        if not case_doc.exists or case_doc.to_dict().get("status") != args.status:
            continue

    results.append({
        "tokenId": doc.id,
        "caseId": case_id,
        "clientName": data.get("clientName", "N/A"),
        "clientEmail": data.get("clientEmail", "N/A"),
        "emailSent": data.get("emailSent"),
        "used": data.get("used"),
        "expiresAt": data.get("expiresAt"),
        "previewUrl": data.get("previewUrl", ""),
    })

print(f"Found {len(results)} token(s)\n")
for r in results:
    print(f"Case ID    : {r['caseId']}")
    print(f"Token ID   : {r['tokenId']}")
    print(f"Client     : {r['clientName']} ({r['clientEmail']})")
    print(f"Email Sent : {r['emailSent']}")
    print(f"Used       : {r['used']}")
    print(f"Expires    : {r['expiresAt']}")
    print(f"Form URL   : {r['previewUrl']}")
    print()
