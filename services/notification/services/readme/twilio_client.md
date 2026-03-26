# twilio_client.py

**Location:** `services/notification/services/twilio_client.py`

---

## What Does This File Do?

The **direct interface to the Twilio SMS API**. It handles the actual HTTP call to Twilio to send an SMS message. It also enforces SMS length limits and calculates how many SMS segments a message will use (which affects billing).

---

## SMS Length Rules (GSM-7 Encoding)

| Message Length | Segments | Cost |
|---|---|---|
| ≤ 160 chars | 1 segment | Cheapest |
| 161–306 chars | 2 segments | 2× cost |
| 307–459 chars | 3 segments | 3× cost |
| > 1600 chars | **Rejected** | Not sent |

**Special characters** like `€`, `{`, `}`, `[`, `]`, `\`, `^`, `~`, `|` count as **2 characters** in GSM-7 encoding. A message with these characters hits the limit faster.

---

## Public Function

### `send_sms_via_twilio(to, body)` → `SmsResult`

Sends an SMS via Twilio. **Never raises an exception** — always returns an `SmsResult`.

```python
from services.twilio_client import send_sms_via_twilio

result = send_sms_via_twilio(
    to="+12125551234",
    body="Hi Jane, your case ZAD-2024-01-0001 has been received.",
)

if result.success:
    print(f"Sent! SID: {result.message_sid}, Segments: {result.segment_count}")
else:
    print(f"Failed: {result.error_code} — {result.error_message}")
```

---

## Return Type — `SmsResult`

| Field | Type | Description |
|---|---|---|
| `success` | bool | `True` if Twilio accepted the message |
| `message_sid` | string\|None | Twilio's unique message ID (e.g. `SMxxxxxxx`) |
| `status` | string\|None | Twilio status (e.g. `"queued"`, `"sent"`) |
| `error_code` | int\|None | Twilio error code if failed |
| `error_message` | string\|None | Human-readable error |
| `char_count` | int | GSM-7 character count |
| `segment_count` | int | Estimated SMS segments |

---

## Configuration (Environment Variables / Secrets)

| Setting | Description | Where Set |
|---|---|---|
| `TWILIO_ACCOUNT_SID` | Twilio account SID | Secret Manager |
| `TWILIO_AUTH_TOKEN` | Twilio auth token | Secret Manager |
| `TWILIO_FROM_NUMBER` | Sender phone number | Cloud Build substitution |

---

## Error Handling

The function catches all errors and returns them in the `SmsResult` — it never crashes the caller:

| Error | Returned As |
|---|---|
| Twilio API error (e.g. invalid number) | `success=False`, `error_code=<twilio code>` |
| Message too long (>1600 chars) | `success=False`, rejected before API call |
| Network error / unexpected exception | `success=False`, `error_message=<details>` |

---

## Twilio Test Numbers

During development, use Twilio's magic test numbers:

| Number | Behaviour |
|---|---|
| `+15005550006` | Always succeeds as FROM number |
| `+15005550001` | Fails — unroutable number |
| `+15005550007` | Fails — international blocked |

---

## Running Tests

```powershell
cd services/notification
python -m pytest tests/test_twilio_client.py -v
```

**16 tests** covering: GSM-7 length calculation, segment counting, successful send, multi-segment, hard cap rejection, Twilio error handling, singleton client reuse.
