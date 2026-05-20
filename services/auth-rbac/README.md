# auth-rbac — Authentication, RBAC & Portal UI

This service owns:
- **Firebase Auth** — login, signup, session cookies, password reset, portal invites
- **RBAC** — 5-role permission system (senior_partner → client)
- **User management API** — create, list, update, soft-delete users
- **Audit log** — immutable event log (senior_partner only)
- **React frontend** — case portal UI (login, dashboard, admin panel)

## Structure

```
auth-rbac/
├── backend/                   ← Firebase project root (deploy from here)
│   ├── firebase.json          ← Hosting + Functions + Firestore config
│   ├── _firebaserc            ← Project: simple-tort-zadroga-prod
│   ├── firestore/
│   │   └── firestore.rules    ← Security rules (mirrors RBAC)
│   └── functions/             ← Python 3.12 Cloud Functions
│       ├── main.py
│       ├── api/               ← HTTP endpoints
│       │   ├── auth_api.py
│       │   ├── users.py
│       │   └── audit.py
│       ├── auth/              ← RBAC + auth service
│       │   ├── rbac.py
│       │   ├── auth_service.py
│       │   └── triggers.py
│       └── middleware/        ← JWT + HTTP utils
│           ├── http.py
│           └── jwt_middleware.py
│
├── frontend/                  ← React + Vite + Tailwind v4
│   ├── src/
│   │   ├── lib/
│   │   │   ├── firebase.ts    ← Firebase SDK init
│   │   │   ├── api.ts         ← Typed Cloud Function wrappers
│   │   │   └── AuthContext.tsx← Auth state + hooks
│   │   ├── components/
│   │   └── main.tsx
│   ├── styles/
│   ├── .env.example           ← Copy to .env.local, fill in Firebase config
│   ├── package.json
│   └── vite.config.ts         ← Builds into ../backend/frontend/dist
│
└── .github/
    └── workflows/
        └── deploy.yml         ← Auto-deploy on push to main
```

## Local Development

```bash
# Terminal 1 — Firebase emulators
cd backend
firebase emulators:start

# Terminal 2 — React dev server
cd frontend
cp .env.example .env.local    # fill in your 3 Firebase values
npm install
npm run dev
# → http://localhost:5173
```

## Deploy

```bash
# 1. Build frontend (outputs to backend/frontend/dist)
cd frontend && npm run build

# 2. Deploy everything to Firebase
cd ../backend && firebase deploy
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `EMAIL_PROVIDER` | Yes | `"sendgrid"` or `"mailgun"` |
| `SENDGRID_API_KEY` | If SendGrid | SendGrid API key |
| `SENDGRID_FROM_EMAIL` | If SendGrid | Sender address |
| `MAILGUN_API_KEY` | If Mailgun | Mailgun API key |
| `MAILGUN_DOMAIN` | If Mailgun | Mailgun domain |
| `MAILGUN_FROM_EMAIL` | If Mailgun | Sender address |
| `PORTAL_BASE_URL` | Yes | Frontend URL for invite links |
| `FIREBASE_PROJECT_ID` | Yes | Firebase project ID |
| `ALLOWED_ORIGIN` | No | CORS origin (default: `https://simpletort-zadroga-dev.web.app`) |

---

## API Endpoints

All functions are deployed as Firebase Cloud Functions (region: `us-central1`).

### Authentication

#### `POST /register`

Create a new staff user account. Requires `MANAGE_USERS` permission unless creating a client via portal invite.

**Request body:**
```json
{
  "email": "string",
  "password": "string",
  "display_name": "string",
  "role": "senior_partner | junior_partner | paralegal | admin_staff | client",
  "portal_token": "string (optional, required for client self-registration)"
}
```

**Response `201`:**
```json
{
  "uid": "string",
  "email": "string",
  "display_name": "string",
  "role": "string",
  "permissions": ["string"]
}
```

**Errors:** `400` missing fields / invalid email · `409` email already registered · `500` registration failed

---

#### `POST /createSession`

Exchange a Firebase ID token for a session cookie. Public endpoint.

**Request body:**
```json
{
  "id_token": "string"
}
```

**Response `200`** (also sets `session` and `session_id` httpOnly cookies, 30-min TTL):
```json
{
  "session_id": "string",
  "expires_in_minutes": 30,
  "uid": "string",
  "role": "string",
  "permissions": ["string"]
}
```

**Errors:** `400` missing id_token · `401` invalid token · `500` session creation failed

---

#### `POST /logout`

Revoke all refresh tokens and clear session cookies. Requires authentication.

**Request body:** _(empty)_

**Response `200`** (clears cookies):
```json
{
  "message": "Logged out successfully."
}
```

**Errors:** `401` authentication required · `500` logout failed

---

#### `POST /passwordReset`

Send a password reset email. Public endpoint, rate-limited to 5 attempts per 15 minutes per IP.

**Request body:**
```json
{
  "email": "string"
}
```

**Response `200`:**
```json
{
  "message": "If that email is registered, a reset link has been sent."
}
```

**Errors:** `400` missing email · `429` rate limit exceeded · `500` password reset failed

> Response is identical for registered and unregistered emails (security).

---

#### `POST /createInvite`

Generate a 7-day, one-time-use portal invite link. Requires `senior_partner` or `system_admin` role.

**Request body:**
```json
{
  "email": "string"
}
```

**Response `200`:**
```json
{
  "invite_link": "https://portal.zadlegal.com/register?token=<token>",
  "expires_in_days": 7
}
```

**Errors:** `400` missing email · `401` unauthenticated · `403` insufficient role · `500` invite creation failed

---

### User Management

#### `POST /createUser`

Create a new user (staff or client). Requires `MANAGE_USERS` permission.

**Request body:**
```json
{
  "email": "string",
  "password": "string",
  "display_name": "string",
  "role": "senior_partner | junior_partner | paralegal | admin_staff | client",
  "portal_token": "string (optional)"
}
```

**Response `201`:**
```json
{
  "success": true,
  "user": {
    "uid": "string",
    "email": "string",
    "display_name": "string",
    "role": "string"
  }
}
```

**Errors:** `400` missing fields / invalid password · `401` unauthenticated · `403` insufficient permission or cannot assign staff roles · `500` creation failed

---

#### `GET /listUsers`

List all staff users. Requires `MANAGE_USERS` permission.

**Query parameters:**

| Param | Type | Description |
|---|---|---|
| `role` | string | Filter by role (e.g. `paralegal`) |
| `status` | string | `active` or `inactive` |
| `search` | string | Case-insensitive search on name or email |
| `page_size` | integer | Items per page (default: 20, max: 100) |
| `cursor` | string | Pagination cursor from previous response |

**Response `200`:**
```json
{
  "users": [
    {
      "userId": "string",
      "email": "string",
      "displayName": "string",
      "role": "string",
      "roleLabel": "string",
      "isActive": true,
      "googleWorkspaceId": "string",
      "lastLoginAt": "ISO8601 | null",
      "createdAt": "ISO8601",
      "activeCaseCount": 0,
      "maxCaseload": 0
    }
  ],
  "page_size": 20,
  "has_more": false,
  "next_cursor": "string | null"
}
```

**Errors:** `401` unauthenticated · `403` insufficient permission

> PHI fields (`ssn`, `dob`, `medical_info`, `phi_data`) are stripped. Results ordered by `createdAt` descending.

---

#### `GET /getUser`

Get a single user by UID. Requires `MANAGE_USERS` permission, or the caller's own UID.

**Query parameters:**

| Param | Type | Description |
|---|---|---|
| `uid` | string | Firebase Auth UID |

**Response `200`:**
```json
{
  "user": {
    "userId": "string",
    "email": "string",
    "displayName": "string",
    "role": "string",
    "roleLabel": "string",
    "isActive": true,
    "googleWorkspaceId": "string",
    "lastLoginAt": "ISO8601 | null",
    "createdAt": "ISO8601",
    "activeCaseCount": 0,
    "maxCaseload": 0
  }
}
```

**Errors:** `400` missing uid · `401` unauthenticated · `403` forbidden · `404` user not found

> PHI fields only returned if the caller has `VIEW_PHI` permission.

---

#### `PUT /updateUser`

Update a user's details or role. Requires `MANAGE_USERS` to modify others; any authenticated user may update their own `displayName` and `googleWorkspaceId`.

**Request body:**
```json
{
  "uid": "string",
  "displayName": "string (optional)",
  "googleWorkspaceId": "string (optional)",
  "role": "string (optional, MANAGE_USERS only)",
  "isActive": "boolean (optional, MANAGE_USERS only)"
}
```

**Response `200`:**
```json
{
  "success": true,
  "updated_fields": ["displayName", "role"]
}
```

**Errors:** `400` missing uid / no updatable fields · `401` unauthenticated · `403` forbidden · `404` user not found · `500` update failed

> Role changes update Firebase custom claims and write an audit log entry. `isActive: false` disables the Firebase Auth account.

---

#### `DELETE /deleteUser`

Soft-delete a user (marks as deleted, disables account, revokes tokens). Requires `MANAGE_USERS` permission.

**Query parameters:**

| Param | Type | Description |
|---|---|---|
| `uid` | string | Firebase Auth UID to delete |

**Response `200`:**
```json
{
  "success": true,
  "message": "User <uid> soft-deleted."
}
```

**Errors:** `400` missing uid · `401` unauthenticated · `403` insufficient permission · `404` user not found · `500` deletion failed

> Sets `status: "deleted"`, `deleted_at`, `deleted_by` on the staff Firestore doc; disables Firebase Auth user; revokes all refresh tokens; writes audit log entry.

---

### Audit Log

#### `GET /auditLog`

Retrieve immutable audit log entries. Requires `VIEW_AUDIT_LOG` permission (`senior_partner` or `system_admin` only).

**Query parameters:**

| Param | Type | Description |
|---|---|---|
| `uid` | string | (optional) Filter by user UID |
| `limit` | integer | Number of entries (default: 50, max: 200) |

**Response `200`:**
```json
{
  "logs": [
    {
      "event_type": "string",
      "timestamp": "ISO8601",
      "uid": "string",
      "...": "additional context fields vary by event_type"
    }
  ]
}
```

**Errors:** `401` unauthenticated · `403` insufficient permission

**Audit event types:**

| Event | Trigger |
|---|---|
| `user_registered` | Account created via `/register` |
| `session_created` | Session started via `/createSession` |
| `logout` | Logout via `/logout` |
| `permission_denied` | RBAC rejection |
| `role_change` | Role updated via `/updateUser` |
| `user_soft_deleted` | Account soft-deleted via `/deleteUser` |
| `invite_created` | Portal invite generated via `/createInvite` |
| `user_created` | User created via Firebase Auth trigger |

---

## Authentication

Every protected endpoint accepts credentials via one of two methods:

| Method | Format | TTL |
|---|---|---|
| Bearer token | `Authorization: Bearer <firebase_id_token>` | ~1 hour (Firebase default) |
| Session cookie | `session` + `session_id` cookies (set by `/createSession`) | 30-minute idle window |

---

## Roles & Permissions

| Role | Value |
|---|---|
| Senior Partner | `senior_partner` |
| Attorney | `junior_partner` |
| Paralegal | `paralegal` |
| Admin Staff | `admin_staff` |
| Client | `client` |

| Permission | client | admin_staff | paralegal | junior_partner | senior_partner / system_admin |
|---|:---:|:---:|:---:|:---:|:---:|
| `cases.read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `cases.write` | | ✓ | ✓ | ✓ | ✓ |
| `cases.status.update` | | ✓ | ✓ | ✓ | ✓ |
| `cases.approve` | | | | ✓ | ✓ |
| `cases.delete` | | | | | ✓ |
| `clients.read` | | ✓ | ✓ | ✓ | ✓ |
| `clients.write` | | ✓ | ✓ | ✓ | ✓ |
| `documents.read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `documents.upload` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `documents.verify` (VIEW_PHI) | | | ✓ | ✓ | ✓ |
| `documents.override` | | | | | ✓ |
| `tasks.read` | | ✓ | ✓ | ✓ | ✓ |
| `tasks.write` | | ✓ | ✓ | ✓ | ✓ |
| `tasks.complete` | | ✓ | ✓ | ✓ | ✓ |
| `communications.read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `communications.write` | | ✓ | ✓ | ✓ | ✓ |
| `timeline.read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `expenses.read` | | ✓ | ✓ | ✓ | ✓ |
| `expenses.write` | | ✓ | ✓ | ✓ | ✓ |
| `disbursements.read` | | ✓ | ✓ | ✓ | ✓ |
| `disbursements.write` | | | | ✓ | ✓ |
| `disbursements.approve` | | | | | ✓ |
| `staff.read` | | ✓ | ✓ | ✓ | ✓ |
| `staff.manage` (MANAGE_USERS) | | ✓ | | | ✓ |
| `reports.read` | | | ✓ | ✓ | ✓ |
| `analytics.read` | | | | ✓ | ✓ |
| `settings.read` | | | | ✓ | ✓ |
| `settings.write` | | | | | ✓ |
| `auditLog.read` (VIEW_AUDIT_LOG) | | | | | ✓ |
| `system.admin` | | | | | ✓ |

---

## Connecting to Other Services

```python
# In any other service (Python)
from firebase_admin import auth

def verify_request(id_token: str) -> dict:
    decoded = auth.verify_id_token(id_token)
    return {
        "uid":  decoded["uid"],
        "role": decoded.get("role", "client"),
    }
```

```typescript
// In any other frontend service (TypeScript)
import { auth } from "./lib/firebase";

async function getToken(): Promise<string> {
  return auth.currentUser?.getIdToken() ?? "";
}
// Pass as: Authorization: Bearer <token>
```
