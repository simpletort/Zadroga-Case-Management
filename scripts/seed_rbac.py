"""
scripts/seed_rbac.py — Seed roles and permissions_registry into Firestore.

Writes:
  roles/{roleId}                — 6 role documents with permission arrays
  permissions_registry/default  — 42 permissions with displayName/category/description

Usage
-----
  # Authenticate first (ADC)
  gcloud auth application-default login

  # Dry run
  python scripts/seed_rbac.py --project <your-gcp-project-id> --dry-run

  # Seed
  python scripts/seed_rbac.py --project <your-gcp-project-id>

  # Overwrite existing documents
  python scripts/seed_rbac.py --project <your-gcp-project-id> --overwrite

Options
-------
  --project PROJECT   GCP project ID (default: <your-gcp-project-id>)
  --database DB       Firestore database ID (default: simpletort-dev)
  --dry-run           Print what would be written without writing
  --overwrite         Overwrite existing documents (default: skip)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# ── Role definitions (mirrors _ROLES_FIXTURE in tests/test_rbac.py) ──────────

ROLES = [
    {
        "roleId":      "client",
        "displayName": "Client",
        "description": "End client — limited read access",
        "permissions": [
            "cases.read", "documents.read", "documents.upload",
            "communications.read", "timeline.read",
            "storage.signed_url", "storage.upload.write",
            "storage.upload.read", "storage.documents.read",
        ],
    },
    {
        "roleId":      "admin_staff",
        "displayName": "Admin Staff",
        "description": "Front-office staff",
        "permissions": [
            "cases.read", "cases.write", "cases.status.update",
            "clients.read", "clients.write",
            "documents.read", "documents.upload",
            "tasks.read", "tasks.write", "tasks.complete",
            "communications.read", "communications.write",
            "timeline.read", "expenses.read", "expenses.write",
            "disbursements.read", "staff.read", "staff.manage",
            "storage.signed_url", "storage.metadata.read",
            "storage.upload.write", "storage.upload.read",
            "storage.documents.read", "storage.documents.write",
        ],
    },
    {
        "roleId":      "paralegal",
        "displayName": "Paralegal",
        "description": "Paralegal — document review and case handling",
        "permissions": [
            "cases.read", "cases.write", "cases.status.update",
            "clients.read", "clients.write",
            "documents.read", "documents.upload", "documents.verify",
            "tasks.read", "tasks.write", "tasks.complete", "tasks.assign",
            "communications.read", "communications.write",
            "timeline.read", "expenses.read", "expenses.write",
            "disbursements.read", "staff.read", "reports.read",
            "storage.signed_url", "storage.metadata.read",
            "storage.upload.write", "storage.upload.read",
            "storage.documents.read", "storage.documents.write",
        ],
    },
    {
        "roleId":      "junior_partner",
        "displayName": "Junior Partner",
        "description": "Attorney — case approval and escalation",
        "permissions": [
            "cases.read", "cases.write", "cases.status.update", "cases.approve",
            "clients.read", "clients.write",
            "documents.read", "documents.upload", "documents.verify",
            "tasks.read", "tasks.write", "tasks.complete", "tasks.assign", "tasks.skip",
            "communications.read", "communications.write",
            "timeline.read", "expenses.read", "expenses.write",
            "disbursements.read", "disbursements.write",
            "staff.read", "reports.read", "analytics.read",
            "settings.read", "auditLog.read",
            "storage.signed_url", "storage.metadata.read",
            "storage.upload.write", "storage.upload.read",
            "storage.documents.read", "storage.documents.write",
            "storage.lifecycle.read", "storage.hold.write",
        ],
    },
    {
        "roleId":      "senior_partner",
        "displayName": "Senior Partner",
        "description": "Full access except system administration",
        "permissions": [
            "cases.read", "cases.write", "cases.status.update",
            "cases.approve", "cases.delete",
            "clients.read", "clients.write",
            "documents.read", "documents.upload", "documents.verify", "documents.override",
            "tasks.read", "tasks.write", "tasks.complete",
            "tasks.assign", "tasks.skip", "tasks.delete",
            "communications.read", "communications.write",
            "timeline.read", "expenses.read", "expenses.write",
            "disbursements.read", "disbursements.write", "disbursements.approve",
            "staff.read", "staff.write", "staff.manage",
            "reports.read", "analytics.read",
            "settings.read", "settings.write", "auditLog.read",
            "storage.signed_url", "storage.metadata.read",
            "storage.lifecycle.read", "storage.lifecycle.write",
            "storage.hold.write", "storage.upload.write", "storage.upload.read",
            "storage.documents.read", "storage.documents.write",
        ],
    },
    {
        "roleId":      "system_admin",
        "displayName": "System Admin",
        "description": "Full platform access including role management",
        "permissions": [
            "system.admin", "staff.manage", "staff.invite", "auditLog.read",
            "cases.read", "cases.write", "cases.delete",
            "settings.read", "settings.write",
            "storage.signed_url", "storage.metadata.read",
            "storage.upload.read", "storage.upload.write",
            "storage.documents.read", "storage.documents.write",
            "storage.hold.write",
            "storage.lifecycle.read", "storage.lifecycle.write",
        ],
    },
]


# ── Permissions registry ───────────────────────────────────────────────────────

# Loaded from firestore/seed/permissions_registry.json, with staff.invite added.
def _load_permissions(repo_root: Path) -> list[dict]:
    registry_path = repo_root / "firestore" / "seed" / "permissions_registry.json"
    with open(registry_path, encoding="utf-8") as f:
        data = json.load(f)
    permissions: list[dict] = data["data"]["permissions"]

    # Add staff.invite — used in auth_api.py but absent from the JSON file
    existing_ids = {p["id"] for p in permissions}
    if "staff.invite" not in existing_ids:
        permissions.append({
            "id":          "staff.invite",
            "displayName": "Invite Staff",
            "category":    "staff",
            "description": "Generate portal invite links for new users",
        })

    return sorted(permissions, key=lambda p: p["id"])


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed RBAC roles and permissions into Firestore.")
    parser.add_argument("--project",  default=os.environ.get("GCP_PROJECT_ID"), help="GCP project ID")
    parser.add_argument("--database", default="simpletort-dev",         help="Firestore database ID")
    parser.add_argument("--dry-run",  action="store_true",              help="Print without writing")
    parser.add_argument("--overwrite",action="store_true",              help="Overwrite existing documents")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent

    if args.dry_run:
        print("[DRY RUN] No changes will be written.\n")

    # ── Firestore client ───────────────────────────────────────────────────────
    if not args.dry_run:
        try:
            from google.cloud import firestore
        except ImportError:
            print("ERROR: google-cloud-firestore not installed.")
            print("  pip install google-cloud-firestore")
            sys.exit(1)
        db = firestore.Client(project=args.project, database=args.database)

    # ── Seed roles ─────────────────────────────────────────────────────────────
    print(f"Seeding roles collection ({len(ROLES)} documents)...")
    for role in ROLES:
        role_id = role["roleId"]
        perm_count = len(role["permissions"])
        if args.dry_run:
            print(f"  WRITE  roles/{role_id}  ({perm_count} permissions)")
            continue

        ref = db.collection("roles").document(role_id)
        if not args.overwrite and ref.get().exists:
            print(f"  SKIP   roles/{role_id} (already exists; use --overwrite to replace)")
            continue

        ref.set(role)
        print(f"  OK     roles/{role_id}  ({perm_count} permissions)")

    # ── Seed permissions_registry ──────────────────────────────────────────────
    print(f"\nSeeding permissions_registry/default...")
    permissions = _load_permissions(repo_root)

    if args.dry_run:
        print(f"  WRITE  permissions_registry/default  ({len(permissions)} permissions)")
        for p in permissions:
            print(f"         {p['id']}")
    else:
        ref = db.collection("permissions_registry").document("default")
        if not args.overwrite and ref.get().exists:
            print("  SKIP   permissions_registry/default (already exists; use --overwrite to replace)")
        else:
            ref.set({"permissions": permissions})
            print(f"  OK     permissions_registry/default  ({len(permissions)} permissions)")

    print("\nDone.")


if __name__ == "__main__":
    main()
