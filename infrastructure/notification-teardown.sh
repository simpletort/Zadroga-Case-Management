#!/usr/bin/env bash
# =============================================================================
# infrastructure/notification-teardown.sh
#
# Removes ALL GCP resources created by notification-setup.sh for one ENV.
# Use for dev cleanup or full rollback.  Does NOT touch prod unless
# you explicitly set ENV=prod (guarded with a confirmation prompt).
#
# Usage
#   export PROJECT_ID=simpletort-prod
#   ENV=dev ./infrastructure/notification-teardown.sh
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID}"
REGION="${REGION:-us-central1}"
TASKS_REGION="${TASKS_REGION:-us-east1}"
ENV="${ENV:-dev}"

SA_NAME="notification-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
TASKS_QUEUE="sms-dispatch"
SERVICE_NAME="zad-notification-${ENV}"

RED='\033[0;31m'; YLW='\033[1;33m'; GRN='\033[0;32m'; NC='\033[0m'
warn() { echo -e "${YLW}[WARN]${NC}  $*"; }
info() { echo -e "${GRN}[INFO]${NC}  $*"; }

if [ "$ENV" = "prod" ]; then
  echo -e "${RED}WARNING: You are about to delete PRODUCTION resources for project $PROJECT_ID.${NC}"
  read -rp "Type 'delete-prod' to confirm: " CONFIRM
  [ "$CONFIRM" = "delete-prod" ] || { echo "Aborted."; exit 1; }
fi

gcloud config set project "$PROJECT_ID"

echo ""
warn "Tearing down Notification Service resources (ENV=$ENV, PROJECT=$PROJECT_ID)"
echo ""

# Cloud Run service
info "Deleting Cloud Run service: $SERVICE_NAME"
gcloud run services delete "$SERVICE_NAME" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --quiet 2>/dev/null || warn "  Service $SERVICE_NAME not found — skipping"

# Cloud Tasks queue
info "Deleting Cloud Tasks queue: $TASKS_QUEUE"
gcloud tasks queues delete "$TASKS_QUEUE" \
  --location="$TASKS_REGION" \
  --project="$PROJECT_ID" \
  --quiet 2>/dev/null || warn "  Queue $TASKS_QUEUE not found — skipping"

# Secrets (only delete if both envs are being torn down; comment out if shared)
if [ "$ENV" = "dev" ]; then
  warn "Secrets (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN) are shared across envs."
  warn "Skipping secret deletion. Delete manually if needed:"
  warn "  gcloud secrets delete TWILIO_ACCOUNT_SID --project=$PROJECT_ID"
  warn "  gcloud secrets delete TWILIO_AUTH_TOKEN  --project=$PROJECT_ID"
fi

# Service account (only delete if no other services depend on it)
info "Deleting service account: $SA_EMAIL"
gcloud iam service-accounts delete "$SA_EMAIL" \
  --project="$PROJECT_ID" \
  --quiet 2>/dev/null || warn "  SA $SA_EMAIL not found — skipping"

echo ""
info "Teardown complete for ENV=$ENV."
warn "Artifact Registry images and Firestore collections were NOT deleted."
warn "Delete manually if needed:"
warn "  gcloud artifacts docker images delete REPO/zad-notification:TAG"
