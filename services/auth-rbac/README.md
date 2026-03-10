# Simpletort Legal Portal

Full-stack legal case management system built with React + Firebase.

## Project Structure

```
simpletort-legal-portal/
├── frontend/                  ← React + Vite + Tailwind v4
│   ├── src/
│   │   ├── components/        ← All UI components
│   │   ├── lib/
│   │   │   ├── firebase.ts    ← Firebase SDK init
│   │   │   ├── api.ts         ← Cloud Function wrappers
│   │   │   └── AuthContext.tsx← Real Firebase auth
│   │   ├── App.tsx
│   │   ├── routes.tsx
│   │   └── main.tsx
│   ├── styles/
│   ├── .env.example           ← Copy to .env.local and fill in
│   ├── package.json
│   └── vite.config.ts
│
├── backend/                   ← Firebase project root
│   ├── functions/             ← Python 3.12 Cloud Functions
│   │   ├── api/               ← HTTP endpoints
│   │   ├── auth/              ← RBAC + auth service
│   │   ├── middleware/        ← JWT + HTTP utils
│   │   └── main.py
│   ├── firestore/
│   │   └── firestore.rules    ← Security rules
│   └── firebase.json
│
└── .github/
    └── workflows/
        └── deploy.yml         ← Auto-deploy on push to main
```

## Quick Start (Local)

```bash
# Terminal 1 — Firebase emulators
cd backend
firebase emulators:start

# Terminal 2 — Frontend dev server
cd frontend
cp .env.example .env.local     # fill in your Firebase config
npm install
npm run dev
```

## Deploy to Production

```bash
# Build frontend
cd frontend && npm run build

# Deploy everything
cd ../backend && firebase deploy
```

See `SETUP.md` for full deployment guide including creating your first admin user.

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite, Tailwind CSS v4, React Router v7 |
| Auth | Firebase Authentication + custom JWT claims |
| Backend | Python 3.12 Firebase Cloud Functions |
| Database | Firestore with security rules mirroring RBAC |
| Hosting | Firebase Hosting |

## Roles

| Role | Access |
|---|---|
| Senior Partner | Full system admin |
| Attorney (Junior Partner) | Approve/reject cases, view PHI |
| Paralegal | Manage cases, submit for review |
| Admin Staff | View cases, manage users |
| Client | Own case + documents only |
