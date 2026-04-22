#!/bin/bash
# ---------------------------------------------------------------------------
# IAM Setup – Workflow Orchestrator Service
# Run once per GCP project environment (dev / staging / prod)
# ---------------------------------------------------------------------------
set -e

PROJECT_ID="${1:?Usage: ./iam-setup.sh <PROJECT_ID>}"
REGION="us-east1"
SA_NAME="workflow-orchestrator"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> Creating service account: ${SA_EMAIL}"
gcloud iam service-accounts create "${SA_NAME}" \
  --project="${PROJECT_ID}" \
  --display-name="Workflow Orchestrator Service" \
  --description="Service identity for the SimpleTort Workflow Orchestrator" \
  2>/dev/null || echo "Service account already exists — skipping creation."

echo "==> Granting Firestore access"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/datastore.user"

echo "==> Granting Cloud Workflows executor role"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/workflows.invoker"

echo "==> Granting Cloud Tasks enqueuer role"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudtasks.enqueuer"

echo "==> Granting Pub/Sub publisher and subscriber roles"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/pubsub.publisher"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/pubsub.subscriber"

echo "==> Granting Cloud Run invoker (for service-to-service calls)"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker"

echo "==> Granting Secret Manager accessor (for any secrets at rest)"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor"

echo "==> Creating Cloud Tasks queue: workflow-deadlines"
gcloud tasks queues create workflow-deadlines \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --max-concurrent-dispatches=100 \
  --max-attempts=5 \
  --min-backoff=30s \
  --max-backoff=300s \
  2>/dev/null || echo "Queue already exists — skipping."

echo "==> Creating Pub/Sub topics"
for topic in case-events deadline-alerts; do
  gcloud pubsub topics create "${topic}" \
    --project="${PROJECT_ID}" \
    2>/dev/null || echo "Topic ${topic} already exists — skipping."
done

echo "==> Creating Pub/Sub subscription for inbound case-events"
gcloud pubsub subscriptions create workflow-orchestrator-case-events-sub \
  --project="${PROJECT_ID}" \
  --topic=case-events \
  --push-endpoint="https://workflow-orchestrator-SUFFIX.a.run.app/internal/pubsub/case-events" \
  --push-auth-service-account="${SA_EMAIL}" \
  --ack-deadline=60 \
  2>/dev/null || echo "Subscription already exists — skipping."

echo ""
echo "✅  IAM setup complete for project: ${PROJECT_ID}"
echo "   Service account: ${SA_EMAIL}"
