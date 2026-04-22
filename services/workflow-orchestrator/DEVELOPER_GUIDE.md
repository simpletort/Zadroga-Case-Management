# Workflow Orchestrator — Developer Guide

## What this service does

The Workflow Orchestrator is the process coordinator for SimpleTort. It does not do case work itself — it **triggers multi-step processes, creates tasks for staff, schedules deadline alerts, and reacts to events from other microservices**.

Three things flow through it:
1. **Workflow executions** — GCP Cloud Workflows processes that call other microservices in sequence.
2. **Tasks** — human-action items that appear on paralegal, attorney, and client dashboards.
3. **Events** — Pub/Sub messages that auto-advance the pipeline without manual intervention.

---

## Repository layout

```
workflow-orchestrator/
│
├── main.py                        # FastAPI app entry point, health check, logging setup
├── config.py                      # All config loaded from env vars
├── .env.example                   # Copy to .env for local development
│
├── api/
│   ├── workflows.py               # POST /trigger, GET /definitions, GET /{execution_id}
│   └── tasks.py                   # GET /active, PUT /{id}/complete, GET /cases/{id}/tasks
│
├── services/
│   ├── workflow_engine.py         # ← THE KEY FILE: triggers GCP workflows + creates tasks
│   ├── firestore_service.py       # All Firestore reads/writes (never call Firestore directly)
│   ├── pubsub_service.py          # Publishes domain events to Pub/Sub topics
│   └── cloud_tasks_service.py     # Schedules deadline reminders via Cloud Tasks
│
├── handlers/
│   └── event_handler.py           # /internal/* endpoints for Cloud Tasks callbacks + Pub/Sub
│
├── models/
│   ├── task.py                    # Task entity + enums + request/response models
│   └── workflow.py                # WorkflowExecution, WorkflowType, WORKFLOW_REGISTRY
│
├── cloud_workflows/               # GCP Cloud Workflows YAML definitions (one per workflow type)
│   ├── lead-qualification.yaml
│   ├── client-onboarding.yaml
│   ├── medical-processing.yaml
│   ├── vcf-enrollment.yaml
│   └── settlement.yaml
│
├── tests/
│   ├── conftest.py                # Shared fixtures and sample data factories
│   ├── test_models.py             # Task/WorkflowExecution serialisation, enums, registry
│   ├── test_api.py                # API endpoint routing and validation
│   ├── test_workflow_engine.py    # Initial task creation, GCP trigger behaviour
│   └── test_event_handler.py     # Cloud Tasks callbacks, Pub/Sub routing
│
├── Dockerfile                     # Multi-stage build for Cloud Run
├── cloudbuild.yaml                # CI/CD: build → test → deploy service + YAML workflows
└── iam-setup.sh                   # One-time IAM/queue/topic setup per environment
```

---

## How to run locally

```bash
# 1. Copy and fill in the config
cp .env.example .env
# Edit .env — GCP_PROJECT_ID and CLOUD_TASKS_SERVICE_URL are the minimum required

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the server
python main.py
```

The server starts at `http://localhost:8080`. Interactive API docs are available at `http://localhost:8080/docs` in non-production environments.

> **Note:** Without real GCP credentials, any endpoint that calls Firestore, Cloud Workflows, or Cloud Tasks will return a 500. Endpoints that only use local logic (e.g. `GET /api/v1/workflows/definitions`, `GET /health`) work without credentials.

---

## How to run tests

```bash
pip install pytest pytest-asyncio httpx
pytest tests/ -v
```

No GCP credentials are required — all cloud clients are mocked. See `tests/README.md` for more detail.

---

## How to change the process

### Changing tasks within an existing workflow

Tasks are defined in `WORKFLOW_INITIAL_TASKS` in `services/workflow_engine.py`. Each entry is a 5-element tuple:

```
(TaskType, "title", TaskPriority, due_offset_hours, "assigned_to_role")
```

**Examples:**

```python
# Change the retainer deadline from 48h to 72h
(TaskType.SIGN_RETAINER, "Sign retainer agreement (DocuSign)",
 TaskPriority.CRITICAL, 72, "client"),   # was 48

# Add a new paralegal review step to medical processing
WorkflowType.MEDICAL_PROCESSING: [
    (TaskType.REVIEW_MEDICAL_SUMMARY, "Review AI-generated medical summary",
     TaskPriority.HIGH, 24, "paralegal"),
    (TaskType.VERIFY_QUALIFICATION_SCORE, "Verify AI qualification score",
     TaskPriority.HIGH, 48, "attorney"),
    # NEW: senior paralegal checks before attorney review
    (TaskType.GENERIC, "Senior paralegal sign-off on medical summary",
     TaskPriority.HIGH, 36, "paralegal"),
],
```

After editing, run `pytest tests/test_workflow_engine.py` to verify the change is correct.

---

### Changing the steps in a Cloud Workflow (the GCP process)

Each `.yaml` file in `cloud_workflows/` defines the actual multi-step process that runs in GCP. Steps call other microservices via authenticated HTTP.

**To add a new step:**

```yaml
# In cloud_workflows/medical-processing.yaml, after fetch_qualification_score:

- notify_compliance_team:
    call: http.post
    args:
      url: ${notification_url + "/api/v1/notifications/email"}
      auth:
        type: OIDC
      body:
        template: "compliance_review_required"
        case_id: ${case_id}
    result: compliance_notify_response
```

**To change a branching condition:**

```yaml
# Change the qualification threshold from 65 to 75:
- evaluate_score:
    switch:
      - condition: ${score_response.body.qualification_score >= 75}   # was 65
        next: advance_to_review
    next: flag_for_manual_review
```

After editing a YAML, redeploy it with:
```bash
gcloud workflows deploy medical-processing \
  --location=us-east1 \
  --source=cloud_workflows/medical-processing.yaml
```

Or push to `main` and `cloudbuild.yaml` will deploy all YAMLs automatically.

---

### Adding a new workflow type end-to-end

Four things need to change:

**1. Add the enum value** in `models/workflow.py`:
```python
class WorkflowType(str, Enum):
    ...
    ANNUAL_REVIEW = "annual-review"   # new
```

**2. Register it** in `WORKFLOW_REGISTRY` in the same file:
```python
WorkflowType.ANNUAL_REVIEW: WorkflowDefinition(
    workflow_type=WorkflowType.ANNUAL_REVIEW,
    gcp_workflow_id="annual-review",
    display_name="Annual Case Review",
    description="Triggers a scheduled annual review of active cases.",
    required_arguments=["case_id"],
    estimated_duration_hours=2.0,
),
```

**3. Add its initial tasks** in `services/workflow_engine.py`:
```python
WorkflowType.ANNUAL_REVIEW: [
    (TaskType.REVIEW_CASE_FILE, "Annual case file review",
     TaskPriority.MEDIUM, 168, "paralegal"),
    (TaskType.ATTORNEY_APPROVAL, "Attorney sign-off on annual review",
     TaskPriority.MEDIUM, 336, "attorney"),
],
```

**4. Create the YAML definition** at `cloud_workflows/annual-review.yaml`. Use the existing files as templates — all steps must use OIDC auth and all service URLs must use `sys.get_env("CLOUD_RUN_SUFFIX")`.

---

### Adding a new auto-trigger (Pub/Sub event → workflow)

When another microservice publishes an event and you want this service to automatically start a workflow in response, edit `handle_case_event()` in `handlers/event_handler.py`:

```python
elif event_type == "annual_review.scheduled":
    # Auto-trigger annual review when the scheduler fires
    await engine.trigger(
        case_id=data["case_id"],
        workflow_type=WorkflowType.ANNUAL_REVIEW,
        triggered_by="system",
        arguments={"case_id": data["case_id"]},
    )
```

Then add a test in `tests/test_event_handler.py`:
```python
def test_annual_review_scheduled_triggers_annual_review(self, client):
    body = _pubsub_body("annual_review.scheduled", {"case_id": "case-abc"})
    with patch("handlers.event_handler.WorkflowEngine") as MockEngine:
        MockEngine.return_value.trigger = AsyncMock()
        client.post("/internal/pubsub/case-events", json=body)
    call_kwargs = MockEngine.return_value.trigger.call_args.kwargs
    assert call_kwargs["workflow_type"] == "annual-review"
```

---

### Changing deadline alert thresholds

Enrollment deadline alerts fire at 90/60/30/14/7 days by default. To change this:

```python
# In services/cloud_tasks_service.py, schedule_enrollment_deadline_check():
if advance_days is None:
    advance_days = [120, 90, 60, 30, 14, 7]  # added 120-day early warning
```

The `CRITICAL` vs `HIGH` priority threshold is in `handlers/event_handler.py`:
```python
# Change CRITICAL cutoff from 14 days to 30 days
priority = TaskPriority.CRITICAL if payload.days_remaining <= 30 else TaskPriority.HIGH
```

---

## How the data is stored

All data lives in Firestore. The key collections are:

| Path | What it stores |
|---|---|
| `cases/{caseId}/tasks/{taskId}` | Tasks for a specific case |
| `cases/{caseId}/workflow_executions/{id}` | Execution records for a specific case |
| `workflow_executions/{id}` | Top-level index of all executions (enables cross-case queries) |

**Why the dual-write on workflow executions?**
Firestore doesn't support queries across sub-collections efficiently without collection group indexes. Writing to the top-level `workflow_executions` collection lets us query "all running workflows" without a collection group query. The case sub-collection gives cheap case-scoped lookups.

**Required Firestore indexes:**
The `list_active_tasks` query requires a composite index on the `tasks` collection group:
- `status` ASC + `due_date` ASC

Create it in the GCP console or with:
```bash
gcloud firestore indexes composite create \
  --collection-group=tasks \
  --field-config=field-path=status,order=ASCENDING \
  --field-config=field-path=due_date,order=ASCENDING
```

---

## Deployment

```bash
# Deploy to staging
gcloud run deploy workflow-orchestrator \
  --image=us-east1-docker.pkg.dev/simpletort-staging/simpletort/workflow-orchestrator:latest \
  --region=us-east1 \
  --service-account=workflow-orchestrator@simpletort-staging.iam.gserviceaccount.com

# Deploy all Cloud Workflow definitions
for f in cloud_workflows/*.yaml; do
  gcloud workflows deploy "$(basename $f .yaml)" --location=us-east1 --source="$f"
done
```

Pushing to `main` runs `cloudbuild.yaml` automatically, which does all of the above.

---

## Common issues

**"Your default credentials were not found"**
You're running locally without GCP credentials. For local development either:
- Run `gcloud auth application-default login`, or
- Set `GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json`

**"composite index required" error from Firestore**
The `list_active_tasks` query needs a composite index. See the Firestore indexes section above.

**Cloud Tasks job fires but the endpoint returns 403**
The OIDC token audience must exactly match the Cloud Run service URL. Check that `CLOUD_TASKS_SERVICE_URL` in your env matches the URL in the Cloud Tasks queue configuration.

**A workflow triggers but no tasks appear on the dashboard**
Check that the `WorkflowType` has an entry in `WORKFLOW_INITIAL_TASKS`. If the key is missing, `_create_initial_tasks` silently returns an empty list.

**Pub/Sub events are not triggering workflows**
1. Check that the push subscription URL points to `/internal/pubsub/case-events` on the correct Cloud Run service URL.
2. Check Cloud Run logs for `pubsub_decode_error` — the message payload may be malformed.
3. Check that the event_type string exactly matches the `if/elif` in `handle_case_event()`.
