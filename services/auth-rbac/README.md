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
│       ├── auth/              ← RBAC + auth service
│       └── middleware/        ← JWT + HTTP utils
│
├── frontend/                  ← React + Vite + Tailwind v4
│   ├── src/                   ← All components, lib, routes
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

## Connecting to Other Services

This service exposes Firebase Auth tokens that other services can verify:

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

## Roles

| Role | Value | Key Permissions |
|---|---|---|
| Senior Partner | `senior_partner` | Full access including audit log |
| Attorney | `junior_partner` | Approve cases, view PHI |
| Paralegal | `paralegal` | Manage cases, submit for review |
| Admin Staff | `admin_staff` | View cases, manage users |
| Client | `client` | Own case + documents only |
