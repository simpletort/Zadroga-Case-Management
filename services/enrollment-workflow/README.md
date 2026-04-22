# Enrollment Workflow Service — Module 3

WTC Health Program enrollment sub-workflow and VCF registration tracking for the SimpleTort case management system.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                   Enrollment Workflow Service                    │
│                     (Cloud Run — FastAPI)                        │
├──────────────────┬──────────────────┬───────────────────────────┤
│   WTC Router     │   VCF Router     │   Dashboard Router        │
│  /api/v1/wtc/*   │  /api/v1/vcf/*   │  /api/v1/dashboard/*      │
├──────────────────┴──────────────────┴───────────────────────────┤
│   wtc_workflow.py │ vcf_workflow.py │ deadline_service.py        │
│   task_service.py │ timeline_service.py │ pubsub_service.py      │
└─────────────────────────────┬───────────────────────────────────┘
                               │ Firestore
                    ┌──────────┴──────────┐
                    │   cases/{caseId}    │
                    │   ├── /tasks        │
                    │   └── /timeline     │
                    └─────────────────────┘

┌───────────────────────────────────────────────────────────────────┐
│              Cloud Functions (Gen 2)                              │
├──────────────────────────┬────────────────────────────────────────┤
│  deadline-calculator     │  deadline-alerter                      │
│  Trigger: Firestore      │  Trigger: Cloud Scheduler (daily 8AM) │
│  Event: case written     │  Scans for 90/60/30-day deadlines     │
└──────────────────────────┴────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────┐
│              Cloud Workflows                                      │
│  wtc_enrollment.yaml — Orchestrates full WTC enrollment cycle    │
└───────────────────────────────────────────────────────────────────┘
```

---

## Environment Variables

Set these before running locally or deploying. Copy `.env.example` to `.env`.

| Variable | Required | Default | Description |
|---|---|---|---|
| `GCP_PROJECT_ID` | **YES** | — | GCP project ID |
| `APP_ENV` | NO | `development` | `development` \| `test` \| `production` |
| `FIRESTORE_DATABASE_ID` | NO | `(default)` | Named Firestore database |
| `JWT_AUDIENCE` | prod only | — | Firebase project ID for JWT verification |
| `JWT_ISSUER` | prod only | — | `https://securetoken.google.com/{project}` |
| `PUBSUB_TOPIC_ENROLLMENT` | NO | `enrollment-status-changes` | Pub/Sub topic for status events |
| `PUBSUB_TOPIC_NOTIFICATIONS` | NO | `notification-requests` | Pub/Sub topic for email/SMS alerts |
| `SENDGRID_API_KEY` | prod only | — | SendGrid API key (use Secret Manager in prod) |
| `SENDGRID_FROM_EMAIL` | NO | `noreply@zadlegal.com` | Sender email address |
| `NOTIFICATION_SERVICE_URL` | NO | `http://localhost:8081` | Internal notification service URL |
| `VCF_DEADLINE_YEARS` | NO | `2` | VCF deadline offset from cert date |
| `ALERT_DAYS` | NO | `90,60,30` | Comma-separated deadline alert thresholds |

### Cloud Function–Specific Variables

**deadline-calculator** (same GCP vars + ):
- `PUBSUB_TOPIC_ENROLLMENT` — topic to publish deadline events

**deadline-alerter** (same GCP vars + ):
- `PUBSUB_TOPIC_NOTIFICATIONS` — topic for email alert requests
- `ALERT_DAYS` — override alert thresholds (default: `90,60,30`)

---

## Data Model

Enrollment data is stored in the `cases` collection under the `enrollment` nested map:

```javascript
// cases/{caseId}/enrollment fields
{
  // WTC Health Program
  wtcEnrollmentStatus: "Not Enrolled" | "Application Pending" | "Enrolled" | "Already Enrolled" | "Deceased",
  wtcWorkflowStep: "initial_assessment" | "paralegal_task_created" | "application_submitted" | ...,
  wtcWorkflowTriggeredAt: Timestamp,
  wtcApplicationDate: Timestamp,
  wtcEnrollmentDate: Timestamp,
  wtcMemberId: string,
  wtcNotes: string,
  wtcLastUpdatedAt: Timestamp,
  wtcLastUpdatedBy: string,

  // VCF Registration
  vcfRegistrationStatus: "Not Registered" | "Registration Pending" | "Registered",
  vcfRegistrationStep: "eligibility_review" | "form_preparation" | "submission_pending" | ...,
  vcfClaimNumber: string,
  vcfRegistrationDate: Timestamp,
  vcfWorkflowInitiatedAt: Timestamp,
  vcfLastUpdatedAt: Timestamp,
  vcfLastUpdatedBy: string,

  // Deadline tracking
  vcfFilingDeadline: "YYYY-MM-DD",       // certificationDate + 2 years
  deadlineStatus: "active" | "warning_90" | "warning_60" | "warning_30" | "expired" | "not_set",
  daysUntilDeadline: number,
  deadlineCalculatedAt: Timestamp,
  lastAlertMilestone: 90 | 60 | 30,      // prevents duplicate alerts
  lastAlertSentAt: Timestamp,
}
```

---

## API Reference

All endpoints require `Authorization: Bearer <JWT>` in production.
In `development` mode, auth is bypassed.

### WTC Enrollment

```
POST /api/v1/wtc/trigger
Body: { "case_id": "ZAD-2024-01-0001", "force": false }
→ 200: { triggered, workflow_step, task_id, message }

GET  /api/v1/wtc/{case_id}
→ 200: WTCEnrollmentRecord

PUT  /api/v1/wtc/{case_id}/status
Body: { "status": "Application Pending", "performed_by": "uid", "notes": "..." }
→ 200: { old_status, new_status, timeline_event_id, next_task_id, message }
```

### VCF Registration

```
POST /api/v1/vcf/register
Body: { "case_id": "ZAD-2024-01-0001" }
→ 200: { initiated, registration_step, task_id, message }

GET  /api/v1/vcf/{case_id}
→ 200: VCFRegistrationRecord (includes vcf_filing_deadline, days_until_deadline)

PUT  /api/v1/vcf/{case_id}/status
Body: { "status": "Registered", "vcf_claim_number": "VCF-2024-00123",
        "registration_date": "2024-03-15T00:00:00Z", "performed_by": "uid" }
→ 200: { old_status, new_status, timeline_event_id, vcf_filing_deadline, next_task_id }

GET  /api/v1/vcf/{case_id}/prefill
→ 200: VCFFormPrefillData (pre-filled form data from case record)
```

### Dashboard

```
GET  /api/v1/dashboard/enrollment
     ?paralegal_id=uid&wtc_status=Enrolled&vcf_status=Not+Registered&limit=100
→ 200: EnrollmentDashboardResponse (pipeline counts + case rows)

GET  /api/v1/dashboard/deadlines
     ?status=warning_30&paralegal_id=uid&limit=100
→ 200: list[DeadlineSummaryItem] (sorted by urgency)

GET  /api/v1/dashboard/export
     ?paralegal_id=uid
→ CSV file download
```

---

## Local Development Setup

### Prerequisites
- Python 3.11+
- Google Cloud SDK (`gcloud`)
- Firebase project with Firestore enabled
- `GOOGLE_APPLICATION_CREDENTIALS` pointing to a service account key (or `gcloud auth application-default login`)

### Step 1: Clone and install dependencies

```bash
cd services/enrollment-workflow
python -m venv venv
source venv/bin/activate         # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Step 2: Configure environment

```bash
cp .env.example .env
# Edit .env with your GCP_PROJECT_ID
```

### Step 3: Start the service

```bash
# Option A: uvicorn (recommended for dev — hot reload)
uvicorn app:app --host 0.0.0.0 --port 8080 --reload

# Option B: Python directly
python app.py
```

Service is now at http://localhost:8080
Swagger UI: http://localhost:8080/docs

### Step 4: Test the API locally

```bash
# Trigger WTC workflow
curl -X POST http://localhost:8080/api/v1/wtc/trigger \
  -H "Content-Type: application/json" \
  -d '{"case_id": "your-case-id"}'

# Get VCF status
curl http://localhost:8080/api/v1/vcf/your-case-id

# Get enrollment dashboard
curl "http://localhost:8080/api/v1/dashboard/enrollment?limit=10"

# Get deadline summary (warning cases only)
curl "http://localhost:8080/api/v1/dashboard/deadlines?status=warning_30"
```

### Step 5: Run unit tests

```bash
cd services/enrollment-workflow
pytest tests/ -v --tb=short

# Run with coverage
pip install pytest-cov
pytest tests/ -v --cov=services --cov=models --cov-report=term-missing
```

### Step 6: Test Cloud Functions locally

**deadline-calculator:**
```bash
cd cloud-functions/deadline-calculator
pip install -r requirements.txt
GCP_PROJECT_ID=test pytest tests/ -v

# Run locally with functions-framework
GCP_PROJECT_ID=your-project functions-framework \
  --target=calculate_vcf_deadline \
  --signature-type=cloudevent \
  --port=8081
```

**deadline-alerter:**
```bash
cd cloud-functions/deadline-alerter
pip install -r requirements.txt
GCP_PROJECT_ID=test pytest tests/ -v

# Run locally
GCP_PROJECT_ID=your-project functions-framework \
  --target=deadline_alerter \
  --signature-type=http \
  --port=8082

# Trigger manually
curl -X POST http://localhost:8082
```

---

## Production Deployment

### Prerequisites
- GCP project with billing enabled
- `gcloud` CLI authenticated: `gcloud auth login && gcloud config set project YOUR_PROJECT`
- Artifact Registry repository created (see `infrastructure/setup.sh`)

### Step 1: Run infrastructure setup (ONCE per environment)

```bash
export GCP_PROJECT_ID=your-project-id
export REGION=us-central1
export ENV=prod
bash services/enrollment-workflow/infrastructure/setup.sh
```

This creates: Service accounts, Pub/Sub topics, IAM bindings.
Saves: Firestore index definitions, Eventarc trigger commands, Scheduler job commands.

### Step 2: Store secrets in Secret Manager

```bash
PROJECT=your-project-id

# SendGrid API Key
echo -n "SG.your-actual-key" | \
  gcloud secrets versions add SENDGRID_API_KEY \
  --data-file=- --project=$PROJECT
```

### Step 3: Build and push Docker images

```bash
PROJECT=your-project-id
REGION=us-central1
REPO="${REGION}-docker.pkg.dev/${PROJECT}/simpletort"

# Authenticate Docker to Artifact Registry
gcloud auth configure-docker ${REGION}-docker.pkg.dev

# Build and push enrollment-workflow service
cd services/enrollment-workflow
docker build -t ${REPO}/enrollment-workflow:latest .
docker push ${REPO}/enrollment-workflow:latest

# Build and push deadline-calculator function
cd ../../cloud-functions/deadline-calculator
docker build -t ${REPO}/deadline-calculator:latest .
docker push ${REPO}/deadline-calculator:latest

# Build and push deadline-alerter function
cd ../deadline-alerter
docker build -t ${REPO}/deadline-alerter:latest .
docker push ${REPO}/deadline-alerter:latest
```

### Step 4: Deploy Cloud Run services

```bash
PROJECT=your-project-id
REGION=us-central1
REPO="${REGION}-docker.pkg.dev/${PROJECT}/simpletort"
ENROLL_SA="enrollment-workflow-sa@${PROJECT}.iam.gserviceaccount.com"
CALC_SA="deadline-calculator-sa@${PROJECT}.iam.gserviceaccount.com"

# Deploy enrollment-workflow service
gcloud run deploy enrollment-workflow \
  --image="${REPO}/enrollment-workflow:latest" \
  --region="${REGION}" \
  --platform=managed \
  --no-allow-unauthenticated \
  --service-account="${ENROLL_SA}" \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT},APP_ENV=production,FIRESTORE_DATABASE_ID=(default),PUBSUB_TOPIC_ENROLLMENT=enrollment-status-changes,PUBSUB_TOPIC_NOTIFICATIONS=notification-requests,JWT_AUDIENCE=${PROJECT},JWT_ISSUER=https://securetoken.google.com/${PROJECT}" \
  --memory=512Mi \
  --cpu=1 \
  --timeout=120s \
  --min-instances=1 \
  --max-instances=10 \
  --project="${PROJECT}"

# Deploy deadline-calculator Cloud Function
gcloud run deploy deadline-calculator \
  --image="${REPO}/deadline-calculator:latest" \
  --region="${REGION}" \
  --platform=managed \
  --no-allow-unauthenticated \
  --service-account="${CALC_SA}" \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT},FIRESTORE_DATABASE_ID=(default),PUBSUB_TOPIC_ENROLLMENT=enrollment-status-changes" \
  --memory=256Mi \
  --cpu=1 \
  --timeout=60s \
  --min-instances=0 \
  --max-instances=10 \
  --project="${PROJECT}"

# Deploy deadline-alerter Cloud Function
gcloud run deploy deadline-alerter \
  --image="${REPO}/deadline-alerter:latest" \
  --region="${REGION}" \
  --platform=managed \
  --no-allow-unauthenticated \
  --service-account="${CALC_SA}" \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT},FIRESTORE_DATABASE_ID=(default),PUBSUB_TOPIC_NOTIFICATIONS=notification-requests,PUBSUB_TOPIC_ENROLLMENT=enrollment-status-changes,ALERT_DAYS=90,60,30" \
  --memory=512Mi \
  --cpu=1 \
  --timeout=300s \
  --min-instances=0 \
  --max-instances=1 \
  --project="${PROJECT}"
```

### Step 5: Create Eventarc trigger (deadline-calculator)

```bash
PROJECT=your-project-id
REGION=us-central1
CALC_SA="deadline-calculator-sa@${PROJECT}.iam.gserviceaccount.com"

gcloud eventarc triggers create deadline-calculator-trigger \
  --location="${REGION}" \
  --destination-run-service=deadline-calculator \
  --destination-run-region="${REGION}" \
  --event-filters="type=google.cloud.firestore.document.v1.written" \
  --event-filters="database=(default)" \
  --event-filters-path-pattern="document=cases/{caseId}" \
  --service-account="${CALC_SA}" \
  --project="${PROJECT}"
```

### Step 6: Create Cloud Scheduler job (deadline-alerter)

```bash
PROJECT=your-project-id
REGION=us-central1
SCHEDULER_SA="deadline-alerter-scheduler@${PROJECT}.iam.gserviceaccount.com"

# Get the deployed service URL
ALERTER_URL=$(gcloud run services describe deadline-alerter \
  --region="${REGION}" \
  --format="value(status.url)" \
  --project="${PROJECT}")

# Create daily job at 8 AM ET (1 PM UTC)
gcloud scheduler jobs create http deadline-alerter-daily \
  --location="${REGION}" \
  --schedule="0 13 * * *" \
  --uri="${ALERTER_URL}" \
  --http-method=POST \
  --oidc-service-account-email="${SCHEDULER_SA}" \
  --oidc-token-audience="${ALERTER_URL}" \
  --time-zone="UTC" \
  --description="Daily VCF deadline alert scanner — 90/60/30-day warnings" \
  --project="${PROJECT}"
```

### Step 7: Deploy Cloud Workflow (WTC orchestration)

```bash
PROJECT=your-project-id
REGION=us-central1

gcloud workflows deploy wtc-enrollment \
  --location="${REGION}" \
  --source="services/enrollment-workflow/workflows/wtc_enrollment.yaml" \
  --service-account="enrollment-workflow-sa@${PROJECT}.iam.gserviceaccount.com" \
  --project="${PROJECT}"
```

### Step 8: Deploy Firestore indexes

```bash
# From the auth-rbac service root (where firebase.json lives)
cd services/auth-rbac/backend
firebase deploy --only firestore:indexes --project=your-project-id
```

### Step 9: Grant Cloud Run invoker role to enrollment service

```bash
PROJECT=your-project-id
ENROLL_SA="enrollment-workflow-sa@${PROJECT}.iam.gserviceaccount.com"

# Allow enrollment service to invoke other Cloud Run services
gcloud run services add-iam-policy-binding deadline-calculator \
  --region=us-central1 \
  --member="serviceAccount:${ENROLL_SA}" \
  --role="roles/run.invoker" \
  --project="${PROJECT}"
```

---

## Production Testing

### Step 1: Health check

```bash
SERVICE_URL=$(gcloud run services describe enrollment-workflow \
  --region=us-central1 --format="value(status.url)" --project=YOUR_PROJECT)

curl "${SERVICE_URL}/health"
# Expected: {"status":"healthy","service":"enrollment-workflow","version":"1.0.0"}
```

### Step 2: Get an auth token

```bash
# Get OIDC token for a service account (for API testing in prod)
TOKEN=$(gcloud auth print-identity-token)
```

### Step 3: Test WTC workflow trigger

```bash
# Replace ZAD-2024-01-0001 with a real case ID from your Firestore
curl -X POST "${SERVICE_URL}/api/v1/wtc/trigger" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"case_id": "ZAD-2024-01-0001"}'

# Expected: {"case_id":"...","triggered":true,"workflow_step":"paralegal_task_created","task_id":"...","message":"WTC enrollment workflow triggered..."}
```

### Step 4: Test VCF registration

```bash
# Initiate VCF registration
curl -X POST "${SERVICE_URL}/api/v1/vcf/register" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"case_id": "ZAD-2024-01-0001"}'

# Get VCF status
curl "${SERVICE_URL}/api/v1/vcf/ZAD-2024-01-0001" \
  -H "Authorization: Bearer ${TOKEN}"

# Update to Registration Pending
curl -X PUT "${SERVICE_URL}/api/v1/vcf/ZAD-2024-01-0001/status" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"status": "Registration Pending", "performed_by": "test-user"}'

# Mark as Registered (requires claim number)
curl -X PUT "${SERVICE_URL}/api/v1/vcf/ZAD-2024-01-0001/status" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "Registered",
    "vcf_claim_number": "VCF-2024-00123",
    "registration_date": "2024-03-15T00:00:00Z",
    "performed_by": "test-user"
  }'

# After registration: check that vcf_filing_deadline was auto-calculated
curl "${SERVICE_URL}/api/v1/vcf/ZAD-2024-01-0001" \
  -H "Authorization: Bearer ${TOKEN}"
# Should show vcf_filing_deadline = certificationDate + 2 years
```

### Step 5: Test deadline alerter manually

```bash
ALERTER_URL=$(gcloud run services describe deadline-alerter \
  --region=us-central1 --format="value(status.url)" --project=YOUR_PROJECT)

curl -X POST "${ALERTER_URL}" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token \
    --audiences=${ALERTER_URL})"

# Expected: {"status":"ok","date":"2024-...","stats":{...}}
```

### Step 6: Test deadline calculator via Firestore

Update a case's `medicalInfo.certificationDate` field in Firestore directly.
Within ~30 seconds, the Eventarc trigger fires and `enrollment.vcfFilingDeadline`
is automatically updated in the case document.

```bash
# Verify in Firestore Console or via gcloud
gcloud firestore documents get \
  "projects/YOUR_PROJECT/databases/(default)/documents/cases/ZAD-2024-01-0001" \
  --format=json | jq '.fields.enrollment'
```

### Step 7: Test enrollment dashboard

```bash
# Full pipeline view
curl "${SERVICE_URL}/api/v1/dashboard/enrollment" \
  -H "Authorization: Bearer ${TOKEN}"

# Deadline warnings only
curl "${SERVICE_URL}/api/v1/dashboard/deadlines?status=warning_30" \
  -H "Authorization: Bearer ${TOKEN}"

# Export CSV
curl "${SERVICE_URL}/api/v1/dashboard/export" \
  -H "Authorization: Bearer ${TOKEN}" \
  -o enrollment_export.csv
```

### Step 8: Verify Firestore data integrity

After running the above tests, verify in Firestore Console:
- `cases/{caseId}/enrollment` contains all expected fields
- `cases/{caseId}/tasks` has paralegal tasks created for each step
- `cases/{caseId}/timeline` has events for each status change
- `enrollment.lastAlertMilestone` is set after alerter fires

---

## Workflow Diagrams

### WTC Status Flow
```
                      ┌─────────────────┐
                      │   Not Enrolled  │ ← trigger_wtc_workflow()
                      └────────┬────────┘
                               │ Paralegal creates WTC application
                               ▼
                  ┌────────────────────────┐
                  │   Application Pending  │
                  └────────────┬───────────┘
                               │ WTC program reviews
                               ▼
                  ┌────────────────────────┐
                  │        Enrolled        │ → triggers VCF registration
                  └────────────────────────┘

Edge cases:
  ├─ Already Enrolled → SKIP (log + exit)
  └─ Deceased         → SKIP (log + exit)
```

### VCF Status Flow
```
                    ┌──────────────────┐
                    │  Not Registered  │ ← initiate_vcf_registration()
                    └────────┬─────────┘
                             │ Eligibility review task
                             ▼
               ┌─────────────────────────┐
               │  Registration Pending   │ → Form prep task created
               └────────────┬────────────┘
                             │ Submit to vcf.gov, capture claim #
                             ▼
               ┌─────────────────────────┐
               │       Registered        │ → Deadline calculated
               └─────────────────────────┘   → Confirmation task created
```

### Deadline Alert Flow
```
Cloud Scheduler (daily 8AM ET)
         │
         ▼
  deadline-alerter
         │
         ├─ Scan cases with vcfFilingDeadline
         │
         ├─ days ≤ 90 AND lastAlertMilestone > 90 → 90-day alert
         ├─ days ≤ 60 AND lastAlertMilestone > 60 → 60-day alert  
         └─ days ≤ 30 AND lastAlertMilestone > 30 → 30-day alert
                    │
                    ├─ Create paralegal task (URGENT)
                    ├─ Publish Pub/Sub notification request
                    ├─ Write timeline event
                    └─ Update lastAlertMilestone (prevent duplicates)
```

---

## Troubleshooting

| Problem | Check |
|---|---|
| `401 Unauthorized` in prod | JWT_AUDIENCE and JWT_ISSUER env vars are set correctly |
| Deadline not calculated | Eventarc trigger is connected; check Cloud Run logs for `deadline-calculator` |
| Duplicate alerts sent | `enrollment.lastAlertMilestone` update failed; check alerter logs |
| VCF status transition rejected | Check `VALID_TRANSITIONS` in `vcf_workflow.py` |
| Tasks not created | Check `cases/{caseId}/tasks` sub-collection permissions in Firestore rules |
| Cloud Scheduler job not firing | Verify OIDC token audience matches service URL exactly |

### View logs in production

```bash
# Enrollment workflow service logs
gcloud logs read "resource.type=cloud_run_revision AND resource.labels.service_name=enrollment-workflow" \
  --limit=50 --project=YOUR_PROJECT

# Deadline calculator logs
gcloud logs read "resource.type=cloud_run_revision AND resource.labels.service_name=deadline-calculator" \
  --limit=50 --project=YOUR_PROJECT

# Deadline alerter logs
gcloud logs read "resource.type=cloud_run_revision AND resource.labels.service_name=deadline-alerter" \
  --limit=50 --project=YOUR_PROJECT
```
