"""
test_reminders.py — Local runner to test document reminder scheduling.

Calls service code DIRECTLY (no HTTP, no deployment needed).
Same approach as send_sms.py.

Tests:
  [1/4] Fetch case from Firestore
  [2/4] Enqueue 48hr + 7day reminder tasks in Cloud Tasks
  [3/4] Verify both tasks exist in Cloud Tasks queue
  [4/4] Cancel both tasks (unless --skip-cancel)

Usage (from services/notification/):
    python test_reminders.py --case-id ZAD-2024-01-0001
    python test_reminders.py --case-id ZAD-2024-01-0001 --skip-cancel
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

# ── Bootstrap ─────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

PASS  = "\033[92mPASS\033[0m"
FAIL  = "\033[91mFAIL\033[0m"
INFO  = "\033[94mINFO\033[0m"

# ── Args ──────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--case-id",     required=True, help="e.g. ZAD-2024-01-0001")
parser.add_argument("--phone",       default=None,  help="Override E.164 phone")
parser.add_argument("--skip-cancel", action="store_true",
                    help="Leave tasks scheduled (don't run step 4)")
args = parser.parse_args()

CASE_ID = args.case_id

# ── Header ────────────────────────────────────────────────────────────────────
print("=" * 60)
print("  ZAD Notification — Reminder Scheduling Test")
print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
print("=" * 60)
print()

# ─────────────────────────────────────────────────────────────────────────────
# [1/4] Fetch case from Firestore
# ─────────────────────────────────────────────────────────────────────────────
print(f"[1/4] Fetching case from Firestore: {CASE_ID}...")

from services.firestore_client import get_db

async def fetch_case():
    db = get_db()
    doc = await db.collection("cases").document(CASE_ID).get()
    return doc.to_dict() if doc.exists else None

case_data = asyncio.run(fetch_case())

if not case_data:
    print(f"{FAIL}  Case {CASE_ID} not found in Firestore")
    sys.exit(1)

lead        = case_data.get("leadData", {})
first       = lead.get("firstName", "")
last        = lead.get("lastName", "")
client_name = f"{first} {last}".strip() or "Client"
phone       = args.phone or lead.get("phone", "")
portal_url  = case_data.get("portalAccessLink",
                             f"https://portal.zadroga.com/c/{CASE_ID}")
status      = case_data.get("status", "")
raw_missing = case_data.get("missingDocuments", [])

print(f"{PASS}  Case found: {CASE_ID}")
print(f"      clientName : {client_name}")
print(f"      phone      : {phone}")
print(f"      status     : {status}")
print(f"      portalUrl  : {portal_url}")
print()

if not phone:
    print(f"{FAIL}  No phone number on case — cannot schedule SMS reminder")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# [2/4] Enqueue 48hr + 7day tasks directly via tasks_service
# ─────────────────────────────────────────────────────────────────────────────
print(f"[2/4] Enqueuing reminder tasks in Cloud Tasks...")

from services.tasks_service import enqueue_document_reminders

deadline = (datetime.now(tz=timezone.utc) + timedelta(hours=48)).strftime(
    "%B %d, %Y at %I:%M %p UTC"
)

if raw_missing:
    missing_docs = "\n".join(f"• {d}" for d in raw_missing)
else:
    missing_docs = (
        "• Required authorization forms\n"
        "• Supporting documentation for your Zadroga Act claim"
    )

try:
    result = enqueue_document_reminders(
        case_id        = CASE_ID,
        phone          = phone,
        client_name    = client_name,
        missing_docs_list = missing_docs,
        portal_url     = portal_url,
        deadline_label = deadline,
        request_id     = f"test-{CASE_ID}",
    )
    task_48 = result.get("task_48hr")
    task_7d = result.get("task_7day")
    print(f"{PASS}  Tasks enqueued")
    print(f"      48hr task : {task_48 or 'already existed'}")
    print(f"      7day task : {task_7d or 'already existed'}")
except Exception as e:
    print(f"{FAIL}  {e}")
    sys.exit(1)
print()

# ─────────────────────────────────────────────────────────────────────────────
# [3/4] Verify tasks exist in Cloud Tasks queue
# ─────────────────────────────────────────────────────────────────────────────
print(f"[3/4] Verifying tasks in Cloud Tasks queue...")

from google.cloud import tasks_v2
from config import get_settings

settings   = get_settings()
tc         = tasks_v2.CloudTasksClient()
queue_path = tc.queue_path(
    settings.gcp_project_id,
    settings.cloud_tasks_queue_region,
    settings.cloud_tasks_queue,
)
safe_id = CASE_ID.replace("/", "-")

all_found = True
for suffix in ["48hr", "7day"]:
    task_name = f"{queue_path}/tasks/doc-reminder-{safe_id}-{suffix}"
    try:
        task = tc.get_task(request={"name": task_name})
        sched = task.schedule_time.strftime("%Y-%m-%d %H:%M UTC") \
                if task.schedule_time else "immediate"
        print(f"{PASS}  doc-reminder-{safe_id}-{suffix}")
        print(f"      scheduled  : {sched}")
        print(f"      attempts   : {task.dispatch_count}")
    except Exception as e:
        print(f"{FAIL}  doc-reminder-{safe_id}-{suffix} — {e}")
        all_found = False
print()

# ─────────────────────────────────────────────────────────────────────────────
# [4/4] Cancel tasks
# ─────────────────────────────────────────────────────────────────────────────
if args.skip_cancel:
    print(f"[4/4] Skipping cancellation (--skip-cancel)")
    print(f"      Tasks remain scheduled — they will fire for real.")
    print(f"      To cancel later run:")
    print(f"      python test_reminders.py --case-id {CASE_ID}")
else:
    print(f"[4/4] Cancelling tasks...")
    from services.tasks_service import cancel_document_reminders
    try:
        cancel = cancel_document_reminders(CASE_ID)
        print(f"{PASS}  Cancellation complete")
        print(f"      48hr cancelled : {cancel['cancelled_48hr']}")
        print(f"      7day cancelled : {cancel['cancelled_7day']}")
    except Exception as e:
        print(f"{FAIL}  {e}")
print()

# ── Summary ────────────────────────────────────────────────────────────────────
print("=" * 60)
if all_found:
    print("  All steps passed ✓  Reminder scheduling works correctly.")
else:
    print("  Some steps failed — check Cloud Tasks queue config.")
print("=" * 60)
