# Legal Portal — Firebase Cloud Functions

## Project Structure

```
legal_portal/
├── firebase.json                  # Firebase project config + emulator settings
├── _firebaserc                    # Firebase project aliases
├── package.json                   # JS dev deps for Firestore rules tests
│
├── firestore/
│   ├── firestore.rules            # Firestore security rules (RBAC at DB level)
│   ├── firestore_indexes.json     # Composite indexes (users, cases, audit_log, sessions)
│   └── firestore_rules_test.js   # 658-line Jest emulator test suite
│
├── frontend/
│   └── index.html                 # Admin UI — user management, role assignment,
│                                  # permission preview, activity log, invite flow
│
└── functions/                     # Python 3.12 Cloud Functions
    ├── main.py                    # Entry point — SDK init + function re-exports
    ├── requirements.txt           # Pinned Python dependencies
    │
    ├── middleware/
    │   ├── http.py                # ★ Shared utilities (new consolidated file):
    │   │                          #   REGION, CORS_HEADERS, PHI_FIELDS,
    │   │                          #   json_ok/err, handle_options(),
    │   │                          #   db(), serialise_doc(), write_audit_event()
    │   └── jwt_middleware.py      # JWT / session auth; re-exports from http.py
    │
    ├── auth/
    │   ├── rbac.py                # Roles, permissions, permission matrix, guards
    │   ├── auth_service.py        # User creation, sessions, rate limiting, email
    │   └── triggers.py            # Firebase Auth onCreate / onDelete triggers
    │
    ├── api/
    │   ├── auth_api.py            # register, createSession, logout,
    │   │                          # passwordReset, createInvite
    │   ├── users.py               # createUser, listUsers, getUser,
    │   │                          # updateUser, deleteUser
    │   └── audit.py               # getAuditLog (senior_partner only)
    │
    └── tests/
        └── test_rbac.py           # pytest suite — all roles × permissions
```

## Consolidation Summary

`middleware/http.py` is the new single home for logic that was previously
duplicated across 6 files:

| What was duplicated | Where it lived | Occurrences |
|---|---|---|
| `REGION = "us-central1"` | audit.py, auth_api.py, users.py | 3 |
| `if req.method == "OPTIONS": return ...` | auth_api.py, users.py, audit.py | 11 |
| `CORS_HEADERS` dict | jwt_middleware.py (defined), 4 files (imported) | 5 |
| `json_ok` / `json_err` | jwt_middleware.py (defined), 4 files (imported) | 5 |
| `db.collection("audit_log").add({...})` | rbac.py, triggers.py, users.py | 5 |
| Timestamp `.isoformat()` loop | users.py (×3), audit.py (×2) | 5 |
| PHI field stripping | users.py `list_users_fn` + `get_user_fn` | 2 |
| `fs_admin.client()` shortcut | 6 files, 18 call sites | 18 |

## Quick Start

```bash
# Install JS deps (for Firestore rules tests)
npm install

# Install Python deps
cd functions && pip install -r requirements.txt

# Run Firestore rules tests
firebase emulators:exec --only firestore "npx jest firestore/firestore_rules_test.js"

# Run Python RBAC unit tests
cd functions && pytest tests/test_rbac.py -v

# Start all emulators
firebase emulators:start
```

## Environment Variables

Set these on your Cloud Functions deployment:

| Variable | Required | Description |
|---|---|---|
| `EMAIL_PROVIDER` | Yes | `sendgrid` or `mailgun` |
| `SENDGRID_API_KEY` | If sendgrid | SendGrid API key |
| `SENDGRID_FROM_EMAIL` | If sendgrid | Sender address |
| `MAILGUN_API_KEY` | If mailgun | Mailgun API key |
| `MAILGUN_DOMAIN` | If mailgun | Mailgun domain |
| `MAILGUN_FROM_EMAIL` | If mailgun | Sender address |
| `PORTAL_BASE_URL` | Yes | Frontend URL for invite links |

## Bugs Fixed

| ID | Severity | Description |
|---|---|---|
| F-01 | Medium | Email verification link was generated but never sent (TODO comment) |
| F-02 | Low | `refresh_session()` existed but was never called — timeout was absolute not idle |
| F-03 | Low | Rate limiter mixed `SERVER_TIMESTAMP` writes with `time.time()` reads |
| F-04 | Medium | `ADMIN_STAFF` was missing `MANAGE_USERS` permission |
| F-05 | Low | No Python unit tests for `rbac.py` |
| F-06 | Low | 60s token cache meant revoked tokens stayed valid; `PUBLIC_PATHS` dead code |
