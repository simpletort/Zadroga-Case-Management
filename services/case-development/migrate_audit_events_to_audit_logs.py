"""
migrate_audit_events_to_audit_logs.py

One-time migration: copies all documents from `audit_events` (global) and
`cases/{caseId}/audit_events` (subcollection) into the new `audit_logs`
collection, preserving the same document IDs and schema.

Usage:
    export GCP_PROJECT_ID=simpletort-zadroga-dev
    export FIRESTORE_DATABASE_ID=simpletort-dev
    python migrate_audit_events_to_audit_logs.py

    # Dry run (read-only, no writes):
    python migrate_audit_events_to_audit_logs.py --dry-run

Safety:
    - Read-only on audit_events (never modifies or deletes source docs).
    - Idempotent: uses set() with the same doc ID, so re-running is safe.
    - Prints progress every 50 docs.
"""
from __future__ import annotations

import argparse
import os
import sys

from google.cloud import firestore


def get_db() -> firestore.Client:
    project = os.environ.get("GCP_PROJECT_ID", "simpletort-zadroga-dev")
    database = os.environ.get("FIRESTORE_DATABASE_ID", "simpletort-dev")
    return firestore.Client(project=project, database=database)


def migrate_global_collection(db: firestore.Client, dry_run: bool) -> int:
    """Copy audit_events/{docId} → audit_logs/{docId}."""
    print("\n── Migrating global audit_events → audit_logs ──")
    count = 0
    for doc in db.collection("audit_events").stream():
        data = doc.to_dict()
        if not data:
            continue
        if not dry_run:
            db.collection("audit_logs").document(doc.id).set(data)
        count += 1
        if count % 50 == 0:
            print(f"  ... {count} global docs {'would be ' if dry_run else ''}copied")

    print(f"  Total global docs: {count} {'(dry run)' if dry_run else 'copied'}")
    return count


def migrate_case_subcollections(db: firestore.Client, dry_run: bool) -> int:
    """Copy cases/{caseId}/audit_events/{docId} → cases/{caseId}/audit_logs/{docId}."""
    print("\n── Migrating case-scoped audit_events → audit_logs ──")
    count = 0
    for case_doc in db.collection("cases").stream():
        case_id = case_doc.id
        sub_ref = case_doc.reference.collection("audit_events")
        for audit_doc in sub_ref.stream():
            data = audit_doc.to_dict()
            if not data:
                continue
            if not dry_run:
                (
                    db.collection("cases")
                    .document(case_id)
                    .collection("audit_logs")
                    .document(audit_doc.id)
                    .set(data)
                )
            count += 1
            if count % 50 == 0:
                print(f"  ... {count} case-scoped docs {'would be ' if dry_run else ''}copied")

    print(f"  Total case-scoped docs: {count} {'(dry run)' if dry_run else 'copied'}")
    return count


def main():
    parser = argparse.ArgumentParser(description="Migrate audit_events → audit_logs")
    parser.add_argument("--dry-run", action="store_true", help="Read-only, no writes")
    args = parser.parse_args()

    db = get_db()

    print(f"Project:  {db.project}")
    print(f"Database: {db._database_string}")
    print(f"Mode:     {'DRY RUN' if args.dry_run else 'LIVE'}")

    global_count = migrate_global_collection(db, args.dry_run)
    case_count = migrate_case_subcollections(db, args.dry_run)

    print(f"\n── Done ──")
    print(f"  Global docs:      {global_count}")
    print(f"  Case-scoped docs: {case_count}")
    print(f"  Total:            {global_count + case_count}")

    if args.dry_run:
        print("\n  (Dry run — no writes were made. Remove --dry-run to execute.)")


if __name__ == "__main__":
    main()
