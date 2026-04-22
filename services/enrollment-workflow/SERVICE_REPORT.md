# Enrollment Workflow Service — Comprehensive Report

**Version:** 2.0.0 (Generic — formerly WTC/VCF-specific)  
**Language:** Python 3.11 / FastAPI  
**Compute:** GCP Cloud Run  
**Storage:** Google Cloud Firestore  
**Messaging:** Google Cloud Pub/Sub  
**Orchestration:** GCP Cloud Workflows + Cloud Tasks  
**Scheduled Jobs:** Cloud Scheduler → Cloud Functions Gen 2

---

## What This Service Does

The Enrollment Workflow Service manages the two-phase process of getting a litigation client formally enrolled in benefits programs and registered to file claims:

1. **Certification Phase** — Getting the client certified/enrolled in a health program that confirms their medical eligibility (e.g. WTC Health Program). A physician reviews the client's medical history and issues a certification.

2. **Registration Phase** — Once certified, registering the client with the claims fund (e.g. VCF — Victim Compensation Fund) before a hard filing deadline. Missing this deadline permanently bars the client from filing a claim.

This service tracks the status of both phases, creates paralegal tasks at each step, sends deadline alerts, and exposes a dashboard for case managers.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                  Workflow Orchestrator                       │
│  (vcf-enrollment.yaml Cloud Workflow)                        │
│                                                             │
│  Calls:                                                      │
│    GET  /api/v1/enrollment/wtc-status?case_id={}             │
│    PUT  /api/v1/enrollment/wtc-status                        │
│    GET  /api/v1/enrollment/vcf-status?case_id={}             │
│    PUT  /api/v1/enrollment/vcf-status                        │
│    GET  /api/v1/enrollment/deadlines?case_id={}              │
└─────────────────────┬───────────────────────────────────────┘
                      │ OIDC-authenticated HTTP
                      ▼
┌─────────────────────────────────────────────────────────────┐
│            Enrollment Workflow Service (Cloud Run)           │
│                                                              │
│  routers/orchestrator.py     ← adapter endpoints (WTC/VCF)  │
│  routers/enrollment.py       ← generic endpoints            │
│  routers/dashboard.py        ← paralegal dashboard          │
│                                                              │
│  services/certification_workflow.py   ← state machine       │
│  services/registration_workflow.py    ← state machine       │
│  services/deadline_service.py         ← deadline math       │
│  services/task_service.py             ← paralegal tasks     │
│  services/timeline_service.py         ← audit trail         │
└──────────┬──────────────────────────────────────────────────┘
           │ read/write
           ▼
┌────────────────────────┐    ┌──────────────────────────────┐
│     Firestore           │    │  Pub/Sub Topics               │
│                         │    │                              │
│  cases/{id}             │    │  enrollment-status-changes   │
│    .enrollment.*        │    │  notification-requests       │
│  cases/{id}/tasks/*     │    └──────────────────────────────┘
│  cases/{id}/timeline/*  │
└────────────────────────┘
           ▲
           │ triggered by Firestore write events (Eventarc)
┌──────────┴──────────────────────────────────────────────────┐
│  Cloud Functions (Gen 2)                                     │
│                                                              │
│  deadline-calculator/main.py                                 │
│    Trigger: Eventarc on cases/{caseId} document write        │
│    Fires when: certificationStatus→Enrolled OR               │
│                certificationDate changes                     │
│    Does: calculates filingDeadline, writes to Firestore      │
│                                                              │
│  deadline-alerter/main.py                                    │
│    Trigger: Cloud Scheduler HTTP (daily 8 AM ET)             │
│    Does: scans all cases with filingDeadline, fires          │
│           paralegal tasks + email notifications at           │
│           90 / 60 / 30 days before deadline                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Files and What Each Does

### Application Entry

| File | Purpose |
|------|---------|
| `app.py` | FastAPI app with lifespan, CORS, and router registration. Registers 3 routers: enrollment (generic paths), orchestrator (adapter paths), dashboard. |
| `config.py` | Pydantic Settings: reads all env vars. Has `is_production` / `is_development` properties. |
| `middleware/auth.py` | JWT authentication via Google Identity Platform. In development mode, returns a mock staff user so you can test without tokens. |

### Models (Data Shapes)

| File | Purpose |
|------|---------|
| `models/certification_models.py` | Enums and Pydantic schemas for the certification workflow. `CertificationStatus` (NOT_ENROLLED → APPLICATION_PENDING → ENROLLED), `CertificationWorkflowStep`, request/response shapes. |
| `models/registration_models.py` | Enums and Pydantic schemas for the registration workflow. `RegistrationStatus` (NOT_REGISTERED → REGISTRATION_PENDING → REGISTERED), `DeadlineStatus`, dashboard shapes. |

### Services (Business Logic)

| File | Purpose |
|------|---------|
| `services/certification_workflow.py` | **State machine for certification.** Validates transitions, writes to Firestore, creates paralegal tasks, writes timeline events. When status becomes ENROLLED, publishes a `certification.enrolled` Pub/Sub event so the orchestrator can trigger registration automatically. |
| `services/registration_workflow.py` | **State machine for registration.** Same pattern as above. When status becomes REGISTERED, validates `registration_number` is present, then calls `deadline_service.update_case_deadline()` to calculate the filing deadline. |
| `services/deadline_service.py` | **Deadline calculation.** `calculate_filing_deadline(cert_date)` → `cert_date + N years` (default 2) using `dateutil.relativedelta` (handles leap years correctly). `update_case_deadline()` writes the calculated deadline to Firestore. `scan_approaching_deadlines()` is called by the deadline-alerter Cloud Function. |
| `services/task_service.py` | **Paralegal task factory.** Contains full task definitions (title, instructions, due days, priority) for every step in both workflows. `create_certification_task()` and `create_registration_task()` write tasks to `cases/{id}/tasks/*`. |
| `services/timeline_service.py` | **Audit trail writer.** Every status change, task creation, and deadline event writes a document to `cases/{id}/timeline/*`. Used by the case history view in the UI. |

### Routers (API Endpoints)

| File | Purpose |
|------|---------|
| `routers/enrollment.py` | **Generic human-facing endpoints.** Used by the paralegal dashboard and case management UI. Uses program-agnostic paths: `/api/v1/enrollment/certification/*` and `/api/v1/enrollment/registration/*`. |
| `routers/orchestrator.py` | **Adapter endpoints for the workflow orchestrator.** Uses WTC/VCF terminology in paths (`/api/v1/enrollment/wtc-status`, `/vcf-status`, `/deadlines`) because the orchestrator's `vcf-enrollment.yaml` was written using those terms. Internally delegates to the generic certification/registration services. |
| `routers/dashboard.py` | **Dashboard endpoints.** Aggregates enrollment pipeline data for the paralegal dashboard. Supports filtering by paralegal, status, and program. Also provides CSV export. |

### Cloud Functions (Event-Driven)

| File | Purpose |
|------|---------|
| `cloud-functions/deadline-calculator/main.py` | **Triggered by Firestore document writes** (via Eventarc) on `cases/{caseId}`. Fires when `certificationStatus` becomes Enrolled or when `certificationDate` changes. Calculates `filingDeadline = certificationDate + 2 years` and writes it to `enrollment.filingDeadline`. Also writes a timeline event and publishes a Pub/Sub event. |
| `cloud-functions/deadline-alerter/main.py` | **Triggered daily by Cloud Scheduler** (8 AM ET). Scans every case that has `enrollment.filingDeadline` set. For each case within 90/60/30 days of the deadline, creates an urgent paralegal task and publishes an email notification request. Uses `lastAlertMilestone` to prevent duplicate alerts — once a 90-day alert fires, it won't fire again until the 60-day threshold is crossed. |

### Cloud Workflow YAML

| File | Purpose |
|------|---------|
| `workflows/enrollment.yaml` | Cloud Workflows YAML definition. Polls the enrollment service for certification and registration completion. Handles timeouts (30 days for certification, 60 days for registration). Called by the orchestrator's `vcf-enrollment` execution. |

---

## API Reference

### Human-Facing Endpoints (Generic)

#### Certification

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/enrollment/certification/trigger` | Start certification workflow. Idempotent — safe to call multiple times. |
| `GET` | `/api/v1/enrollment/certification/{case_id}` | Get current certification status and step. |
| `PUT` | `/api/v1/enrollment/certification/{case_id}/status` | Advance certification status. Returns 422 for invalid transitions. |

**Certification request body (PUT):**
```json
{
  "new_status": "Application Pending",
  "updated_by": "uid_paralegal_123",
  "certification_date": "2024-03-15",   // required when status = Enrolled
  "notes": "Application submitted to program portal"
}
```

#### Registration

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/enrollment/registration/initiate` | Start registration workflow. Requires certification to exist. |
| `GET` | `/api/v1/enrollment/registration/{case_id}` | Get current registration status. |
| `PUT` | `/api/v1/enrollment/registration/{case_id}/status` | Advance registration status. `registration_number` required for REGISTERED. |
| `GET` | `/api/v1/enrollment/registration/{case_id}/prefill` | Get pre-filled form data from case record. |

---

### Orchestrator Adapter Endpoints

These endpoints are called by the `vcf-enrollment.yaml` Cloud Workflow — **do not rename or restructure these without also updating the orchestrator YAML**.

| Method | Path | Called By | Returns |
|--------|------|-----------|---------|
| `GET` | `/api/v1/enrollment/wtc-status?case_id={}` | vcf-enrollment.yaml | `{ "wtc_enrolled": bool }` |
| `PUT` | `/api/v1/enrollment/wtc-status` | vcf-enrollment.yaml | trigger result |
| `GET` | `/api/v1/enrollment/vcf-status?case_id={}` | vcf-enrollment.yaml | `{ "vcf_registered": bool }` |
| `PUT` | `/api/v1/enrollment/vcf-status` | vcf-enrollment.yaml | trigger result |
| `GET` | `/api/v1/enrollment/deadlines?case_id={}` | vcf-enrollment.yaml | `{ "wtc_deadline": null, "vcf_submission_deadline": "YYYY-MM-DD" }` |

---

## Firestore Data Model

All data lives on the `cases/{caseId}` document under the `enrollment` map:

```
cases/{caseId}/
  enrollment:
    # Certification fields
    certificationStatus:      "Not Enrolled" | "Application Pending" | "Enrolled" | "Already Enrolled" | "Deceased"
    certificationProgram:     "wtc"  (or any program string)
    certificationWorkflowStep: "paralegal_task_created" | "application_pending" | ...
    certificationDate:        "2024-03-15"   (ISO date, set when Enrolled)
    certificationNotes:       "..."
    certificationUpdatedAt:   ISO datetime
    certificationUpdatedBy:   staff UID

    # Registration fields
    registrationStatus:       "Not Registered" | "Registration Pending" | "Registered"
    registrationProgram:      "vcf"  (or any program string)
    registrationWorkflowStep: "registration_initiated" | "submission_pending" | "registered"
    registrationNumber:       "VCF-2024-12345"  (set when Registered)
    registrationNotes:        "..."
    registrationUpdatedAt:    ISO datetime
    registrationUpdatedBy:    staff UID

    # Deadline fields (written by deadline-calculator Cloud Function)
    filingDeadline:           "2026-03-15"   (certificationDate + 2 years)
    deadlineStatus:           "active" | "warning_90" | "warning_60" | "warning_30" | "expired"
    daysUntilDeadline:        450
    deadlineCalculatedAt:     server timestamp
    lastAlertMilestone:       90 | 60 | 30 | null  (tracks which alert was last sent)
    lastAlertSentAt:          server timestamp

  # Tasks subcollection
  tasks/{taskId}:
    taskId, caseId, title, instructions, status, priority
    assignedTo, assignedToRole, dueDate, createdAt, completedAt
    workflowType, workflowStep, metadata

  # Timeline subcollection (audit trail)
  timeline/{eventId}:
    eventId, caseId, timestamp, eventType, description
    performedBy, metadata
```

---

## State Machines

### Certification State Machine

```
                    ┌──────────────────────┐
                    │    trigger()          │
                    └──────────┬───────────┘
                               ▼
                        NOT_ENROLLED
                               │
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
       APPLICATION_PENDING  ALREADY_ENROLLED DECEASED
                │            (terminal)     (terminal)
                │
          ┌─────┴──────┐
          ▼            ▼
       ENROLLED    NOT_ENROLLED   ← rejection/restart
      (terminal     (retry loop)
      + triggers
      registration)
```

When ENROLLED is reached:
- A `certification.enrolled` Pub/Sub event is fired
- The orchestrator picks this up and calls `PUT /api/v1/enrollment/vcf-status` to trigger registration

### Registration State Machine

```
                    ┌──────────────────────┐
                    │    initiate()         │
                    └──────────┬───────────┘
                               ▼
                        NOT_REGISTERED
                               │
                               ▼
                      REGISTRATION_PENDING
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
                REGISTERED          NOT_REGISTERED  ← rejection/retry
               (terminal)
                    │
                    ▼
            deadline calculated
         (certificationDate + 2 years)
                    │
                    ▼
            monitoring tasks created
         (90/60/30-day alerts scheduled)
```

---

## How the Orchestrator Integrates

The **workflow-orchestrator** service runs a GCP Cloud Workflow called `vcf-enrollment`. Here is the exact call sequence:

```
Orchestrator vcf-enrollment.yaml
    │
    ├── GET /internal/workflow-step-config/vcf-enrollment  (orchestrator's own endpoint)
    │   Returns: configurable step parameters and task templates
    │
    ├── GET /api/v1/enrollment/wtc-status?case_id=ABC
    │   Response: { "wtc_enrolled": false }
    │
    ├── PUT /api/v1/enrollment/wtc-status
    │   Body: { "case_id": "ABC", "action": "initiate_enrollment", "updated_by": "workflow-orchestrator" }
    │   → enrollment service creates paralegal tasks, sets certificationStatus = Not Enrolled
    │
    │   [Poll every 24h until wtc_enrolled = true]
    │
    ├── GET /api/v1/enrollment/vcf-status?case_id=ABC
    │   Response: { "vcf_registered": false }
    │
    ├── PUT /api/v1/enrollment/vcf-status
    │   Body: { "case_id": "ABC", "action": "submit_registration", "updated_by": "workflow-orchestrator" }
    │   → enrollment service creates registration tasks, sets registrationStatus = Not Registered
    │
    │   [Poll every 24h until vcf_registered = true]
    │
    └── GET /api/v1/enrollment/deadlines?case_id=ABC
        Response: { "wtc_deadline": null, "vcf_submission_deadline": "2026-03-15" }
        → orchestrator schedules Cloud Tasks reminders at 90/60/30 days
```

The orchestrator also fires `POST /internal/deadline-alerts` on its own service when Cloud Tasks callback fires — this creates a `DEADLINE_REMINDER` task at CRITICAL priority if ≤14 days remain.

---

## Deadline Calculation Flow

This is one of the most critical pieces of logic in the service:

```
1. Paralegal sets certificationStatus = "Enrolled" via PUT /api/v1/enrollment/certification/{id}/status
   with certificationDate = "2024-03-15"

2. Firestore document is updated → Eventarc trigger fires

3. deadline-calculator Cloud Function runs:
   - Reads certificationDate = "2024-03-15"
   - Calculates: filingDeadline = 2024-03-15 + 2 years = "2026-03-15"
     (uses dateutil.relativedelta — handles leap years correctly)
   - Writes to cases/{id}.enrollment.filingDeadline = "2026-03-15"
   - Sets deadlineStatus = "active" (> 90 days remaining)
   - Writes timeline event "DeadlineCalculated"
   - Publishes Pub/Sub event "FilingDeadlineCalculated"

4. Daily Cloud Scheduler fires deadline-alerter at 8 AM ET:
   - Queries all cases WHERE enrollment.filingDeadline != null
   - For each case, calculates days_remaining = filingDeadline - today
   - If days_remaining ≤ 90 AND lastAlertMilestone is null or > 90:
     → Creates URGENT paralegal task
     → Publishes email notification to assigned paralegal + attorney
     → Updates lastAlertMilestone = 90
   - Same logic fires again at 60 and 30 days
   - Once a milestone fires, it NEVER fires again (no-duplicate logic)
```

---

## Paralegal Tasks Created

Each state transition creates a paralegal task. Here is the full list:

### Certification Tasks

| Trigger | Task Created | Priority | Due |
|---------|-------------|----------|-----|
| Workflow triggered | Prepare certification application | HIGH | 7 days |
| Status → Application Pending | Follow up on application status | MEDIUM | 14 days |
| Status → Enrolled | Confirm enrollment and get certification date | HIGH | 3 days |

### Registration Tasks

| Trigger | Task Created | Priority | Due |
|---------|-------------|----------|-----|
| Registration initiated | Prepare registration application package | HIGH | 14 days |
| Status → Registration Pending | Submit and track registration | HIGH | 30 days |
| Status → Registered | Confirm registration and record claim number | HIGH | 5 days |
| Deadline calculated | Set up deadline monitoring (check alerts) | MEDIUM | 7 days |

### Deadline Alert Tasks (from Cloud Function)

| Trigger | Task Created | Priority | Due |
|---------|-------------|----------|-----|
| 90 days before deadline | DEADLINE ALERT: Filing Due in 90 Days | HIGH | 14 days |
| 60 days before deadline | DEADLINE ALERT: Filing Due in 60 Days | HIGH | 10 days |
| 30 days before deadline | DEADLINE ALERT: Filing Due in 30 Days | URGENT | 5 days |
| Orchestrator Cloud Tasks | CRITICAL DEADLINE REMINDER (≤14 days) | CRITICAL | immediate |

---

## What Changed in Version 2.0 (Generalization)

The original service was written with WTC Health Program and VCF-specific terminology hardcoded throughout. This version makes the service generic:

| Old (v1, WTC/VCF-specific) | New (v2, Generic) |
|---------------------------|-------------------|
| `models/wtc_models.py` | `models/certification_models.py` |
| `models/vcf_models.py` | `models/registration_models.py` |
| `WTCEnrollmentStatus` enum | `CertificationStatus` enum |
| `VCFRegistrationStatus` enum | `RegistrationStatus` enum |
| `services/wtc_workflow.py` | `services/certification_workflow.py` |
| `services/vcf_workflow.py` | `services/registration_workflow.py` |
| `routers/wtc.py` (paths: `/api/v1/wtc/*`) | `routers/enrollment.py` (paths: `/api/v1/enrollment/certification/*`) |
| `routers/vcf.py` (paths: `/api/v1/vcf/*`) | `routers/enrollment.py` (paths: `/api/v1/enrollment/registration/*`) |
| *(no adapter)* | `routers/orchestrator.py` (WTC/VCF adapter paths for orchestrator) |
| Firestore field: `wtcEnrollmentStatus` | Firestore field: `certificationStatus` |
| Firestore field: `vcfFilingDeadline` | Firestore field: `filingDeadline` |
| Firestore field: `vcfRegistrationStatus` | Firestore field: `registrationStatus` |
| Cloud Workflow: `wtc_enrollment.yaml` | Cloud Workflow: `enrollment.yaml` |

**The orchestrator adapter is the key design decision**: Rather than changing the orchestrator's `vcf-enrollment.yaml` Cloud Workflow (which would require redeployment of the orchestrator and could break other dependent services), the enrollment service exposes adapter endpoints at the exact paths the orchestrator already calls. These adapter endpoints translate the WTC/VCF-named requests into generic certification/registration operations internally.

---

## Local Development Setup

```bash
cd services/enrollment-workflow

# 1. Create virtual environment
python -m venv venv
source venv/bin/activate   # or venv\Scripts\activate on Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set environment variables
cp .env.example .env
# Edit .env with your GCP project ID

# 4. Authenticate with GCP (for Firestore access)
gcloud auth application-default login

# 5. Start the server
python app.py
# Server starts at http://localhost:8080
# API docs at http://localhost:8080/docs
```

---

## Deployment

```bash
# Build and deploy to Cloud Run
gcloud run deploy enrollment-workflow \
  --source services/enrollment-workflow \
  --region us-east1 \
  --set-env-vars GCP_PROJECT_ID=your-project,FIRESTORE_DATABASE_ID=your-db

# Deploy Cloud Functions
gcloud functions deploy deadline-calculator \
  --gen2 \
  --runtime python311 \
  --trigger-event-filters="type=google.cloud.firestore.document.v1.written" \
  --trigger-event-filters="database=(default)" \
  --trigger-event-filters-path-pattern="document=cases/{caseId}" \
  --region us-east1 \
  --source cloud-functions/deadline-calculator \
  --entry-point calculate_filing_deadline

gcloud functions deploy deadline-alerter \
  --gen2 \
  --runtime python311 \
  --trigger-http \
  --region us-east1 \
  --source cloud-functions/deadline-alerter \
  --entry-point deadline_alerter

# Deploy Cloud Workflow
gcloud workflows deploy enrollment \
  --location us-east1 \
  --source services/enrollment-workflow/workflows/enrollment.yaml
```

---

## Testing Key Flows

```bash
BASE_URL="https://enrollment-workflow-xyz.run.app"

# 1. Trigger certification workflow
curl -X POST $BASE_URL/api/v1/enrollment/certification/trigger \
  -H "Content-Type: application/json" \
  -d '{"case_id": "case_abc", "program": "wtc", "triggered_by": "uid_paralegal"}'

# 2. Check certification status
curl $BASE_URL/api/v1/enrollment/certification/case_abc

# 3. Advance to Application Pending
curl -X PUT $BASE_URL/api/v1/enrollment/certification/case_abc/status \
  -H "Content-Type: application/json" \
  -d '{"new_status": "Application Pending", "updated_by": "uid_paralegal"}'

# 4. Mark as Enrolled (with certification date)
curl -X PUT $BASE_URL/api/v1/enrollment/certification/case_abc/status \
  -H "Content-Type: application/json" \
  -d '{"new_status": "Enrolled", "updated_by": "uid_paralegal", "certification_date": "2024-03-15"}'

# 5. Initiate registration
curl -X POST $BASE_URL/api/v1/enrollment/registration/initiate \
  -H "Content-Type: application/json" \
  -d '{"case_id": "case_abc", "program": "vcf", "initiated_by": "uid_paralegal"}'

# 6. Check deadlines (orchestrator adapter)
curl "$BASE_URL/api/v1/enrollment/deadlines?case_id=case_abc"
# Returns: {"vcf_submission_deadline": "2026-03-15", "wtc_deadline": null}
```

---

## Security Notes

- **PHI Policy**: Never log `firstName`, `lastName`, `email`, `phone`, `dateOfBirth`, `ssn`, or any medical data. Only log `case_id`, status values, and event types.
- **Authentication**: All endpoints require a valid Firebase/Google Identity Platform JWT. The `middleware/auth.py` validates tokens and extracts the staff user. Development mode bypasses auth.
- **Orchestrator calls**: The orchestrator authenticates using OIDC service account tokens, not staff JWTs. The adapter endpoints (`/wtc-status`, `/vcf-status`, `/deadlines`) accept service account tokens.
- **No direct Firestore writes from UI**: All writes go through the service layer, which enforces state machine transitions. Direct Firestore updates from the UI would bypass the validation logic.
