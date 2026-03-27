Here's everything you need to set up on GCP/Firebase to make the frontend fully work:

---

## 1. Register a Firebase Web App (get config values)
**Firebase Console → Project Settings → Your Apps → Add App → Web**
- Register app name (e.g. `simpletort-paralegal-dashboard`)
- Copy the config object → paste values into `.env.local`

---

## 2. Enable Firebase Authentication
**Firebase Console → Authentication → Sign-in method → Enable:**
- Email/Password (for staff login)

---

## 3. Set Firestore Security Rules
The frontend's real-time listener reads `cases` directly from Firestore — rules must allow it:

**Firebase Console → Firestore → Rules:**
```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {

    // Helper — check role from staff document
    function userRole() {
      return get(/databases/$(database)/documents/staff/$(request.auth.uid)).data.role;
    }

    function isAdmin() {
      return userRole() in ['admin_staff', 'junior_partner', 'senior_partner', 'system_admin'];
    }

    // Cases — paralegals see only their own, admins see all
    match /cases/{caseId} {
      allow read: if request.auth != null && (
        isAdmin() ||
        resource.data.assignment.assignedParalegal == request.auth.uid
      );
      allow write: if request.auth != null && isAdmin();
    }

    // Staff — authenticated users can read their own profile
    match /staff/{userId} {
      allow read: if request.auth != null && (
        request.auth.uid == userId || isAdmin()
      );
    }

    // Firm settings — read only for authenticated users
    match /firmSettings/{doc} {
      allow read: if request.auth != null;
      allow write: if request.auth != null && userRole() == 'system_admin';
    }
  }
}
```

---

## 4. Add CORS to the Case Development Cloud Run service
The frontend calls your Cloud Run API — it needs to allow requests from Firebase Hosting:

```bash
gcloud run services update case-development \
  --region=us-central1 \
  --project=simpletort-zadroga-dev \
  --set-env-vars="ALLOWED_ORIGINS=https://simpletort-zadroga-dev.web.app,https://simpletort-zadroga-dev.firebaseapp.com"
```

---

## 5. Deploy frontend to Firebase Hosting

```bash
# Install Firebase CLI
npm install -g firebase-tools

# Login
firebase login --no-localhost   # use this flag in Cloud Shell

# Init hosting in the frontend folder
cd "Paralegal dashboard design"
firebase init hosting --project simpletort-zadroga-dev
```

When prompted:
| Question | Answer |
|---|---|
| Public directory | `dist` |
| Single-page app? | `Yes` |
| Overwrite index.html? | `No` |

Then build and deploy:
```bash
# Build
pnpm build

# Deploy
firebase deploy --only hosting --project simpletort-zadroga-dev
```

Your app will be live at:
```
https://simpletort-zadroga-dev.web.app
```

---

## 6. Create staff user records in Firestore

Firebase Auth handles login, but your app reads the **role** from the `staff` collection. After a user signs up, add their role:

```bash
# Create a paralegal user record
gcloud firestore documents create \
  "projects/simpletort-zadroga-dev/databases/simpletort-dev/documents/staff/<FIREBASE-UID>" \
  --fields='role={"stringValue":"paralegal"},isActive={"booleanValue":true},displayName={"stringValue":"Sarah Chen"},activeCaseCount={"integerValue":0},maxCaseload={"integerValue":20}'
```

Replace `<FIREBASE-UID>` with the UID from **Firebase Console → Authentication → Users**.

---

## Summary checklist

| Step | Where | Status |
|---|---|---|
| Register Web App | Firebase Console | Get `.env.local` values |
| Enable Email Auth | Firebase Console | Allow staff login |
| Firestore Rules | Firebase Console | Secure case data |
| CORS on Cloud Run | gcloud CLI | Allow frontend API calls |
| Deploy to Hosting | Firebase CLI | Get a public URL |
| Create staff records | Firestore | Assign roles to users |






----------------------------------------------------------------------------------------------------------------------------------
----------------------------------------------------------------------------------------------------------------------------------









## How It All Works — Simple Explanation

---

## The Big Picture

Think of it like a **law firm's filing room**. When a new case arrives and is ready for a paralegal, someone needs to:
1. **Automatically** pick which paralegal gets the case (Case Assignment Function)
2. **Show** each paralegal their assigned cases on a dashboard (Case Development Service)

These are two separate pieces that work together.

---

## Part 1: Case Assignment Cloud Function

### What it does
Automatically assigns a case to a paralegal the moment it becomes ready — **no human needed**.

### How it gets triggered

```
Lawyer changes case status
        ↓
Firestore saves the change
        ↓
Eventarc detects the change
        ↓
Sends a notification to the Cloud Function
        ↓
Function runs automatically
```

The Eventarc trigger you created is basically a **watchman** sitting outside Firestore. It watches the `cases` collection 24/7. The moment any case document changes, it wakes up the function.

### What happens inside the function (step by step)

**Step 1 — Is this change relevant?**
```
"Did the status just change TO 'Pending Paralegal Review'?"
  → No?  Stop. Do nothing. (e.g. status changed to 'Closed' — not our job)
  → Yes? Continue.
```

**Step 2 — Is it already assigned?**
```
"Does this case already have a paralegal assigned?"
  → Yes? Stop. Don't reassign. (prevents duplicate assignment)
  → No?  Continue.
```

**Step 3 — Pick a paralegal**

The function checks `firmSettings` in Firestore to see which mode is set:

| Mode | How it picks |
|---|---|
| `load_balancing` | Picks the paralegal with the **fewest active cases** (most available) |
| `round_robin` | Takes turns — paralegal 1, then 2, then 3, back to 1... |

In both modes, it skips anyone who:
- Is not active (`isActive = false`)
- Is already at max capacity (`activeCaseCount >= maxCaseload`)

**Step 4 — Write the assignment (all or nothing)**

This is a **Firestore Transaction** — think of it like a bank transfer. Either ALL of these happen together, or NONE of them do:

```
① Write paralegal's ID to cases/ZAD-2024-01-0001/assignment.assignedParalegal
② Increment paralegal's activeCaseCount by 1 (they now have one more case)
③ Add a timeline entry "Case assigned to Sarah Chen on 2026-03-25"
```

Why all-or-nothing? Imagine if step ① succeeded but step ② crashed — the paralegal would have a case but their counter would be wrong. The transaction prevents this.

**Step 5 — Notify the paralegal**

Sends a message to a **Pub/Sub topic** called `assignment-notifications`. Think of Pub/Sub like a text message system — other services can subscribe and get notified when a new assignment happens (e.g. send an email to the paralegal).

### Visual flow
```
Firestore change detected
        ↓
   Is status = "Pending Paralegal Review"? ──No──→ EXIT
        ↓ Yes
   Already assigned? ──Yes──→ EXIT
        ↓ No
   Read firmSettings (load_balance or round_robin)
        ↓
   Find eligible paralegals from staff collection
        ↓
   Pick one
        ↓
   Firestore Transaction:
     - Assign case to paralegal
     - +1 to their activeCaseCount
     - Log timeline event
        ↓
   Publish to Pub/Sub → "Hey Sarah, you got a new case!"
        ↓
        DONE
```

---

## Part 2: Case Development Service (FastAPI)

### What it does
A REST API (a web server) that the **frontend dashboard calls** to get and manage case data. It has two groups of endpoints:

### Group A — Assignment Endpoints (manual controls)

These let admin staff **override** the automatic assignment:

| Endpoint | Who can use | What it does |
|---|---|---|
| `POST /api/v1/cases/{caseId}/assign` | Admin Staff+ | Manually reassign a case to a different paralegal |
| `GET /api/v1/cases/{caseId}/assignment` | Paralegal+ | See who is assigned to a case |
| `GET /api/v1/staff/paralegals/workload` | Paralegal+ | See all paralegals and how many cases each has |

### Group B — Dashboard Endpoint

| Endpoint | Who can use | What it does |
|---|---|---|
| `GET /api/v1/dashboard/cases` | Paralegal+ | Get your list of cases with filters, sorting, pagination |

### How a paralegal loads their dashboard

```
Browser opens dashboard
        ↓
Frontend calls GET /api/v1/dashboard/cases
  (with Authorization: Bearer <firebase-token>)
        ↓
Service verifies the Firebase token
  → Invalid token? Return 401
  → Valid token? Continue
        ↓
Check the user's role
  → Role too low? Return 403
  → Role OK? Continue
        ↓
Query Firestore:
  - Paralegal? → only cases WHERE assignedParalegal == "sarah-uid"
  - Admin?     → all cases (no filter)
        ↓
Apply filters in Python:
  - Status filter (e.g. only "Pending Paralegal Review")
  - Deadline range (e.g. deadlines in next 30 days)
  - Qual score range (e.g. score > 70)
        ↓
Calculate KPI numbers:
  - How many cases total?
  - How many overdue?
  - How many pending my review?
  - Average qual score?
        ↓
Sort the results (by deadline, name, etc.)
        ↓
Return page 1 of 20 results
        ↓
Frontend displays the table
```

### Why filter in Python instead of Firestore?

Firestore has a limitation — you can't combine multiple range filters (`deadline > X AND deadline < Y AND score > Z`) in one query. So we:
1. Fetch all cases for the paralegal from Firestore (one simple query)
2. Filter/sort/paginate them in Python code

---

## How the two pieces connect

```
                    AUTO PATH
                    ──────────────────────────────────────────
Lawyer              Firestore          Eventarc         Cloud Function
updates   ───────→  saves    ────────→  detects  ──────→  assigns case
status              change              change            to paralegal
                    ──────────────────────────────────────────

                    MANUAL PATH
                    ──────────────────────────────────────────
Admin Staff         Case Dev Service    Firestore
clicks    ────────→ POST /assign ──────→ updates
"Reassign"          (validates role)    assignment
                    ──────────────────────────────────────────

                    VIEW PATH
                    ──────────────────────────────────────────
Paralegal           Case Dev Service    Firestore
opens     ────────→ GET /dashboard ────→ queries cases
dashboard           (filters+paginates)  assigned to them
                    ──────────────────────────────────────────
```

---

## Security layer (RBAC)

Every request to the Case Development Service goes through two checks:

```
Request arrives
      ↓
① Authentication — "Are you who you say you are?"
  Verifies the Firebase token in the Authorization header
  → No token or bad token → 403 Forbidden
      ↓
② Authorization — "Are you allowed to do this?"
  Checks role hierarchy:
  paralegal(1) < admin_staff(2) < junior_partner(3) < senior_partner(4) < system_admin(5)
  → Role too low → 403 Forbidden
      ↓
  Execute the request
```

A paralegal can **read** workload and dashboard, but cannot **override** assignments — that requires `admin_staff` or higher.











