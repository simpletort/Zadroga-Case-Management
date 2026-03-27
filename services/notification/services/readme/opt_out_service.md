# opt_out_service.py

**Location:** `services/notification/services/opt_out_service.py`

---

## What Does This File Do?

Manages the **SMS opt-out / suppression list**. When a client replies STOP to an SMS, they are added to this list and will never receive another SMS from the service. When they reply START, they are removed from the list.

---

## Firestore Collection

Documents are stored in the `notification_opt_outs` collection.

**Document ID** = the client's phone number in E.164 format (e.g. `+12125551234`)

| Field | Type | Description |
|---|---|---|
| `phone` | string | E.164 phone number |
| `smsOptedOut` | boolean | `true` = opted out, `false` = active |
| `optedOutAt` | string | ISO timestamp when opt-out was recorded |
| `reason` | string | `"STOP"`, `"UNSUBSCRIBE"`, `"manual"` |
| `updatedAt` | timestamp | Firestore server timestamp |

---

## Public Functions

### `is_opted_out(phone, db)` → `bool`
Checks if a phone number has opted out. Returns `True` if opted out, `False` if not (or if no record exists).

```python
from services.opt_out_service import is_opted_out

opted_out = await is_opted_out("+12125551234", db)
if opted_out:
    # Skip sending SMS
    pass
```

### `record_opt_out(phone, reason, db)` → `None`
Records an opt-out for a phone number. Called when a STOP or UNSUBSCRIBE keyword is received from Twilio.

```python
await record_opt_out("+12125551234", reason="STOP", db=db)
```

### `clear_opt_out(phone, db)` → `None`
Removes the opt-out flag. Called when a START keyword is received from Twilio.

```python
await clear_opt_out("+12125551234", db=db)
```

---

## How It Fits in the Flow

```
sms_service.send_sms()
        │
        ▼
opt_out_service.is_opted_out()    ← THIS FILE (Step 1)
        │
        ├── True  → skip SMS, write delivery record with status="opted_out"
        └── False → continue to template fetch and send
```

```
Twilio inbound webhook (app.py)
        │
        ├── "STOP" or "UNSUBSCRIBE" → opt_out_service.record_opt_out()   ← THIS FILE
        └── "START"                 → opt_out_service.clear_opt_out()    ← THIS FILE
```

---

## Privacy Note

Phone numbers are **never logged in plain text**. All log entries use `phone_masked="[REDACTED]"` to prevent PII from appearing in Cloud Logging.

---

## Running Tests

```powershell
cd services/notification
python -m pytest tests/test_opt_out_service.py -v
```

**12 tests** covering: opted-out true/false, document absent, correct collection/document path, record and clear writes.
