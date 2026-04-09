# Case Development Service

**SimpleTort — Zadroga Act / 9-11 VCF Case Management**
Cloud Run | Python 3.11 | FastAPI 0.110 | Firestore | Firebase Auth

Handles all paralegal-facing case workflows: dashboard, case assignment, attorney review submission, communication logging, advanced search, saved filter presets, and CSV export.

---

## Table of Contents

- [Service Functions](#service-functions)
- [Tech Stack](#tech-stack)
- [RBAC Role Hierarchy](#rbac-role-hierarchy)
- [API Endpoints — Quick Reference](#api-endpoints--quick-reference)
- [Endpoint Details](#endpoint-details)
  - [Health Check](#health-check)
  - [Paralegal Dashboard](#paralegal-dashboard)
  - [Case Assignment](#case-assignment)
  - [Attorney Review](#attorney-review)
  - [Communication Log](#communication-log)
  - [Case Search](#case-search)
  - [Filter Presets](#filter-presets)
- [Firestore Collections](#firestore-collections)
- [Configuration](#configuration)
- [Running Locally](#running-locally)
- [Running Tests](#running-tests)

---

## Service Functions

| Function | Description |
|----------|-------------|
| **Paralegal Dashboard** | Paginated, filtered case list scoped to the authenticated paralegal. Admin roles see all cases. Includes live KPI summary: overdue deadlines, pending review count, average qualification score. |
| **Case Assignment** | Manual assignment and re-assignment of cases to paralegals by admin staff. Tracks workload distribution across all paralegals. Maintains atomic `activeCaseCount` counters via Firestore transactions. |
| **Review Pre-flight Checks** | Validates a case is ready for attorney review before submission: checks case status, required document uploads (medical records, proof-of-presence, ID documents), questionnaire completion, and AI summary generation. |
| **Review Submission** | Submits a case for attorney review. Auto-assigns the least-loaded junior partner when no attorney is set. Atomically creates review task, in-app notification, and timeline event. |
| **Communication Log** | Structured log of all case communications across channels (email, call, letter, fax, in-person). Paralegals can view the full history and manually log new entries. |
| **Case Search** | Full-text search across client name, case ID, email, and phone. Twelve combinable filter dimensions including status, case type, assigned staff, VCF deadline range, created date range, qualification score, document completeness, and screening result. Sortable by any column. |
| **CSV Export** | Exports any filtered search result set to a downloadable CSV file with no pagination limit. |
| **Filter Presets** | Per-user saved search configurations stored in Firestore. Users can create, rename, update, and delete presets that restore a full set of search filters in one click. |

---

## Tech Stack

- **Runtime:** Python 3.11, FastAPI 0.110, Uvicorn
- **Database:** Cloud Firestore (NoSQL, database-per-service pattern)
- **Auth:** Firebase Auth — JWT verification via `firebase-admin` SDK
- **Deploy:** Cloud Run (serverless), Cloud Build CI/CD, Artifact Registry
- **Tests:** pytest + `unittest.mock` (no live GCP credentials required)

---

## RBAC Role Hierarchy

Every endpoint enforces a minimum role level. Higher number = more authority.

| Role | Level |
|------|-------|
| `paralegal` | 1 |
| `admin_staff` | 2 |
| `junior_partner` | 3 |
| `senior_partner` | 4 |
| `system_admin` | 5 |

All authenticated requests must supply `Authorization: Bearer <Firebase ID token>`.
Missing or invalid tokens return `403 Forbidden`. Insufficient role returns `403 Forbidden`.

---

## API Endpoints — Quick Reference

| Method | Path | Min Role | Description |
|--------|------|----------|-------------|
| GET | `/health` | None | Liveness / readiness probe |
| GET | `/api/v1/dashboard/cases` | paralegal | Paginated, filterable case list with KPI summary |
| POST | `/api/v1/cases/{caseId}/assign` | admin_staff | Manually assign or re-assign a case |
| GET | `/api/v1/cases/{caseId}/assignment` | paralegal | Get current assignment for a case |
| GET | `/api/v1/staff/paralegals/workload` | paralegal | View caseload across all paralegals |
| GET | `/api/v1/cases/{caseId}/review-preflight` | paralegal | Run pre-flight readiness checks |
| POST | `/api/v1/cases/{caseId}/submit-for-review` | paralegal | Submit case for attorney review |
| GET | `/api/v1/cases/{caseId}/communications` | paralegal | List communication log entries |
| POST | `/api/v1/cases/{caseId}/communications` | paralegal | Log a new communication entry |
| GET | `/api/v1/cases/search` | paralegal | Advanced search + filtering, paginated |
| GET | `/api/v1/cases/search/export` | paralegal | Export filtered cases to CSV |
| GET | `/api/v1/search/presets` | paralegal | List saved filter presets |
| POST | `/api/v1/search/presets` | paralegal | Save a new filter preset |
| PATCH | `/api/v1/search/presets/{preset_id}` | paralegal | Update a filter preset |
| DELETE | `/api/v1/search/presets/{preset_id}` | paralegal | Delete a filter preset |

---

## Endpoint Details

### Health Check

#### `GET /health`
No authentication required. Used by Cloud Run for liveness and readiness probes.

**Response `200`**
```json
{ "status": "ok", "service": "case-development" }
```

---

### Paralegal Dashboard

#### `GET /api/v1/dashboard/cases`
Returns a paginated, filterable list of cases. Paralegals see only their own assigned cases. Admin roles (`admin_staff` and above) see all cases. Response always includes a KPI summary computed from the full filtered set before pagination.

**Query Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `statuses` | `string[]` | — | One or more status values (repeat param for multiple) |
| `case_type` | `string` | — | `all` \| `wtc` \| `vcf` |
| `assignees` | `string[]` | — | Filter by paralegal UID(s) — admin roles only |
| `deadline_from` | `datetime` | — | VCF deadline on or after (ISO 8601) |
| `deadline_to` | `datetime` | — | VCF deadline on or before (ISO 8601) |
| `completeness_min` | `float` | — | Document completeness % minimum (0–100) |
| `completeness_max` | `float` | — | Document completeness % maximum (0–100) |
| `qual_min` | `float` | — | Qualification score minimum (0–100) |
| `qual_max` | `float` | — | Qualification score maximum (0–100) |
| `sort_by` | `string` | `last_activity` | `case_id` \| `client_name` \| `status` \| `case_type` \| `vcf_deadline` \| `doc_completeness_pct` \| `qual_score` \| `last_activity` |
| `sort_dir` | `string` | `desc` | `asc` \| `desc` |
| `page` | `int` | `1` | Page number |
| `page_size` | `int` | `20` | Items per page (max 100) |

**Response `200`**
```json
{
  "summary": {
    "total_assigned": 42,
    "overdue_deadline": 3,
    "pending_review": 8,
    "avg_qual_score": 71.4
  },
  "page": {
    "items": [
      {
        "case_id": "ZAD-2026-01-0001",
        "first_name": "John",
        "last_name": "Doe",
        "status": "Pending Paralegal Review",
        "case_type": "WTC",
        "vcf_deadline": "2026-09-11T00:00:00Z",
        "doc_completeness_pct": 80.0,
        "qual_score": 75.0,
        "last_activity": "2026-04-01T12:00:00Z",
        "assigned_paralegal": "sarah-chen-uid",
        "is_flagged": false
      }
    ],
    "total": 42,
    "page": 1,
    "page_size": 20,
    "total_pages": 3
  }
}
```

---

### Case Assignment

#### `POST /api/v1/cases/{caseId}/assign`
Manually assigns or re-assigns a case to a different paralegal. Requires `admin_staff` or higher.

**Path Parameter:** `caseId` — Case ID (e.g. `ZAD-2026-01-0001`)

**Request Body**
```json
{
  "paralegal_id": "sarah-chen-uid",
  "reason": "Reassigned due to caseload balancing"
}
```

**Response `200`**
```json
{
  "case_id": "ZAD-2026-01-0001",
  "assignment": {
    "assigned_paralegal": "sarah-chen-uid",
    "assigned_paralegal_name": "Sarah Chen",
    "assignment_date": "2026-04-07T10:00:00Z"
  },
  "overridden_from": "previous-paralegal-uid"
}
```

**Side effects (atomic Firestore transaction):**
- Decrements `activeCaseCount` on the previous paralegal
- Updates case assignment fields
- Increments `activeCaseCount` on the new paralegal
- Appends a timeline event to the case

---

#### `GET /api/v1/cases/{caseId}/assignment`
Returns the current assignment details for a case, including the paralegal's display name.

**Response `200`**
```json
{
  "case_id": "ZAD-2026-01-0001",
  "assignment": {
    "assigned_paralegal": "sarah-chen-uid",
    "assigned_paralegal_name": "Sarah Chen",
    "assignment_date": "2026-04-01T09:00:00Z"
  },
  "overridden_from": null
}
```

---

#### `GET /api/v1/staff/paralegals/workload`
Returns all paralegals sorted by `active_case_count` descending (busiest first). Used to inform manual reassignment decisions.

**Response `200`**
```json
{
  "paralegals": [
    {
      "user_id": "sarah-chen-uid",
      "display_name": "Sarah Chen",
      "active_case_count": 12,
      "max_caseload": 30,
      "is_active": true
    }
  ]
}
```

---

### Attorney Review

#### `GET /api/v1/cases/{caseId}/review-preflight`
Runs all pre-flight readiness checks and returns results without making any changes. Call this before showing the "Submit for Review" button to indicate which requirements are unmet.

**Pre-flight checks performed:**

| Check Name | Passes When |
|------------|-------------|
| `case_status` | Status is `Pending Paralegal Review` |
| `document_medical_records` | At least one clean uploaded medical record document |
| `document_proof_of_presence` | At least one clean proof-of-presence document |
| `document_id_documents` | At least one clean ID document |
| `questionnaire_complete` | `cases/{caseId}.questionnaireComplete == true` |
| `ai_summary_generated` | `cases/{caseId}.aiSummaryGenerated == true` |

**Response `200`**
```json
{
  "case_id": "ZAD-2026-01-0001",
  "all_passed": false,
  "checks": [
    { "name": "case_status",                "passed": true,  "detail": null },
    { "name": "document_medical_records",   "passed": true,  "detail": null },
    { "name": "document_proof_of_presence", "passed": false, "detail": "No clean proof-of-presence document on file." },
    { "name": "document_id_documents",      "passed": true,  "detail": null },
    { "name": "questionnaire_complete",     "passed": true,  "detail": null },
    { "name": "ai_summary_generated",       "passed": false, "detail": "AI summary has not been generated yet." }
  ]
}
```

---

#### `POST /api/v1/cases/{caseId}/submit-for-review`
Submits the case for attorney review. Pre-flight checks are re-run server-side. Returns `HTTP 422` if any check fails.

**Response `200`**
```json
{
  "case_id": "ZAD-2026-01-0001",
  "status": "Pending Attorney Review",
  "submitted_at": "2026-04-07T10:00:00Z",
  "submitted_by": "sarah-chen-uid",
  "notified_attorney_id": "james-miller-uid",
  "task_id": "task-uuid",
  "auto_assigned_attorney_id": "james-miller-uid"
}
```

`auto_assigned_attorney_id` is set when no attorney was previously assigned — the service automatically assigns the least-loaded `junior_partner`.

**Side effects (atomic Firestore batch):**
- Updates case status → `Pending Attorney Review`
- Records `submittedForReviewAt` and `submittedForReviewBy`
- Writes attorney assignment if auto-assigned
- Appends a timeline event
- Creates a review task at `cases/{caseId}/tasks/{taskId}`
- Creates a notification document at `notifications/{notifId}`

---

### Communication Log

#### `GET /api/v1/cases/{caseId}/communications`
Returns a paginated log of all communications for a case, sorted by most recent first.

**Query Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `channel` | `string` | — | Filter by: `Email` \| `Call` \| `Letter` \| `Fax` \| `In Person` |
| `page` | `int` | `1` | Page number |
| `page_size` | `int` | `20` | Items per page (max 100) |

**Response `200`**
```json
{
  "items": [
    {
      "comm_id": "uuid",
      "channel": "Call",
      "direction": "Outbound",
      "subject": "Status update",
      "body": "Called client to confirm document submission.",
      "from_address": "paralegal@simpletort.com",
      "to": "client@example.com",
      "delivery_status": null,
      "is_automated": false,
      "logged_by": "sarah-chen-uid",
      "template_id": null,
      "external_message_id": null,
      "sent_at": "2026-04-07T10:00:00Z"
    }
  ],
  "total": 14,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

---

#### `POST /api/v1/cases/{caseId}/communications`
Logs a new manually-recorded communication entry.

**Request Body**
```json
{
  "channel": "Call",
  "direction": "Outbound",
  "subject": "Status update",
  "body": "Called client to confirm document submission.",
  "from_address": "paralegal@simpletort.com",
  "to": "client@example.com"
}
```

**Response `201`** — `CommunicationEntry` (same shape as items above)

**Side effects (atomic Firestore batch):**
- Writes communication document to `cases/{caseId}/communications/{commId}`
- Appends a timeline event to the parent case
- Updates `updatedAt` on the case

---

### Case Search

#### `GET /api/v1/cases/search`
Advanced search across all cases (scoped to the paralegal's own cases; admins see all). Supports full-text search and twelve combinable filter dimensions.

**Full-text search** (`?q=`) performs a case-insensitive substring match across:
- Client first name + last name
- Case ID
- Email address
- Phone number

**Query Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `q` | `string` | — | Full-text query |
| `statuses` | `string[]` | — | One or more status values (repeat param) |
| `case_type` | `string` | — | `all` \| `wtc` \| `vcf` |
| `assignees` | `string[]` | — | Paralegal UID(s) — admin roles only |
| `attorney` | `string[]` | — | Attorney UID(s) — admin roles only |
| `deadline_from` | `datetime` | — | VCF deadline on or after (ISO 8601) |
| `deadline_to` | `datetime` | — | VCF deadline on or before (ISO 8601) |
| `created_from` | `datetime` | — | Case created on or after (ISO 8601) |
| `created_to` | `datetime` | — | Case created on or before (ISO 8601) |
| `completeness_min` | `float` | — | Document completeness % minimum (0–100) |
| `completeness_max` | `float` | — | Document completeness % maximum (0–100) |
| `qual_min` | `float` | — | Qualification score minimum (0–100) |
| `qual_max` | `float` | — | Qualification score maximum (0–100) |
| `screening_result` | `string` | — | e.g. `pass` \| `fail` \| `pending` |
| `sort_by` | `string` | `last_activity` | `case_id` \| `client_name` \| `status` \| `case_type` \| `vcf_deadline` \| `doc_completeness_pct` \| `qual_score` \| `last_activity` \| `created_at` |
| `sort_dir` | `string` | `desc` | `asc` \| `desc` |
| `page` | `int` | `1` | Page number |
| `page_size` | `int` | `20` | Items per page (max 100) |

**Response `200`**
```json
{
  "page": {
    "items": [
      {
        "case_id": "ZAD-2026-01-0001",
        "first_name": "John",
        "last_name": "Doe",
        "email": "john.doe@example.com",
        "phone": "555-1234",
        "status": "Pending Paralegal Review",
        "case_type": "WTC",
        "vcf_deadline": "2026-09-11T00:00:00Z",
        "doc_completeness_pct": 80.0,
        "qual_score": 75.0,
        "screening_result": "pass",
        "last_activity": "2026-04-01T12:00:00Z",
        "created_at": "2025-06-15T09:00:00Z",
        "assigned_paralegal": "sarah-chen-uid",
        "assigned_attorney": "james-miller-uid",
        "is_flagged": false
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 20,
    "total_pages": 1
  }
}
```

---

#### `GET /api/v1/cases/search/export`
Exports all matching cases as a downloadable CSV file. Accepts the same filter and sort parameters as `/cases/search` — `page` and `page_size` are ignored (all matching rows are returned).

**Response `200`**
- Content-Type: `text/csv`
- Content-Disposition: `attachment; filename=cases_export.csv`

**CSV columns:** `case_id`, `first_name`, `last_name`, `email`, `phone`, `status`, `case_type`, `screening_result`, `qual_score`, `doc_completeness_pct`, `vcf_deadline`, `created_at`, `last_activity`, `assigned_paralegal`, `assigned_attorney`

---

### Filter Presets

Filter presets are stored per-user in Firestore at `staff/{uid}/searchPresets/{presetId}`. Each preset stores a complete set of search filter values that can be recalled by name.

#### `GET /api/v1/search/presets`
Lists all saved presets for the authenticated user, ordered by creation date.

**Response `200`**
```json
{
  "presets": [
    {
      "preset_id": "uuid",
      "name": "High-Score WTC Cases",
      "filters": {
        "case_type": "wtc",
        "qual_min": 70.0,
        "statuses": ["Pending Paralegal Review", "Pending Attorney Review"],
        "sort_by": "qual_score",
        "sort_dir": "desc"
      },
      "created_at": "2026-04-01T09:00:00Z",
      "updated_at": "2026-04-01T09:00:00Z"
    }
  ]
}
```

---

#### `POST /api/v1/search/presets`
Saves a new filter preset for the current user.

**Request Body**
```json
{
  "name": "High-Score WTC Cases",
  "filters": {
    "case_type": "wtc",
    "qual_min": 70.0,
    "statuses": ["Pending Paralegal Review"],
    "sort_by": "qual_score",
    "sort_dir": "desc"
  }
}
```

**Response `201`** — `FilterPreset` (same shape as items in list response above)

---

#### `PATCH /api/v1/search/presets/{preset_id}`
Updates the name and/or filters of an existing preset.

**Request Body** — same shape as POST

**Response `200`** — updated `FilterPreset`

**Response `404`** — if preset does not exist

---

#### `DELETE /api/v1/search/presets/{preset_id}`
Deletes a saved preset.

**Response `204`** — No content

**Response `404`** — if preset does not exist

---

## Firestore Collections

| Collection Path | Purpose |
|----------------|---------|
| `cases` | Main case documents (status, assignment, leadData, qualification, enrollment) |
| `cases/{caseId}/documents` | Uploaded files with virus scan status |
| `cases/{caseId}/communications` | Communication log entries |
| `cases/{caseId}/timeline` | Timestamped case event history |
| `cases/{caseId}/tasks` | Review / action tasks assigned to staff |
| `staff` | Staff profiles: role, displayName, activeCaseCount, maxCaseload, isActive |
| `staff/{uid}/searchPresets` | Per-user saved search filter presets |
| `notifications` | In-app notifications (e.g. new review task for attorneys) |

---

## Configuration

Environment variables — set in Cloud Run; override locally via `.env.dev`:

| Variable | Default | Description |
|----------|---------|-------------|
| `GCP_PROJECT_ID` | `simpletort-prod` | Google Cloud project ID |
| `FIRESTORE_DATABASE_ID` | `(default)` | Firestore database instance |
| `FIREBASE_SERVICE_ACCOUNT_KEY_PATH` | `/secrets/firebase-sa-key.json` | Firebase SA key (Secret Manager volume mount) |
| `ENVIRONMENT` | `production` | Set to `dev` to enable `/docs` Swagger UI |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `ALLOWED_ORIGINS` | `https://staff.simpletort.com` | Comma-separated CORS allowed origins |

---

## Running Locally

```bash
cd services/case-development

# Install dependencies
pip install -r requirements.txt

# Start with hot-reload (Swagger UI available at /docs)
ENVIRONMENT=dev uvicorn main:app --reload --port 8080
```

---

## Running Tests

```bash
cd services/case-development
python -m pytest -v
```

All tests mock Firestore and Firebase Auth. No live GCP credentials required.

| Test File | What it covers |
|-----------|----------------|
| `tests/test_assignment.py` | Manual assign, re-assign, workload, RBAC enforcement |
| `tests/test_dashboard.py` | Filtering, sorting, pagination, KPI summary, admin vs paralegal scoping |
| `tests/test_communication.py` | List / create communications, channel filter, pagination, timestamp handling |
| `tests/test_review.py` | All pre-flight checks, submission workflow, auto attorney assignment, atomic batch |
| `tests/test_search.py` | Full-text search, all 12 filter types, sort, pagination, CSV export, preset CRUD, RBAC |
