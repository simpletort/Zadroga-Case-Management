# tasks_service.py

**Location:** `services/notification/services/tasks_service.py`

---

## What Does This File Do?

Handles **async SMS queuing via Google Cloud Tasks**. Instead of sending an SMS immediately (which would slow down the caller), it puts the SMS job into a Cloud Tasks queue. Cloud Tasks then calls the notification service's `/tasks/sms` endpoint in the background to do the actual sending.

**Why async?** The lead-intake service needs to respond to the user quickly when a new case is submitted. By queuing the SMS, the lead-intake service can return immediately while the notification happens in the background.

---

## How Cloud Tasks Works Here

```
Lead-Intake Service
        │
        │  calls enqueue_sms()  ← THIS FILE
        ▼
Cloud Tasks Queue ("sms-dispatch")
        │
        │  HTTP POST /tasks/sms  (after optional delay)
        ▼
Notification Service (Cloud Run)
        │
        ▼
sms_service.send_sms() → Twilio → SMS delivered
```

---

## Public Function

### `enqueue_sms(to, template_id, variables, *, case_id, request_id, delay_seconds)` → `str`

Puts an SMS dispatch job into the Cloud Tasks queue. Returns the task name (resource path).

```python
from services.tasks_service import enqueue_sms

task_name = enqueue_sms(
    to="+12125551234",
    template_id="welcome_sms",
    variables={"clientName": "Jane Doe", "caseId": "ZAD-2024-01-0001", "portalUrl": "https://..."},
    case_id="ZAD-2024-01-0001",
    request_id="req-abc-123",
    delay_seconds=0,      # Send immediately (or set e.g. 300 for 5-minute delay)
)
```

---

## Task Payload (sent to `/tasks/sms`)

```json
{
  "to": "+12125551234",
  "templateId": "welcome_sms",
  "variables": {
    "clientName": "Jane Doe",
    "caseId": "ZAD-2024-01-0001",
    "portalUrl": "https://portal.zadroga.com/c/ZAD-2024-01-0001"
  },
  "caseId": "ZAD-2024-01-0001",
  "requestId": "req-abc-123"
}
```

---

## Configuration (Environment Variables)

| Setting | Description | Example |
|---|---|---|
| `CLOUD_TASKS_QUEUE` | Queue name | `sms-dispatch` |
| `CLOUD_TASKS_QUEUE_REGION` | Queue region | `us-central1` |
| `NOTIFICATION_SERVICE_URL` | URL of notification Cloud Run service | `https://notification-dev-xxx.run.app` |
| `NOTIFICATION_SA_EMAIL` | Service account for OIDC auth | `notification-sa@project.iam.gserviceaccount.com` |

---

## Retry Behaviour

Cloud Tasks automatically retries if the `/tasks/sms` endpoint returns a non-2xx response. The handler always returns 200 (even on Twilio failure) to prevent duplicate sends.

| Scenario | HTTP Response | Cloud Tasks Action |
|---|---|---|
| SMS sent successfully | 200 | Task complete — no retry |
| Template not found | 200 | Task complete — no retry |
| Twilio failure | 200 | Task complete — no retry |
| Server crash / 500 | 500 | **Retry** (risk of duplicate send) |

---

## Scheduled / Delayed Sends

Use `delay_seconds` to schedule an SMS in the future:

```python
# Send in 48 hours (for appointment reminders)
enqueue_sms(
    to=phone,
    template_id="reminder_48hr_sms",
    variables={...},
    delay_seconds=48 * 60 * 60,
)
```

---

## Running Tests

```powershell
cd services/notification
python -m pytest tests/test_tasks_service.py -v
```
