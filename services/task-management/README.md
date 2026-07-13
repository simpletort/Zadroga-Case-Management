# Task Management Service

Manages tasks attached to Zadroga Act / 9/11 VCF cases. Staff create, assign, progress, and close tasks that drive the case workflow — from initial intake through settlement disbursement.

---

## Stack

- **Runtime:** Python 3.11, FastAPI 0.110, Cloud Run
- **Database:** Cloud Firestore — collection `cases/{caseId}/tasks/{taskId}`
- **Reminders:** Cloud Tasks schedules a callback 24 h before a task's due date
- **Auth:** Firebase Auth (staff) via API Gateway header, or Google OIDC for service-to-service calls

---

## Authentication

Every request (except `/health` and `/internal/reminders`) must be authenticated.

| Method | Header | Used by |
|---|---|---|
| API Gateway | `x-apigateway-api-userinfo: <base64 claims>` | Frontend via GCP API Gateway |
| Bearer token | `Authorization: Bearer <firebase-jwt>` | Direct staff calls (dev/staging) |
| OIDC | `Authorization: Bearer <google-oidc-token>` | Service-to-service (Cloud Tasks) |

### Role hierarchy

Roles are resolved from the authenticated token. Higher numbers can do everything lower numbers can.

| Role | Level |
|---|---|
| `admin_staff` | 1 |
| `paralegal` | 2 |
| `junior_partner` | 3 |
| `senior_partner` | 4 |
| `system_admin` | 5 |

---

## Endpoints

### Health

#### `GET /health`

Returns service status. No authentication required.

**Response `200`**
```json
{ "status": "ok", "service": "task-management" }
```

---

### Tasks

#### `POST /api/v1/tasks`

Creates a new task and attaches it to a case. If `dueAt` is provided, schedules a Cloud Tasks reminder 24 h before the due date.

**Minimum required role:** `admin_staff`

**Request body**
```json
{
  "caseId": "ZAD-2026-05-0001",       // required
  "title": "Review medical records",   // required
  "description": "...",                // optional
  "taskType": "review_medical_summary",// optional, default: "generic"
  "priority": "high",                  // optional, default: "medium"
  "assignedTo": "uid-123",             // optional — Firebase UID
  "assignedToRole": "paralegal",       // optional — role to assign to
  "dueAt": "2026-07-01T00:00:00Z",    // optional — ISO 8601 UTC
  "workflowExecutionId": "wf-abc",     // optional — links task to a workflow
  "metadata": {}                       // optional — arbitrary key/value
}
```

**`taskType` values**

| Category | Values |
|---|---|
| Lead & onboarding | `complete_questionnaire`, `upload_documents`, `sign_retainer` |
| Medical | `review_medical_summary`, `verify_qualification_score` |
| Enrollment | `confirm_wtc_enrollment`, `submit_vcf_registration`, `check_enrollment_deadline` |
| Case development | `assign_paralegal`, `review_case_file`, `attorney_approval` |
| Substitution of counsel | `generate_substitution_form`, `request_prior_files`, `obtain_signature` |
| Claim & settlement | `submit_vcf_claim`, `track_claim_status`, `process_award_letter`, `prepare_settlement_statement`, `disburse_funds` |
| Generic / admin | `generic`, `deadline_reminder` |

**`priority` values:** `low`, `medium`, `high`, `critical`

**Response `201`** — [TaskResponse](#taskresponse)

---

#### `GET /api/v1/tasks/{taskId}`

Fetches a single task by ID. Optionally scoped to a case for an extra integrity check.

**Minimum required role:** `admin_staff`

**Query parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `caseId` | string | No | When provided, returns 404 if the task does not belong to this case |

**Response `200`** — [TaskResponse](#taskresponse)

**Response `404`** — task not found (or does not belong to the given `caseId`)

---

#### `PATCH /api/v1/tasks/{taskId}`

Updates editable fields on a task (title, description, priority, due date, metadata). If `dueAt` is changed, reschedules the Cloud Tasks reminder.

**Minimum required role:** `admin_staff`

**Query parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `caseId` | string | Yes | Case the task belongs to |

**Request body** — all fields optional; only provided fields are updated
```json
{
  "title": "Updated title",
  "description": "New description",
  "priority": "critical",
  "dueAt": "2026-08-15T09:00:00Z",
  "metadata": { "vcfClaimId": "VCF-999" }
}
```

**Response `200`** — [TaskResponse](#taskresponse)

---

#### `POST /api/v1/tasks/{taskId}/start`

Transitions a task from `pending` or `overdue` to `in_progress`.

**Minimum required role:** `admin_staff`

**Query parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `caseId` | string | Yes | Case the task belongs to |

**Response `200`** — [TaskResponse](#taskresponse)

**Response `409`** — task is not in a startable status

---

#### `POST /api/v1/tasks/{taskId}/complete`

Marks a task as `completed`. Records who completed it and optional notes.

**Minimum required role:** `admin_staff`

**Query parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `caseId` | string | Yes | Case the task belongs to |

**Request body**
```json
{
  "completedBy": "uid-123",              // required — Firebase UID of the staff member
  "completionNotes": "Filed with VCF.",  // optional
  "metadata": {}                         // optional — merged into task metadata
}
```

**Response `200`** — [TaskResponse](#taskresponse)

**Response `409`** — task is already completed or skipped

---

#### `POST /api/v1/tasks/{taskId}/skip`

Marks a task as `skipped` with a mandatory reason. Used when a task is intentionally bypassed (e.g. client already enrolled via another firm).

**Minimum required role:** `junior_partner`

**Query parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `caseId` | string | Yes | Case the task belongs to |

**Request body**
```json
{
  "reason": "Client previously enrolled via prior counsel."  // required
}
```

**Response `200`** — [TaskResponse](#taskresponse)

**Response `403`** — caller's role is below `junior_partner`

**Response `409`** — task is already in a terminal status

---

#### `POST /api/v1/tasks/{taskId}/assign`

Assigns a task to a specific staff member and/or a role. A user can reassign a task to themselves at any role level; assigning to a different user requires `junior_partner` or above.

**Minimum required role:** `admin_staff` (self-assignment) / `junior_partner` (other user)

**Query parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `caseId` | string | Yes | Case the task belongs to |

**Request body** — at least one field required
```json
{
  "assignedTo": "uid-456",    // optional — Firebase UID to assign to
  "assignedToRole": "paralegal" // optional — role label for display
}
```

**Response `200`** — [TaskResponse](#taskresponse)

**Response `403`** — assigning to another user without `junior_partner` role

---

#### `DELETE /api/v1/tasks/{taskId}`

Permanently deletes a task. Intended for data-correction only; normal closure should use `complete` or `skip`.

**Minimum required role:** `senior_partner`

**Query parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `caseId` | string | Yes | Case the task belongs to |

**Response `204`** — no content

**Response `403`** — caller's role is below `senior_partner`

**Response `404`** — task not found

---

### Case task list

#### `GET /api/v1/cases/{caseId}/tasks`

Returns all tasks for a case, with optional filtering.

**Minimum required role:** `admin_staff`

**Query parameters**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `status` | string | No | — | Filter by status: `pending`, `in_progress`, `completed`, `skipped`, `overdue` |
| `priority` | string | No | — | Filter by priority: `low`, `medium`, `high`, `critical` |
| `limit` | integer | No | 50 | Max results returned (1–200) |

**Response `200`**
```json
{
  "tasks": [ /* TaskResponse[] */ ],
  "count": 12
}
```

---

### User task list

#### `GET /api/v1/users/{userId}/tasks`

Returns tasks assigned to a specific user. A staff member can always query their own tasks. Viewing another user's tasks requires `senior_partner` or above.

**Minimum required role:** `admin_staff` (own tasks) / `senior_partner` (other user's tasks)

**Query parameters**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `status` | string | No | — | Filter by status |
| `overdue_only` | boolean | No | false | When `true`, returns only tasks past their due date |
| `limit` | integer | No | 50 | Max results returned (1–200) |

**Response `200`**
```json
{
  "tasks": [ /* TaskResponse[] */ ],
  "count": 5
}
```

---

### Internal (Cloud Tasks callback)

#### `POST /internal/reminders`

Called by Cloud Tasks approximately 24 h before a task's `dueAt`. Transitions the task to `overdue` if it is still `pending` or `in_progress` at callback time. Not part of the public API.

**Auth:** Cloud Tasks OIDC token (verified in production; skipped in non-production environments)

**Request body**
```json
{
  "taskId": "task-abc-123",
  "caseId": "ZAD-2026-05-0001",
  "dueAt": "2026-07-01T00:00:00Z"   // informational — service re-checks Firestore state
}
```

**Response `200`**
```json
{ "taskId": "task-abc-123", "status": "overdue" }
```

---

## TaskResponse

Shape returned by all task endpoints.

```json
{
  "taskId": "task-abc-123",
  "caseId": "ZAD-2026-05-0001",
  "workflowExecutionId": "wf-xyz",      // null if not part of a workflow
  "title": "Review medical records",
  "description": "Check for WTC exposure documentation.",
  "taskType": "review_medical_summary",
  "status": "in_progress",              // pending | in_progress | completed | skipped | overdue
  "priority": "high",                   // low | medium | high | critical
  "assignedTo": "uid-123",              // Firebase UID, null if unassigned
  "assignedToRole": "paralegal",        // role label, null if unassigned
  "dueAt": "2026-07-01T00:00:00Z",     // null if no due date
  "reminderSentAt": "2026-06-30T00:00:00Z", // null until reminder fires
  "createdAt": "2026-05-01T10:00:00Z",
  "updatedAt": "2026-05-20T14:30:00Z",
  "completedAt": null,
  "completedBy": null,
  "completionNotes": null,
  "metadata": {}
}
```

---

## Task status transitions

```
pending ──► in_progress ──► completed
   │              │
   │              └──────► skipped
   │
   └──────────────────────► skipped
   │
   ▼
overdue ──► in_progress ──► completed
               │
               └──────────► skipped
```

`completed` and `skipped` are terminal — no further transitions are allowed.
`overdue` is set only by the Cloud Tasks reminder callback, never directly by staff.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GCP_PROJECT_ID` | Yes | GCP project ID (also used as Firebase project) |
| `FIRESTORE_DATABASE_ID` | Yes | Firestore database name (e.g. `simpletort-dev`) |
| `ENVIRONMENT` | Yes | `development`, `staging`, or `production` |
| `TASK_SERVICE_URL` | Yes | This service's own Cloud Run URL (used for reminder callbacks) |
| `SERVICE_ACCOUNT_EMAIL` | Yes | Service account email used for Cloud Tasks OIDC tokens |
| `TRUSTED_SERVICE_ACCOUNTS` | No | Comma-separated SA emails allowed for service-to-service calls |
| `CLOUD_TASKS_QUEUE` | No | Cloud Tasks queue name (default: `task-reminders`) |
| `CLOUD_TASKS_LOCATION` | No | Cloud Tasks region (default: `us-east1`) |
| `REMINDER_ADVANCE_HOURS` | No | Hours before due date to fire reminder (default: `24`) |
| `LOG_LEVEL` | No | Logging level (default: `INFO`) |
