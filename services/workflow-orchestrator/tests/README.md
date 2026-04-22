# Workflow Orchestrator — Test Suite

## Running the tests

```bash
# Install dependencies (once)
pip install -r requirements.txt
pip install pytest pytest-asyncio httpx

# Run all tests
pytest tests/ -v

# Run a specific file
pytest tests/test_models.py -v

# Run with coverage report
pip install pytest-cov
pytest tests/ --cov=. --cov-report=term-missing --cov-omit="tests/*"
```

No GCP credentials are required — all cloud clients are mocked.

## Test files

| File | What it tests |
|---|---|
| `test_models.py` | Task / WorkflowExecution serialisation, enums, Firestore round-trip, registry |
| `test_api.py` | All API endpoints — routing, validation, response shapes, error codes |
| `test_workflow_engine.py` | Initial task creation, GCP trigger behaviour, failure handling |
| `test_event_handler.py` | Cloud Tasks callbacks (overdue), deadline alerts, Pub/Sub event routing |

## Adding tests when you change the process

- **Added a new task to a workflow?** → `test_workflow_engine.py::TestWorkflowInitialTasks`
- **Changed a workflow type or required argument?** → `test_api.py::TestTriggerWorkflow`
- **Added a new Pub/Sub event trigger?** → `test_event_handler.py::TestPubSubCaseEventHandler`
- **Changed deadline priority logic?** → `test_event_handler.py::TestDeadlineAlertHandler`
