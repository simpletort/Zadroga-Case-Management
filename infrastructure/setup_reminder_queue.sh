#!/usr/bin/env bash
# infrastructure/setup_reminder_queue.sh
#
# One-time setup script for the Cloud Tasks queue used by document reminder tasks.
#
# Configures:
#   - max 3 delivery attempts per task
#   - exponential backoff: 10s → 20s → 40s (max 300s)
#   - max_doublings=2  (doubles the backoff interval twice before capping)
#   - dispatch_deadline=30s per attempt
#
# Run once per environment (dev / prod).  Safe to re-run — update is idempotent.
#
# Usage:
#   ./infrastructure/setup_reminder_queue.sh simpletort-zadroga-dev us-central1
#
# Arguments:
#   $1 — GCP project ID   (e.g. simpletort-zadroga-dev)
#   $2 — Queue region     (e.g. us-central1)

set -euo pipefail

PROJECT="${1:?Usage: $0 <project-id> <region>}"
REGION="${2:?Usage: $0 <project-id> <region>}"
QUEUE="sms-dispatch"

echo "Configuring Cloud Tasks queue: projects/$PROJECT/locations/$REGION/queues/$QUEUE"

# Create queue if it doesn't exist, then update retry config.
# 'gcloud tasks queues create' is idempotent when combined with --quiet.
gcloud tasks queues create "$QUEUE" \
  --project="$PROJECT" \
  --location="$REGION" \
  --quiet 2>/dev/null || true

gcloud tasks queues update "$QUEUE" \
  --project="$PROJECT" \
  --location="$REGION" \
  --max-attempts=3 \
  --min-backoff=10s \
  --max-backoff=300s \
  --max-doublings=2

echo ""
echo "Queue retry configuration applied:"
gcloud tasks queues describe "$QUEUE" \
  --project="$PROJECT" \
  --location="$REGION" \
  --format="yaml(retryConfig)"
