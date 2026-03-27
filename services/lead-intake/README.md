# ZAD Module 1 — Lead Intake & Automated Screening

## Architecture Overview

```
Marketing Partner
      │
      ▼ POST /api/v1/leads  (JWT Bearer)
┌─────────────────────────────────────────┐
│         Cloud Run (FastAPI)             │
│                                         │
│  1. JWT Auth (verify_jwt)               │
│  2. Rate Limit (100/min per partner)    │
│  3. Pydantic validation                 │
│  4. Domain validation (VCF dates)       │
│  5. Idempotency check (requestId)       │
│  6. Duplicate check (email AND phone)   │
│  7. Firestore case create (atomic txn)  │
│     └─ ZAD-YYYY-MM-XXXX ID generation  │
│  8. Pub/Sub publish → lead-created      │
│  9. Cloud Tasks → 48hr followup task    │
│  10. Welcome email + SMS                │
│  11. Return 201 { leadId, status }      │
└─────────────────────────────────────────┘
      │ Pub/Sub: lead-created
      ├──────────────────────────────────┐
      ▼                                  ▼
┌──────────────────┐        ┌────────────────────────┐
│  vcf_screener    │        │ notification_dispatcher │
│  (Cloud Fn 2)    │        │  (Cloud Fn 2)           │
│                  │        │                         │
│  Rule engine:    │        │  SendGrid → welcome     │
│  R01 Site check  │        │  email template         │
│  R02 Date window │        │                         │
│  R03 WTC program │        │  Twilio → welcome SMS   │
│  R04 Prior atty  │        │                         │
│  R05 Completeness│        │  Update Firestore        │
│                  │        │  notificationStatus     │
│  → ELIGIBLE /    │        └────────────────────────┘
│    INELIGIBLE /  │
│    NEEDS_REVIEW  │
│  → Update case   │
│  → Pub/Sub:      │
│    lead-screened │
└──────────────────┘

Cloud Tasks Queue (48hr delay):
  POST /internal/tasks/followup → follow-up handler

Firestore:
  /cases/{ZAD-YYYY-MM-XXXX}
  /counters/{ZAD-YYYY-MM}
  /partners/{partnerId}

Admin UI:
  React + Firebase Hosting
  → Real-time Firestore reads
  → Status updates
  → VCF screening detail view
```

## Project Structure

```
zad_module1/
├── api/                          # Cloud Run FastAPI service
│   ├── main.py                   # App entrypoint, middleware, exception handlers
│   ├── config.py                 # Settings (pydantic-settings)
│   ├── logging_config.py         # Structured logging, PHI-safe helpers
│   ├── requirements.txt
│   ├── routers/
│   │   └── leads.py              # POST/GET /api/v1/leads
│   ├── models/
│   │   └── lead.py               # Pydantic models (request, response, Firestore doc)
│   ├── services/
│   │   ├── validation.py         # Domain rules (date window, location)
│   │   ├── duplicate_detection.py
│   │   ├── case_service.py       # Firestore write + atomic ID generation
│   │   ├── pubsub_service.py
│   │   ├── tasks_service.py      # Cloud Tasks 48hr scheduling
│   │   ├── notification_service.py  # SendGrid + Twilio
│   │   └── firestore_client.py   # Shared DB client
│   └── middleware/
│       ├── auth.py               # JWT verification + JWKS cache
│       └── rate_limiter.py       # slowapi per-partner rate limiting
├── functions/
│   ├── vcf_screener/
│   │   └── main.py               # VCF rule engine Cloud Function
│   └── notification_dispatcher/
│       └── main.py               # SendGrid + Twilio Cloud Function
├── openapi/
│   └── openapi.yaml              # OpenAPI 3.0 spec
├── firestore/
│   ├── schema.md                 # Schema documentation + composite indexes
│   └── firestore.rules           # Security rules (no direct client writes)
├── tests/
│   ├── unit/
│   │   └── test_validation.py
│   └── integration/
│       └── test_leads_endpoint.py
├── admin_ui/                     # React Admin UI → Firebase Hosting
│   ├── src/
│   │   ├── App.jsx               # Dashboard, LeadsTable, CaseDetail
│   │   ├── main.jsx
│   │   ├── index.css
│   │   └── services/
│   │       └── firebaseService.js
│   ├── package.json
│   └── vite.config.js
├── infrastructure/
│   ├── Dockerfile
│   └── cloudbuild.yaml
├── firebase.json
├── .env.example
└── README.md
```

## Setup

### 1. GCP Project Setup

```bash
# Enable required APIs
gcloud services enable \
  run.googleapis.com \
  cloudfunctions.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  cloudtasks.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com

# Create Firestore in Native mode
gcloud firestore databases create --location=us-central1

# Create Pub/Sub topics
gcloud pubsub topics create lead-created
gcloud pubsub topics create lead-screened

# Create Cloud Tasks queue
gcloud tasks queues create lead-followup-queue --location=us-central1
```

### 2. Service Accounts

```bash
# Cloud Run service account
gcloud iam service-accounts create lead-intake-sa \
  --display-name="Lead Intake Service Account"

# Grant Firestore + Pub/Sub + Cloud Tasks permissions
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:lead-intake-sa@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/datastore.user"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:lead-intake-sa@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/pubsub.publisher"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:lead-intake-sa@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/cloudtasks.enqueuer"
```

### 3. Secrets

```bash
# Store sensitive values in Secret Manager
echo -n "SG.your_key" | gcloud secrets create SENDGRID_API_KEY --data-file=-
echo -n "ACxxxxxxx" | gcloud secrets create TWILIO_ACCOUNT_SID --data-file=-
echo -n "your_token" | gcloud secrets create TWILIO_AUTH_TOKEN --data-file=-
```

### 4. Firestore Composite Indexes

```bash
# Deploy via firebase CLI
firebase deploy --only firestore:indexes
```

Required indexes (add to firestore.indexes.json):
- `cases`: `email ASC, phone ASC`
- `cases`: `partnerId ASC, createdAt DESC`
- `cases`: `status ASC, createdAt DESC`

### 5. Local Development

```bash
cd api
cp ../.env.example .env
# Edit .env with your values

pip install -r requirements.txt
uvicorn main:app --reload --port 8080

# API docs available at:
# http://localhost:8080/api/v1/docs
```

### 6. Run Tests

```bash
pytest tests/unit/ -v
pytest tests/integration/ -v
```

### 7. Deploy

```bash
# Deploy all via Cloud Build
gcloud builds submit --config infrastructure/cloudbuild.yaml

# Or manual Cloud Run deploy
gcloud run deploy zad-lead-intake \
  --source . \
  --region us-central1 \
  --no-allow-unauthenticated
```

## API Quick Reference

### POST /api/v1/leads

```bash
curl -X POST https://api.zad.example.com/api/v1/leads \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{
    "firstName": "John",
    "lastName": "Doe",
    "email": "john@example.com",
    "phone": "+12125551234",
    "exposureLocation": "World Trade Center",
    "exposureDates": {"start": "2001-09-11", "end": "2001-12-31"},
    "wtcHealthProgramStatus": "enrolled",
    "priorAttorney": false,
    "marketingSource": "google_ads"
  }'

# Response 201:
# {
#   "leadId": "ZAD-2025-03-0001",
#   "status": "New Lead",
#   "vcfScreeningStatus": "pending",
#   "requestId": "550e8400-...",
#   "timestamp": "2025-03-15T10:00:00Z"
# }
```

## Key Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| Framework | FastAPI | Async, Pydantic v2 built-in, auto OpenAPI |
| Firestore ID generation | Atomic transaction + counter doc | Prevents race conditions, human-readable IDs |
| Duplicate detection | email AND phone | Reduces false positives vs OR |
| Auth | JWT + JWKS | Stateless, works with any OAuth2 provider |
| Rate limiting | slowapi (per partner_id) | Low overhead, Redis not needed for 100/min |
| PHI logging | Field-level exclusion | No PII ever written to Cloud Logging |
| Notifications | Non-fatal (try/catch) | Case creation succeeds even if email fails |
| VCF Screening | Async via Pub/Sub | Decoupled, retryable, doesn't block API response |
| 48hr follow-up | Cloud Tasks (deterministic name) | Idempotent, exact scheduling, no cron needed |

## PHI Policy Summary

- **Never log**: firstName, lastName, email, phone, address, DOB, SSN
- **Safe to log**: caseId, partnerId, requestId, status, error codes, metrics
- **Pub/Sub messages**: contain no PII — only caseId + metadata
- **Cloud Tasks payloads**: contain only caseId — handler fetches PII from Firestore
- **Firestore Security Rules**: no direct client writes to cases collection
