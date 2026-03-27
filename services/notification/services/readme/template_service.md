# template_service.py

**Location:** `services/notification/services/template_service.py`

---

## What Does This File Do?

Fetches notification templates from Firestore and renders them by replacing `{{placeholder}}` variables with real values before sending an SMS or email.

**Example:**

Template stored in Firestore:
```
Hi {{clientName}}, your Zadroga Act claim {{caseId}} has been received.
```

After rendering with `{"clientName": "Jane Doe", "caseId": "ZAD-2024-01-0001"}`:
```
Hi Jane Doe, your Zadroga Act claim ZAD-2024-01-0001 has been received.
```

---

## Firestore Template Document Structure

Templates live in the `notificationTemplates` collection:

| Field | Type | Required | Description |
|---|---|---|---|
| `body` | string | ✅ | SMS body with `{{variable}}` placeholders |
| `subject` | string | ✅ | Email subject line |
| `htmlBody` | string | ❌ | HTML email body (auto-generated if absent) |
| `isActive` | boolean | ✅ | `false` = disabled, won't send |
| `channel` | string | ✅ | `"SMS"`, `"EMAIL"`, or `"BOTH"` |
| `triggerEvent` | string | ✅ | e.g. `"new_lead_created"` |

---

## Available Templates

| Template ID | Channel | Variables Required |
|---|---|---|
| `welcome_sms` | SMS | `clientName`, `caseId`, `portalUrl` |
| `welcome_email` | EMAIL | `clientName`, `caseId`, `portalUrl` |
| `reminder_48hr_sms` | SMS | `clientName`, `caseId`, `appointmentDate`, `appointmentTime` |
| `reminder_48hr_email` | EMAIL | `clientName`, `caseId`, `appointmentDate`, `appointmentTime`, `appointmentLocation` |
| `reminder_7day_sms` | SMS | `clientName`, `caseId` |
| `reminder_7day_email` | EMAIL | `clientName`, `caseId`, `submittedDate` |

---

## Public Functions

### `render_template(template_id, variables, db)` → `RenderedTemplate`
Primary entry point. Returns all three rendered fields.

```python
result = await render_template("welcome_sms", {"clientName": "Jane", "caseId": "ZAD-001", "portalUrl": "https://..."}, db)
result.sms_safe   # Plain text ready for Twilio
result.subject    # Email subject
result.html_body  # HTML email body
```

### `fetch_template(template_id, db)` → `dict`
Low-level fetch — returns the raw Firestore document.

### `fetch_and_render(template_id, variables, db)` → `str`
Legacy helper — returns only the SMS body string. Used by `sms_service.py`.

---

## Errors Raised

| Exception | When |
|---|---|
| `TemplateNotFoundError` | Template doesn't exist in Firestore |
| `TemplateDisabledError` | Template has `isActive: false` |
| `MissingVariableError` | One or more `{{placeholder}}` variables not supplied |

---

## Running Tests

```powershell
python -m pytest tests/test_template_service.py -v
```
