#!/usr/bin/env bash
# One-shot deploy script for local / first-time setup.
# Usage:
#   export PROJECT_ID=your-gcp-project
#   export REGION=us-central1
#   export REPO=us-central1-docker.pkg.dev/$PROJECT_ID/simpletort
#   export TEAMS_WEBHOOK_URL="https://outlook.office.com/webhook/..."
#   ./deploy.sh [dev|test|prod]
#
# Prerequisites:
#   - gcloud CLI authenticated with sufficient IAM (Cloud Run Admin, Eventarc Admin)
#   - Docker buildx available
#   - Artifact Registry repo already exists
#   - cloud-builds Pub/Sub topic exists (created automatically by Cloud Build)

set -euo pipefail

ENV="${1:-dev}"
SERVICE_NAME="build-notifier"
PROJECT_ID="${PROJECT_ID:?PROJECT_ID not set}"
REGION="${REGION:-us-central1}"
REPO="${REPO:?REPO not set}"
TEAMS_SECRET_NAME="teams-build-webhook"

echo "==> Storing Teams webhook URL in Secret Manager..."
if gcloud secrets describe "$TEAMS_SECRET_NAME" --project="$PROJECT_ID" &>/dev/null; then
  echo "    Secret exists — adding new version"
  echo -n "${TEAMS_WEBHOOK_URL:?TEAMS_WEBHOOK_URL not set}" \
    | gcloud secrets versions add "$TEAMS_SECRET_NAME" \
        --project="$PROJECT_ID" --data-file=-
else
  echo "    Creating secret"
  echo -n "${TEAMS_WEBHOOK_URL:?TEAMS_WEBHOOK_URL not set}" \
    | gcloud secrets create "$TEAMS_SECRET_NAME" \
        --project="$PROJECT_ID" \
        --replication-policy=automatic \
        --data-file=-
fi

COMMIT_SHA="$(git rev-parse --short HEAD)"
IMAGE="$REPO/$SERVICE_NAME:$COMMIT_SHA"

echo "==> Building Docker image: $IMAGE"
docker build -t "$IMAGE" -t "$REPO/$SERVICE_NAME:latest" .

echo "==> Pushing image..."
docker push "$IMAGE"
docker push "$REPO/$SERVICE_NAME:latest"

echo "==> Deploying Cloud Run service..."
gcloud run deploy "$SERVICE_NAME" \
  --image="$IMAGE" \
  --region="$REGION" \
  --platform=managed \
  --no-allow-unauthenticated \
  --set-env-vars="GCP_PROJECT_ID=$PROJECT_ID,ENV=$ENV" \
  --set-secrets="TEAMS_WEBHOOK_URL=$TEAMS_SECRET_NAME:latest" \
  --memory=256Mi \
  --cpu=1 \
  --timeout=60s \
  --max-instances=3 \
  --min-instances=0 \
  --project="$PROJECT_ID"

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo "==> Ensuring Cloud Build Pub/Sub topic exists..."
gcloud pubsub topics describe "cloud-builds" --project="$PROJECT_ID" &>/dev/null \
  || gcloud pubsub topics create "cloud-builds" --project="$PROJECT_ID"

echo "==> Creating/updating Eventarc trigger..."
gcloud eventarc triggers delete build-notifier-trigger \
  --location="$REGION" --project="$PROJECT_ID" --quiet 2>/dev/null || true

gcloud eventarc triggers create build-notifier-trigger \
  --location="$REGION" \
  --destination-run-service="$SERVICE_NAME" \
  --destination-run-region="$REGION" \
  --event-filters="type=google.cloud.pubsub.topic.v1.messagePublished" \
  --transport-topic="projects/$PROJECT_ID/topics/cloud-builds" \
  --service-account="$SA" \
  --project="$PROJECT_ID"

echo ""
echo "✅  build-notifier deployed successfully."
echo "    Environment : $ENV"
echo "    Image       : $IMAGE"
echo "    Trigger     : build-notifier-trigger → cloud-builds topic"
