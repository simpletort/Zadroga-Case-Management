# Local Development Guide

Three scenarios, in order of complexity:
1. **Pure local** — server runs, GCP endpoints return 500, everything else works
2. **Tests** — full 74-test suite, zero credentials needed
3. **Local + real GCP** — your laptop talks to live Firestore, Cloud Workflows, Cloud Tasks, Pub/Sub

---

## Scenario 1 — Pure local, no GCP

### Step 1 — Install dependencies

```bash
cd workflow-orchestrator
pip install -r requirements.txt
```

If pip complains about system packages: `pip install -r requirements.txt --break-system-packages`

Prefer a venv:
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Step 2 — Create your `.env`

```bash
cp .env.example .env
```

Fill in any non-empty values — nothing calls GCP in this mode:

```
GCP_PROJECT_ID=local-dev
GCP_REGION=us-east1
CLOUD_TASKS_QUEUE=simpletort-tasks
CLOUD_TASKS_SERVICE_URL=http://localhost:8080
SERVICE_ACCOUNT_EMAIL=fake@fake.iam.gserviceaccount.com
ENVIRONMENT=development
```

### Step 3 — Start the server

```bash
python main.py
```

Server starts at `http://localhost:8080`. Logs are structured JSON.

### Step 4 — Try the API

Open `http://localhost:8080/docs` for the interactive Swagger UI.

**Endpoints that work without GCP:**

```bash
# Health check
curl http://localhost:8080/health

# All workflow definitions (in-memory, no GCP)
curl http://localhost:8080/api/v1/workflows/definitions
```

**Endpoints that return 500 without credentials** (expected — they touch Firestore/Cloud Workflows):

```bash
curl -X POST http://localhost:8080/api/v1/workflows/trigger \
  -H "Content-Type: application/json" \
  -d '{"case_id": "case-001", "workflow_type": "lead-qualification",
       "triggered_by": "staff-uid-123", "arguments": {"lead_id": "lead-001"}}'
```

---

## Scenario 2 — Run the test suite (no GCP required)

All 74 tests mock every GCP client. No credentials, no network, no project.

### Step 1 — Install test dependencies

```bash
pip install pytest pytest-asyncio httpx
```

### Step 2 — Run everything

```bash
pytest tests/ -v
```

### Step 3 — Run a subset

```bash
# Just model tests (fastest, zero I/O)
pytest tests/test_models.py -v

# Just API routing tests
pytest tests/test_api.py -v

# Just workflow engine tests
pytest tests/test_workflow_engine.py -v

# Just Pub/Sub and Cloud Tasks callback tests
pytest tests/test_event_handler.py -v

# A single test by name
pytest tests/test_workflow_engine.py::TestWorkflowEngine::test_trigger_creates_initial_tasks -v

# Stop on first failure
pytest tests/ -x -v
```

### What each file covers

| File | What it tests |
|---|---|
| `test_models.py` | Pydantic validation, Firestore serialisation, enum values, WORKFLOW_REGISTRY completeness |
| `test_api.py` | HTTP routing, request validation (422s), 404s, response shapes |
| `test_workflow_engine.py` | Task creation per workflow, GCP trigger call, error handling |
| `test_event_handler.py` | Cloud Tasks callbacks (reminders, deadline alerts), Pub/Sub event routing |

---

## Scenario 3 — Local server pointing at real GCP

Your laptop runs the FastAPI server; Firestore, Cloud Workflows, Cloud Tasks, and Pub/Sub are live in a real GCP project.

### Prerequisites

- A GCP project (personal dev or `simpletort-staging`)
- `gcloud` CLI installed — https://cloud.google.com/sdk/docs/install
- Your account has `roles/editor` or the specific roles in `iam-setup.sh`

### Step 1 — Authenticate

```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

This saves credentials to `~/.config/gcloud/application_default_credentials.json`. All GCP client libraries pick this up automatically — no env var needed.

### Step 2 — Enable the required APIs (once per project)

```bash
gcloud services enable \
  firestore.googleapis.com \
  cloudtasks.googleapis.com \
  workflows.googleapis.com \
  pubsub.googleapis.com \
  run.googleapis.com
```

### Step 3 — Run the one-time infrastructure setup

```bash
chmod +x iam-setup.sh
./iam-setup.sh
```

Or manually:

```bash
# Cloud Tasks queue
gcloud tasks queues create simpletort-tasks --location=us-east1

# Pub/Sub topic
gcloud pubsub topics create simpletort-case-events
```

### Step 4 — Create the Firestore composite index

Required for the `list_active_tasks` query:

```bash
gcloud firestore indexes composite create \
  --collection-group=tasks \
  --field-config=field-path=status,order=ASCENDING \
  --field-config=field-path=due_date,order=ASCENDING
```

Takes ~2 minutes. Check status at **GCP Console → Firestore → Indexes**.

### Step 5 — Deploy the Cloud Workflow YAML definitions

```bash
for f in cloud_workflows/*.yaml; do
  gcloud workflows deploy "$(basename $f .yaml)" \
    --location=us-east1 \
    --source="$f"
done
```

### Step 6 — Update your `.env`

```
GCP_PROJECT_ID=your-real-project-id
GCP_REGION=us-east1
CLOUD_TASKS_QUEUE=simpletort-tasks
CLOUD_TASKS_SERVICE_URL=http://localhost:8080
SERVICE_ACCOUNT_EMAIL=your-sa@your-project.iam.gserviceaccount.com
ENVIRONMENT=development
```

> **Note on Cloud Tasks callbacks:** `CLOUD_TASKS_SERVICE_URL=http://localhost:8080` means Cloud Tasks will try to POST back to your local machine. This only works if you expose your port publicly — use `ngrok http 8080` and put the ngrok URL here if you want callbacks to actually fire.

### Step 7 — Start the server

```bash
python main.py
```

### Step 8 — Trigger a real workflow

```bash
curl -X POST http://localhost:8080/api/v1/workflows/trigger \
  -H "Content-Type: application/json" \
  -d '{
    "case_id": "case-test-001",
    "workflow_type": "lead-qualification",
    "triggered_by": "you@example.com",
    "arguments": {"lead_id": "lead-test-001"}
  }'
```

**What happens behind the scenes:**
1. FastAPI validates the request
2. `WorkflowExecution` record written to Firestore (top-level index + case sub-collection)
3. Initial tasks created in `cases/case-test-001/tasks/`
4. GCP Cloud Workflow execution launched (`lead-qualification`)
5. `workflow.started` Pub/Sub event published

You'll get back:

```json
{
  "execution_id": "a3f2c891-...",
  "case_id": "case-test-001",
  "workflow_type": "lead-qualification",
  "status": "running",
  "gcp_execution_name": "projects/your-project/locations/us-east1/workflows/lead-qualification/executions/..."
}
```

### Step 9 — Verify in GCP console

| What to check | Where in console |
|---|---|
| Workflow execution | Workflows → `lead-qualification` → Executions |
| Tasks created | Firestore → `cases/case-test-001/tasks` |
| Execution record | Firestore → `workflow_executions/{id}` |
| Pub/Sub events | Pub/Sub → Topics → `simpletort-case-events` → View messages |

### Step 10 — Query tasks via API

```bash
# All active tasks across cases
curl http://localhost:8080/api/v1/tasks/active

# Tasks for a specific case
curl http://localhost:8080/api/v1/cases/case-test-001/tasks
```

### Step 11 — Complete a task

```bash
# Replace {task-id} with an ID from the previous response
curl -X PUT http://localhost:8080/api/v1/tasks/{task-id}/complete \
  -H "Content-Type: application/json" \
  -d '{"completed_by": "you@example.com", "completion_notes": "Done."}'
```

---

## Quick reference — what needs GCP and what doesn't

| Endpoint / Layer | No GCP | Needs GCP |
|---|---|---|
| `pytest tests/` | ✅ fully mocked | — |
| `GET /health` | ✅ | — |
| `GET /api/v1/workflows/definitions` | ✅ | — |
| `POST /api/v1/workflows/trigger` | — | ✅ Firestore + Cloud Workflows |
| `GET /api/v1/tasks/active` | — | ✅ Firestore |
| `GET /api/v1/cases/{id}/tasks` | — | ✅ Firestore |
| `PUT /api/v1/tasks/{id}/complete` | — | ✅ Firestore + Pub/Sub |
| `POST /api/v1/tasks` (manual create) | — | ✅ Firestore + Cloud Tasks |
| Cloud Tasks callbacks (`/internal/reminders`) | — | ✅ only fires if CT configured with ngrok URL |
| Pub/Sub callbacks (`/internal/pubsub/case-events`) | — | ✅ only fires if push subscription configured |
