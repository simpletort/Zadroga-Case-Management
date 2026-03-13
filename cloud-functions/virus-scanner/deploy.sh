#!/usr/bin/env bash
# Manual deploy script for the virus-scanner Cloud Function (Gen 2).
#
# Usage:
#   ./deploy.sh [PROJECT_ID] [REGION] [ENV]
#
# Example:
#   ./deploy.sh simpletort-prod us-central1 prod
#
# Prerequisites:
#   - gcloud authenticated with sufficient permissions
#   - Artifact Registry repo already created
#   - Eventarc trigger created (see comment at bottom of this script)

set -euo pipefail

PROJECT_ID="${1:-simpletort-prod}"
REGION="${2:-us-central1}"
ENV="${3:-prod}"
REPO="${REGION}-docker.pkg.dev/${PROJECT_ID}/simpletort/virus-scanner"
BUCKET="zadroga-case-files-${PROJECT_ID}"
SERVICE_NAME="virus-scanner"
IMAGE="${REPO}:latest"

echo "==> Building and pushing image to Artifact Registry..."
docker build -t "${IMAGE}" .
docker push "${IMAGE}"

echo "==> Deploying Cloud Run service: ${SERVICE_NAME}..."
gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --platform=managed \
  --no-allow-unauthenticated \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},GCS_BUCKET_NAME=${BUCKET},ENV=${ENV}" \
  --memory=1Gi \
  --cpu=1 \
  --timeout=300s \
  --max-instances=5 \
  --min-instances=0 \
  --project="${PROJECT_ID}"

echo "==> Deployment complete."
echo ""
echo "NOTE: Ensure the Eventarc trigger exists:"
echo ""
echo "  gcloud eventarc triggers create virus-scanner-gcs-trigger \\"
echo "    --location=${REGION} \\"
echo "    --destination-run-service=${SERVICE_NAME} \\"
echo "    --destination-run-region=${REGION} \\"
echo "    --event-filters='type=google.cloud.storage.object.v1.finalized' \\"
echo "    --event-filters='bucket=${BUCKET}' \\"
echo "    --event-filters-path-pattern='name=staging/**' \\"
echo "    --service-account=virus-scanner-sa@${PROJECT_ID}.iam.gserviceaccount.com \\"
echo "    --project=${PROJECT_ID}"
