# sms_service.py

**Location:** `services/notification/services/sms_service.py`

---

## What Does This File Do?

The **main orchestrator** for sending SMS messages. It coordinates all the steps needed to send an SMS — from checking if the recipient opted out, to fetching the template, rendering the message, calling Twilio, and writing a delivery record.

This is the single entry point for all outbound SMS in the notification service.

---

## The 4-Step SMS Flow

```
send_sms() called
      │
      ▼
Step 1: Opt-out check
      ├── Opted out?  → return status="opted_out"  (no SMS sent)
      └── Not opted out → continue
      │
      ▼
Step 2: Fetch template + render body
      ├── Template not found?   → return status="template_error"
      ├── Template disabled?    → return status="template_error"
      ├── Missing variables?    → return status="template_error"
      └── Rendered OK           → continue
      │
      ▼
Step 3: Send via Twilio
      ├── Twilio success → status="sent"
      └── Twilio failure → status="failed"
      │
      ▼
Step 4: Write delivery record to Firestore
      └── Always attempted (non-fatal if it fails)
```

---

## Public Function

### `send_sms(to, template_id, variables, db, *, case_id, request_id)` → `SmsDispatchResult`

**Never raises an exception** — always returns an `SmsDispatchResult`.

```python
from services.sms_service import send_sms

result = await send_sms(
    to="+12125551234",
    template_id="welcome_sms",
    variables={"clientName": "Jane Doe", "caseId": "ZAD-2024-01-0001", "portalUrl": "https://..."},
    db=db,
    case_id="ZAD-2024-01-0001",
    request_id="req-abc-123",
)

print(result.success)       # True / False
print(result.status)        # "sent" / "failed" / "opted_out" / "template_error"
print(result.message_sid)   # Twilio message SID (e.g. "SMxxxxxxx")
print(result.segment_count) # Number of SMS segments used
```

---

## Return Type — `SmsDispatchResult`

| Field | Type | Description |
|---|---|---|
| `success` | bool | `True` only when Twilio confirmed the send |
| `delivery_id` | string | UUID — matches the Firestore delivery record |
| `status` | string | `"sent"`, `"failed"`, `"opted_out"`, `"template_error"` |
| `message_sid` | string\|None | Twilio message SID |
| `error_code` | int\|None | Twilio error code (if failed) |
| `error_message` | string\|None | Human-readable error description |
| `char_count` | int | GSM-7 character count of the rendered body |
| `segment_count` | int | Estimated number of SMS segments billed |

---

## Firestore Delivery Record

Every SMS attempt writes a document to the `sms_delivery_records` collection:

| Field | Description |
|---|---|
| `deliveryId` | UUID (also the document ID) |
| `to` | Destination phone number (PII — stored for audit) |
| `caseId` | Associated case |
| `templateId` | Template used |
| `status` | `"sent"`, `"failed"`, `"opted_out"`, `"template_error"` |
| `twilioMessageSid` | Twilio SID |
| `charCount` | Character count |
| `segmentCount` | SMS segments |
| `attemptedAt` | ISO timestamp |
| `sentAt` | ISO timestamp (only when status=sent) |

---

## Privacy Note

The `to` phone number is **never logged** — all log entries use `to_masked="[REDACTED]"`. The phone is stored in the Firestore delivery record for support/audit purposes only.

---

## Running Tests

```powershell
cd services/notification
python -m pytest tests/test_sms_service.py -v
```

**15 tests** covering: happy path, opted-out, opt-out check error, template not found, template disabled, missing variable, Twilio failure, delivery record robustness.
