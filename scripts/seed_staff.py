"""
scripts/seed_staff.py — Seed staff accounts (Firebase Auth user + staff/{uid} doc).

Mirrors services/auth-rbac-cr/app/services/auth_service.py::create_user() so
seeded accounts can actually log in: creates the Firebase Auth user, sets the
`role` custom claim, then writes the matching staff/{uid} Firestore document.

Usage
-----
  # Authenticate first (ADC)
  gcloud auth application-default login

  # Dry run
  python scripts/seed_staff.py --project <your-gcp-project-id> --dry-run

  # Seed
  python scripts/seed_staff.py --project <your-gcp-project-id>

  # Update claims/doc for a user that already exists
  python scripts/seed_staff.py --project <your-gcp-project-id> --overwrite

Options
-------
  --project PROJECT   GCP project ID (default: $GCP_PROJECT_ID)
  --database DB       Firestore database ID (default: simpletort-dev)
  --dry-run           Print what would be written without writing
  --overwrite         Update claims/doc if the user already exists (default: skip)
"""
from __future__ import annotations

import argparse
import os
import re
import sys

# ── Staff to seed ────────────────────────────────────────────────────────────
# Mirrors the shape accepted by auth_service.create_user().

USERS = [
    {
        "email":        "systemadmin@test.com",
        "password":     "SystemAdmin@1234",
        "role":         "system_admin",
        "display_name": "Test_System_Admin",
    },
]

# roleId -> displayName, mirrors ROLES in scripts/seed_rbac.py (roles collection
# must already be seeded via seed_rbac.py for these labels to mean anything).
sys.path.insert(0, os.path.dirname(__file__))
from seed_rbac import ROLES  # noqa: E402

ROLE_LABELS = {r["roleId"]: r["displayName"] for r in ROLES}

# ── Password policy ──────────────────────────────────────────────────────────
# Mirrors auth_service.PASSWORD_POLICY exactly.

PASSWORD_POLICY = {
    "min_length":        8,
    "require_uppercase": True,
    "require_lowercase": True,
    "require_digit":     True,
    "require_special":   True,
    "special_chars":     "!@#$%^&*()_+-=[]{}|;':\",./<>?",
}


def validate_password(password: str) -> None:
    p      = PASSWORD_POLICY
    errors = []
    if len(password) < p["min_length"]:
        errors.append(f"Minimum {p['min_length']} characters required.")
    if p["require_uppercase"] and not re.search(r"[A-Z]", password):
        errors.append("Must contain an uppercase letter.")
    if p["require_lowercase"] and not re.search(r"[a-z]", password):
        errors.append("Must contain a lowercase letter.")
    if p["require_digit"] and not re.search(r"\d", password):
        errors.append("Must contain a digit.")
    if p["require_special"] and not re.search(
        r"[" + re.escape(p["special_chars"]) + r"]", password
    ):
        errors.append("Must contain a special character.")
    if errors:
        raise ValueError(" ".join(errors))


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed staff accounts into Firebase Auth + Firestore.")
    parser.add_argument("--project",   default=os.environ.get("GCP_PROJECT_ID"), help="GCP project ID")
    parser.add_argument("--database",  default="simpletort-dev",                 help="Firestore database ID")
    parser.add_argument("--dry-run",   action="store_true",                      help="Print without writing")
    parser.add_argument("--overwrite", action="store_true",                      help="Update existing users")
    args = parser.parse_args()

    if not args.dry_run and not args.project:
        print("ERROR: --project is required (or set GCP_PROJECT_ID).")
        sys.exit(1)

    for user in USERS:
        validate_password(user["password"])

    if args.dry_run:
        print("[DRY RUN] No changes will be written.\n")
        for user in USERS:
            role_label = ROLE_LABELS.get(user["role"], user["role"])
            print(f"  WRITE  auth user   {user['email']}  (role={user['role']})")
            print(f"  WRITE  staff/{{uid}}  displayName={user['display_name']!r} roleLabel={role_label!r}")
        print("\nDone.")
        return

    try:
        import firebase_admin
        from firebase_admin import auth, credentials
        from google.cloud import firestore
    except ImportError:
        print("ERROR: firebase-admin / google-cloud-firestore not installed.")
        print("  pip install firebase-admin google-cloud-firestore")
        sys.exit(1)

    if not firebase_admin._apps:
        cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred, {"projectId": args.project})

    db = firestore.Client(project=args.project, database=args.database)

    for user in USERS:
        email        = user["email"]
        role         = user["role"]
        display_name = user["display_name"]
        role_label   = ROLE_LABELS.get(role, role)

        try:
            existing = auth.get_user_by_email(email)
        except auth.UserNotFoundError:
            existing = None

        if existing and not args.overwrite:
            print(f"  SKIP   {email} (already exists; use --overwrite to update)")
            continue

        if existing:
            uid = existing.uid
            auth.update_user(uid, password=user["password"], display_name=display_name, email_verified=False)
            print(f"  OK     auth user updated  {email}  (uid={uid})")
        else:
            record = auth.create_user(
                email=email,
                password=user["password"],
                display_name=display_name,
                email_verified=False,
            )
            uid = record.uid
            print(f"  OK     auth user created  {email}  (uid={uid})")

        auth.set_custom_user_claims(uid, {"role": role, "active": True})

        ref = db.collection("staff").document(uid)
        ref.set({
            "userId":            uid,
            "email":             email,
            "displayName":       display_name,
            "role":              role,
            "roleLabel":         role_label,
            "isActive":          True,
            "googleWorkspaceId": "",
            "lastLoginAt":       None,
            "createdAt":         firestore.SERVER_TIMESTAMP,
        }, merge=args.overwrite)
        print(f"  OK     staff/{uid}  role={role}")

    print("\nDone.")


if __name__ == "__main__":
    main()
