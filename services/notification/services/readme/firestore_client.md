# firestore_client.py

**Location:** `services/notification/services/firestore_client.py`

---

## What Does This File Do?

Creates and manages a **single shared Firestore database connection** for the entire notification service. Instead of creating a new connection every time a database operation is needed, it creates one connection when the app starts and reuses it for all requests.

---

## How Authentication Works

| Environment | Method | How |
|---|---|---|
| **Local dev** | Application Default Credentials (ADC) | Run `gcloud auth application-default login` |
| **Cloud Run (prod)** | Service Account | Automatically uses the attached service account |
| **With key file** | Service Account JSON | Set `FIREBASE_SERVICE_ACCOUNT_KEY_PATH` env var |

---

## Public Functions

### `get_db()` → `AsyncClient`
Returns the shared async Firestore client. Creates it on first call, reuses on every subsequent call.

```python
from services.firestore_client import get_db

db = get_db()
doc = await db.collection("cases").document("ZAD-2024-01-0001").get()
```

---

## How It Is Used

This function is called in `app.py` as a FastAPI dependency — every endpoint that needs Firestore gets the same shared client:

```python
# In app.py
from services.firestore_client import get_db

@app.post("/tasks/sms")
async def handle_sms_task(db: AsyncClient = Depends(get_db)):
    await send_sms(..., db=db)
```

---

## Key Design Decisions

- **Singleton pattern** — only one Firestore client per process (saves memory and connection overhead)
- **Lazy initialisation** — client is created on first use, not at import time (faster cold starts)
- **Async client** — uses `firestore_async` so it works with FastAPI's async request handling without blocking
