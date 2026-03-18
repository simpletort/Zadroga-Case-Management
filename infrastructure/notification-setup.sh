#!/usr/bin/env bash
# =============================================================================
# infrastructure/notification-setup.sh
#
# One-time GCP bootstrap for the Notification Service.
# Run this ONCE per environment before the first Cloud Build trigger fires.
# Safe to re-run — every command checks for existence before creating.
#
# What this script creates
# ------------------------
#   1. Service Account       notification-sa@PROJECT_ID.iam.gserviceaccount.com
#   2. IAM bindings          SA roles: Firestore, Cloud Tasks, Secret Manager, Cloud Logging
#   3. Cloud Build IAM       Cloud Build SA can impersonate notification-sa (for deploy)
#   4. Secret Manager        TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN secrets
#                            (values prompted interactively or via env vars)
#   5. Secret access IAM     notification-sa can read the Twilio secrets
#   6. Cloud Tasks queue     sms-dispatch (region: us-east1)
#   7. Artifact Registry     ensures zad-docker-repo repo exists (shared with storage-gateway)
#   8. Firestore indexes      composite index on sms_delivery_records.twilioMessageSid
#                            (required by the status callback query in app.py)
#
# Usage
# -----
#   export PROJECT_ID=simpletort-prod
#   export REGION=us-central1
#   export TASKS_REGION=us-east1
#   export TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
#   export TWILIO_AUTH_TOKEN=your_auth_token_here
#   chmod +x infrastructure/notification-setup.sh
#   ./infrastructure/notification-setup.sh
#
# For a dev project, pass ENV=dev:
#   ENV=dev ./infrastructure/notification-setup.sh
# =============================================================================

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID}"
REGION="${REGION:-us-central1}"
TASKS_REGION="${TASKS_REGION:-us-east1}"
ENV="${ENV:-prod}"

SA_NAME="notification-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
REPO_NAME="zad-docker-repo"
TASKS_QUEUE="sms-dispatch"
SERVICE_NAME="zad-notification-${ENV}"

# Colours
GRN='\033[0;32m'; YLW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GRN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YLW}[WARN]${NC}  $*"; }
section() { echo -e "\n${GRN}══${NC} $* ${GRN}══${NC}"; }

# ── Prerequisite: gcloud auth ─────────────────────────────────────────────────
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
  echo -e "${RED}ERROR: No active gcloud account. Run: gcloud auth login${NC}"
  exit 1
fi

gcloud config set project "$PROJECT_ID"
info "Project: $PROJECT_ID  |  Region: $REGION  |  Tasks region: $TASKS_REGION  |  Env: $ENV"

# ─────────────────────────────────────────────────────────────────────────────
# 1. Enable required GCP APIs
# ─────────────────────────────────────────────────────────────────────────────
section "1. Enabling GCP APIs"

APIS=(
  run.googleapis.com
  cloudbuild.googleapis.com
  cloudtasks.googleapis.com
  secretmanager.googleapis.com
  firestore.googleapis.com
  artifactregistry.googleapis.com
  logging.googleapis.com
  monitoring.googleapis.com
  iam.googleapis.com
)

for api in "${APIS[@]}"; do
  if gcloud services list --filter="name:${api}" --format="value(name)" | grep -q "$api"; then
    info "  $api — already enabled"
  else
    info "  Enabling $api ..."
    gcloud services enable "$api"
  fi
done

# ─────────────────────────────────────────────────────────────────────────────
# 2. Service Account
# ─────────────────────────────────────────────────────────────────────────────
section "2. Service Account: $SA_EMAIL"

if gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" &>/dev/null; then
  info "  Service account already exists — skipping creation"
else
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="Notification Service Runtime SA" \
    --description="Used by zad-notification Cloud Run service and Cloud Tasks" \
    --project="$PROJECT_ID"
  info "  Created $SA_EMAIL"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 3. IAM bindings for the service account
# ─────────────────────────────────────────────────────────────────────────────
section "3. IAM role bindings"

ROLES=(
  "roles/datastore.user"                  # Firestore read/write
  "roles/cloudtasks.enqueuer"             # enqueue Cloud Tasks
  "roles/secretmanager.secretAccessor"    # read Twilio secrets at runtime
  "roles/logging.logWriter"               # write structured logs
  "roles/monitoring.metricWriter"         # write Cloud Run metrics
  "roles/run.invoker"                     # allows Cloud Tasks to invoke this service via OIDC
)

for role in "${ROLES[@]}"; do
  info "  Binding $role → $SA_EMAIL"
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="$role" \
    --condition=None \
    --quiet
done

# ─────────────────────────────────────────────────────────────────────────────
# 4. Allow Cloud Build SA to deploy as notification-sa
# ─────────────────────────────────────────────────────────────────────────────
section "4. Cloud Build → notification-sa impersonation"

CB_SA_EMAIL="${PROJECT_ID}@cloudbuild.gserviceaccount.com"
info "  Granting Cloud Build SA ($CB_SA_EMAIL) actAs $SA_EMAIL"

gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --project="$PROJECT_ID" \
  --member="serviceAccount:${CB_SA_EMAIL}" \
  --role="roles/iam.serviceAccountUser" \
  --quiet

# Cloud Build also needs Cloud Run Admin to deploy the service
info "  Granting Cloud Build SA roles/run.admin on project"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${CB_SA_EMAIL}" \
  --role="roles/run.admin" \
  --condition=None \
  --quiet

# ─────────────────────────────────────────────────────────────────────────────
# 5. Artifact Registry repository (shared with storage-gateway)
# ─────────────────────────────────────────────────────────────────────────────
section "5. Artifact Registry: $REPO_NAME"

if gcloud artifacts repositories describe "$REPO_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" &>/dev/null; then
  info "  Repository $REPO_NAME already exists in $REGION"
else
  gcloud artifacts repositories create "$REPO_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --description="ZAD microservices Docker images" \
    --project="$PROJECT_ID"
  info "  Created Artifact Registry repository: $REPO_NAME"
fi

# Grant Cloud Build push access to the repo
gcloud artifacts repositories add-iam-policy-binding "$REPO_NAME" \
  --location="$REGION" \
  --project="$PROJECT_ID" \
  --member="serviceAccount:${CB_SA_EMAIL}" \
  --role="roles/artifactregistry.writer" \
  --quiet

info "  Cloud Build SA granted artifactregistry.writer on $REPO_NAME"

# ─────────────────────────────────────────────────────────────────────────────
# 6. Secret Manager — Twilio credentials
# ─────────────────────────────────────────────────────────────────────────────
section "6. Secret Manager — Twilio secrets"

_create_or_update_secret() {
  local SECRET_NAME=$1
  local SECRET_VALUE=$2

  if gcloud secrets describe "$SECRET_NAME" --project="$PROJECT_ID" &>/dev/null; then
    warn "  Secret $SECRET_NAME already exists — adding new version"
    echo -n "$SECRET_VALUE" | gcloud secrets versions add "$SECRET_NAME" \
      --data-file=- \
      --project="$PROJECT_ID"
  else
    info "  Creating secret $SECRET_NAME"
    echo -n "$SECRET_VALUE" | gcloud secrets create "$SECRET_NAME" \
      --replication-policy=automatic \
      --data-file=- \
      --project="$PROJECT_ID"
  fi

  # Grant notification-sa access to read this secret
  gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet
  info "  $SA_EMAIL granted accessor on $SECRET_NAME"
}

# Twilio Account SID
TWILIO_SID="${TWILIO_ACCOUNT_SID:-}"
if [ -z "$TWILIO_SID" ]; then
  read -rsp "  Enter TWILIO_ACCOUNT_SID: " TWILIO_SID; echo
fi
_create_or_update_secret "TWILIO_ACCOUNT_SID" "$TWILIO_SID"

# Twilio Auth Token
TWILIO_TOKEN="${TWILIO_AUTH_TOKEN:-}"
if [ -z "$TWILIO_TOKEN" ]; then
  read -rsp "  Enter TWILIO_AUTH_TOKEN: " TWILIO_TOKEN; echo
fi
_create_or_update_secret "TWILIO_AUTH_TOKEN" "$TWILIO_TOKEN"

# ─────────────────────────────────────────────────────────────────────────────
# 7. Cloud Tasks queue — sms-dispatch
# ─────────────────────────────────────────────────────────────────────────────
section "7. Cloud Tasks queue: $TASKS_QUEUE (region: $TASKS_REGION)"

if gcloud tasks queues describe "$TASKS_QUEUE" \
    --location="$TASKS_REGION" \
    --project="$PROJECT_ID" &>/dev/null; then
  info "  Queue $TASKS_QUEUE already exists"
else
  gcloud tasks queues create "$TASKS_QUEUE" \
    --location="$TASKS_REGION" \
    --project="$PROJECT_ID" \
    --max-attempts=5 \
    --max-retry-duration=86400s \
    --min-backoff=10s \
    --max-backoff=300s \
    --max-doublings=5 \
    --max-dispatches-per-second=500 \
    --max-concurrent-dispatches=100
  info "  Created queue: $TASKS_QUEUE"
  info "  max-attempts=5, retry window=24h, backoff 10s→300s (exponential)"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 8. Firestore composite index
#    Required by the /webhooks/twilio/status query:
#    .where("twilioMessageSid", "==", ...) on sms_delivery_records
# ─────────────────────────────────────────────────────────────────────────────
section "8. Firestore composite index — sms_delivery_records.twilioMessageSid"

INDEX_FILE=$(mktemp /tmp/firestore-indexes-XXXX.json)
cat > "$INDEX_FILE" << 'INDEX'
{
  "indexes": [
    {
      "collectionGroup": "sms_delivery_records",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "twilioMessageSid", "order": "ASCENDING" },
        { "fieldPath": "attemptedAt",      "order": "DESCENDING" }
      ]
    }
  ]
}
INDEX

if command -v firebase &>/dev/null; then
  firebase firestore:indexes --project="$PROJECT_ID" 2>/dev/null | \
    grep -q "twilioMessageSid" && \
    info "  Index already exists — skipping" || \
    firebase deploy --only firestore:indexes --project="$PROJECT_ID"
else
  warn "  firebase-tools not installed — deploy index manually:"
  warn "  npm install -g firebase-tools"
  warn "  Then apply: $INDEX_FILE"
  cat "$INDEX_FILE"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 9. Summary
# ─────────────────────────────────────────────────────────────────────────────
REPO_PATH="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}"

echo ""
echo -e "${GRN}══════════════════════════════════════════════════${NC}"
echo -e "${GRN}  Setup complete — Notification Service (${ENV})${NC}"
echo -e "${GRN}══════════════════════════════════════════════════${NC}"
echo ""
echo "  Service account : $SA_EMAIL"
echo "  Artifact repo   : $REPO_PATH"
echo "  Tasks queue     : projects/$PROJECT_ID/locations/$TASKS_REGION/queues/$TASKS_QUEUE"
echo ""
echo -e "${YLW}  Next step: Create the Cloud Build trigger — see README below.${NC}"
echo ""
echo "  Cloud Build trigger substitutions:"
echo "    _REPO                   = $REPO_PATH"
echo "    _SERVICE_NAME           = zad-notification"
echo "    _ENV                    = $ENV"
echo "    _REGION                 = $REGION"
echo "    _TWILIO_FROM_NUMBER     = <your Twilio sender number>"
echo "    _CLOUD_TASKS_QUEUE      = $TASKS_QUEUE"
echo "    _CLOUD_TASKS_QUEUE_REGION = $TASKS_REGION"
echo "    _NOTIFICATION_SA_EMAIL  = $SA_EMAIL"
echo ""
