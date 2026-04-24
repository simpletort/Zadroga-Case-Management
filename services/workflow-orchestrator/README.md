# Workflow Orchestrator Service

Orchestrates multi-step litigation workflows, manages case tasks, schedules deadline alerts, and reacts to domain events via Pub/Sub.

**Base URL (dev):** `https://workflow-orchestrator-dev-292736139819.us-central1.run.app`

---

## Endpoints

### Workflows — `/api/v1/workflows`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/workflows/trigger` | Triggers a named Cloud Workflow for a case. Creates a `WorkflowExecution` record in Firestore and returns it immediately — the GCP workflow runs asynchronously. |
| `GET` | `/api/v1/workflows/definitions` | Lists all active workflow definitions. Reads from Firestore, falls back to the hardcoded registry if Firestore is empty. |
| `GET` | `/api/v1/workflows/{execution_id}` | Returns the status of a specific workflow execution. Live-syncs from GCP Cloud Workflows if the execution is still running. |

### Tasks — `/api/v1/tasks` and `/api/v1/cases`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/tasks/active` | Lists all active (pending/in-progress) tasks across all cases. Filterable by `assigned_to` UID, `assigned_to_role`, and `case_id`. Used by paralegal/attorney dashboards. |
| `GET` | `/api/v1/tasks/{task_id}` | Gets a single task. Accepts optional `?case_id=` to scope the Firestore lookup (cheaper); falls back to a collection-group query without it. |
| `PUT` | `/api/v1/tasks/{task_id}/complete` | Marks a task completed, records who completed it and any notes, publishes a `task.completed` Pub/Sub event for downstream workflows. |
| `POST` | `/api/v1/tasks` | Manually creates a task for a case. If the task has a due date, also schedules a Cloud Tasks deadline reminder. |
| `GET` | `/api/v1/cases/{case_id}/tasks` | Lists all tasks for a specific case. Filterable by `?status=`. |

### Admin — `/api/v1/admin/workflows`

Intended for non-technical users (paralegals, senior partners) via the React admin UI. Access is restricted at the Cloud Run ingress layer via the `/admin/` path prefix.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/admin/workflows/seed` | Seeds all 7 workflow definitions into Firestore. Idempotent — skips definitions that already exist. **Run this once after first deployment.** |
| `GET` | `/api/v1/admin/workflows/` | Lists all workflow definitions, including inactive ones. |
| `GET` | `/api/v1/admin/workflows/{workflow_id}` | Gets a single workflow definition. |
| `PATCH` | `/api/v1/admin/workflows/{workflow_id}` | Updates workflow metadata (display name, description, estimated duration). |
| `PATCH` | `/api/v1/admin/workflows/{workflow_id}/task-steps/{step_id}` | Edits a task template's properties (title, priority, due offset days, assigned role). |
| `PATCH` | `/api/v1/admin/workflows/{workflow_id}/automated-steps/{step_id}` | Edits an automated step's configurable parameters (e.g. attorney fee %, eligibility thresholds). |
| `POST` | `/api/v1/admin/workflows/{workflow_id}/activate` | Sets `is_active=true` on a workflow definition. |
| `POST` | `/api/v1/admin/workflows/{workflow_id}/deactivate` | Sets `is_active=false` — prevents new executions from being triggered. |

### Internal — `/internal`

GCP-only. Not publicly accessible — Cloud Run ingress is restricted to internal GCP traffic for `/internal/*` paths.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/internal/workflow-step-config/{workflow_id}` | Called by Cloud Workflow YAMLs at execution start to fetch configurable step parameters from Firestore, avoiding hardcoded thresholds in the YAML. Returns `task_templates` and `step_parameters` maps. |
| `POST` | `/internal/reminders` | Cloud Tasks callback fired ~24h before a task due date. Marks the task OVERDUE if past due, publishes a `task.overdue` Pub/Sub event. |
| `POST` | `/internal/deadline-alerts` | Cloud Tasks callback fired at 90/60/30/14/7 days before a VCF/WTC enrollment deadline. Publishes a `deadline.approaching` event and creates a visible reminder task on the paralegal dashboard. |
| `POST` | `/internal/pubsub/case-events` | Pub/Sub push handler for the `case-events` topic. Checks all active workflow definitions for matching `event_triggers` and automatically fires those workflows. |

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Returns `{"status": "ok"}`. |

---

## Workflow Definitions

Seven workflows are seeded into Firestore on first deployment:

| ID | Display Name | Trigger |
|----|-------------|---------|
| `lead-qualification` | Lead Qualification | Manual |
| `client-onboarding` | Client Onboarding | `lead.qualified` event |
| `medical-processing` | Medical Document Processing | `documents.uploaded` event |
| `vcf-enrollment` | WTC / VCF Enrollment | Manual |
| `substitution-of-counsel` | Substitution of Counsel | Manual |
| `claim-submission` | VCF Claim Submission | Manual |
| `settlement` | Settlement & Disbursement | `award_letter.received` event |

---

## First Deployment Checklist

1. Deploy the service to Cloud Run.
2. Seed workflow definitions into Firestore:
   ```
   GET /api/v1/admin/workflows/seed
   ```
   Expected response: `{"seeded": 7, "skipped": 0}`
3. Verify with `GET /api/v1/workflows/definitions` — should return 7 active workflows.
