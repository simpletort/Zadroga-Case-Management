"""
seed_case_profile_partner.py — Provision a partners/{id} doc + API key for the
case-development service's X-API-Key auth path (shared/shared/middlewares/auth.py).

This is what the Google Forms intake dispatcher (google-forms/apps-script/Code.gs
— CASE_API_KEY) authenticates with to call PATCH /cases/{caseId} and
PATCH /cases/{caseId}/status. Any successful X-API-Key auth is assigned role
"partner" by the middleware; case_profile_service.py's role guard grants that
role edit access to any case, scoped to the fixed field catalog only
(see services/case-development/app/models/case_profile.py — FIELD_CATALOG).

The raw key is generated here and printed ONCE — only its SHA-256 hash is
written to Firestore, matching services/lead-intake/api/models/partner.py's
ApiKeyEntry shape (this service has no partner-management API of its own yet,
so this script writes the document directly).

Run once per environment:
    python scripts/seed_case_profile_partner.py --project <your-gcp-project-id> \
        [--database DB] [--partner-id ID] [--label LABEL]

Re-running with the same --partner-id appends a new key to that partner's
apiKeys[] rather than replacing the document, so existing keys (and whatever
is currently using them) keep working.

Options
-------
  --project PROJECT   GCP project ID (default: $GCP_PROJECT_ID)
  --database DB       Firestore database ID (default: simpletort-dev)
"""
import argparse
import hashlib
import os
import secrets
import sys
from datetime import datetime, timezone

from google.cloud import firestore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project",    default=os.environ.get("GCP_PROJECT_ID"), help="GCP project ID")
    parser.add_argument("--database",   default="simpletort-dev",                 help="Firestore database ID")
    parser.add_argument("--partner-id", default="intake_form_dispatcher")
    parser.add_argument("--label", default="google-forms-intake-dispatcher")
    args = parser.parse_args()

    if not args.project:
        print("ERROR: --project is required (or set GCP_PROJECT_ID).")
        sys.exit(1)

    db = firestore.Client(project=args.project, database=args.database)

    raw_key  = "zad_case_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    now      = datetime.now(tz=timezone.utc)
    key_id   = "key_" + secrets.token_hex(4)

    partner_ref = db.collection("partners").document(args.partner_id)
    snap = partner_ref.get()

    new_key_entry = {
        "keyId":     key_id,
        "label":     args.label,
        "keyHash":   key_hash,
        "active":    True,
        "createdAt": now,
        "expiresAt": None,
    }

    if snap.exists:
        data = snap.to_dict() or {}
        existing_keys = data.get("apiKeys", [])
        partner_ref.update({
            "apiKeys":   existing_keys + [new_key_entry],
            "updatedAt": now,
        })
        print(f"Appended new key to existing partner '{args.partner_id}'.")
    else:
        partner_ref.set({
            "partnerId":    args.partner_id,
            "name":         "Google Forms Intake Dispatcher",
            "active":       True,
            "allowedIps":   [],  # unrestricted — Apps Script egress IPs aren't static
            "requireHmac":  False,
            "apiKeys":      [new_key_entry],
            "requestCount": 0,
            "createdAt":    now,
            "updatedAt":    now,
        })
        print(f"Created new partner '{args.partner_id}'.")

    print()
    print("=" * 72)
    print(f"  partnerId : {args.partner_id}")
    print(f"  keyId     : {key_id}")
    print(f"  API key   : {raw_key}")
    print("=" * 72)
    print()
    print("This key is shown ONCE — it is not stored in plaintext anywhere.")
    print("Set it as CASE_API_KEY in google-forms/apps-script/Code.gs.")


if __name__ == "__main__":
    main()
