#!/usr/bin/env bash
# =============================================================================
# setup.sh — Infrastructure provisioning for Enrollment Workflow Service
#
# Run ONCE per environment to create GCP resources.
# Prerequisites: gcloud CLI authenticated, PROJECT_ID and REGION set.
#
# Usage:
#   export GCP_PROJECT_ID=my-project
#   export REGION=us-central1
#   export ENV=dev           # dev | test | prod
#   bash infrastructure/setup.sh
# =============================================================================

set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}"
REGION="${REGION:-us-central1}"
ENV="${ENV:-dev}"
REPO="us-central1-docker.pkg.dev/${PROJECT_ID}/simpletort"
SCHEDULER_SA="deadline-alerter-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"
ENROLLMENT_SA="enrollment-workflow-sa@${PROJECT_ID}.iam.gserviceaccount.com"
DEADLINE_CALC_SA="deadline-calculator-sa@${PROJECT_ID}.iam.gserviceaccount.com"

echo "=================================================="
echo "Setting up Enrollment Workflow Service"
echo "Project: ${PROJECT_ID}  Region: ${REGION}  Env: ${ENV}"
echo "=================================================="

# ── 1. Enable Required APIs ───────────────────────────────────────────────────
echo "[1/9] Enabling required GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudfunctions.googleapis.com \
  cloudscheduler.googleapis.com \
  workflows.googleapis.com \
  pubsub.googleapis.com \
  firestore.googleapis.com \
  eventarc.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  --project="${PROJECT_ID}"

# ── 2. Create Artifact Registry Repo (if not exists) ─────────────────────────
echo "[2/9] Creating Artifact Registry repository..."
gcloud artifacts repositories create simpletort \
  --repository-format=docker \
  --location="${REGION}" \
  --description="SimpleTort microservices" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  (already exists)"

# ── 3. Create Pub/Sub Topics ──────────────────────────────────────────────────
echo "[3/9] Creating Pub/Sub topics..."
for TOPIC in enrollment-status-changes task-created notification-requests; do
  gcloud pubsub topics create "${TOPIC}" \
    --project="${PROJECT_ID}" 2>/dev/null || echo "  Topic ${TOPIC} already exists"
done

# ── 4. Create Service Accounts ────────────────────────────────────────────────
echo "[4/9] Creating service accounts..."

# Enrollment Workflow Service Account
gcloud iam service-accounts create enrollment-workflow-sa \
  --display-name="Enrollment Workflow Service" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  enrollment-workflow-sa already exists"

# Deadline Calculator Service Account
gcloud iam service-accounts create deadline-calculator-sa \
  --display-name="VCF Deadline Calculator" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  deadline-calculator-sa already exists"

# Deadline Alerter Scheduler Service Account
gcloud iam service-accounts create deadline-alerter-scheduler \
  --display-name="Deadline Alerter Cloud Scheduler" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  deadline-alerter-scheduler already exists"

# ── 5. Grant IAM Roles ────────────────────────────────────────────────────────
echo "[5/9] Granting IAM roles..."

# Enrollment Workflow SA: Firestore read/write + Pub/Sub publish
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${ENROLLMENT_SA}" \
  --role="roles/datastore.user" --quiet

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${ENROLLMENT_SA}" \
  --role="roles/pubsub.publisher" --quiet

# Deadline Calculator SA: Firestore read/write + Pub/Sub publish
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${DEADLINE_CALC_SA}" \
  --role="roles/datastore.user" --quiet

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${DEADLINE_CALC_SA}" \
  --role="roles/pubsub.publisher" --quiet

# Scheduler SA: Cloud Run invoker (to call the deadline-alerter function)
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SCHEDULER_SA}" \
  --role="roles/run.invoker" --quiet

echo "  IAM roles granted."

# ── 6. Create Firestore Composite Indexes ─────────────────────────────────────
echo "[6/9] Creating Firestore indexes..."
cat > /tmp/firestore_indexes.json << 'INDEXES'
{
  "indexes": [
    {
      "collectionGroup": "cases",
      "queryScope": "COLLECTION",
      "fields": [
        {"fieldPath": "enrollment.vcfFilingDeadline", "order": "ASCENDING"},
        {"fieldPath": "status", "order": "ASCENDING"}
      ]
    },
    {
      "collectionGroup": "cases",
      "queryScope": "COLLECTION",
      "fields": [
        {"fieldPath": "assignment.assignedParalegal", "order": "ASCENDING"},
        {"fieldPath": "enrollment.wtcEnrollmentStatus", "order": "ASCENDING"}
      ]
    },
    {
      "collectionGroup": "cases",
      "queryScope": "COLLECTION",
      "fields": [
        {"fieldPath": "assignment.assignedParalegal", "order": "ASCENDING"},
        {"fieldPath": "enrollment.vcfRegistrationStatus", "order": "ASCENDING"}
      ]
    },
    {
      "collectionGroup": "tasks",
      "queryScope": "COLLECTION_GROUP",
      "fields": [
        {"fieldPath": "assignedTo", "order": "ASCENDING"},
        {"fieldPath": "status", "order": "ASCENDING"},
        {"fieldPath": "dueDate", "order": "ASCENDING"}
      ]
    }
  ]
}
INDEXES

echo "  Indexes defined in /tmp/firestore_indexes.json"
echo "  Deploy indexes manually: firebase deploy --only firestore:indexes"

# ── 7. Create Eventarc Trigger (deadline-calculator) ─────────────────────────
echo "[7/9] Creating Eventarc trigger for deadline-calculator..."
echo "  NOTE: Run this AFTER deploying deadline-calculator Cloud Run service:"
echo ""
echo "  gcloud eventarc triggers create deadline-calculator-trigger \\"
echo "    --location=${REGION} \\"
echo "    --destination-run-service=deadline-calculator \\"
echo "    --destination-run-region=${REGION} \\"
echo "    --event-filters=\"type=google.cloud.firestore.document.v1.written\" \\"
echo "    --event-filters=\"database=(default)\" \\"
echo "    --event-filters-path-pattern=\"document=cases/{caseId}\" \\"
echo "    --service-account=${DEADLINE_CALC_SA} \\"
echo "    --project=${PROJECT_ID}"
echo ""

# ── 8. Create Cloud Scheduler Job (deadline-alerter) ─────────────────────────
echo "[8/9] Creating Cloud Scheduler job for deadline-alerter..."
echo "  NOTE: Run this AFTER deploying deadline-alerter Cloud Run service:"
echo ""
echo "  # Get the service URL first:"
echo "  ALERTER_URL=\$(gcloud run services describe deadline-alerter \\"
echo "    --region=${REGION} --format='value(status.url)' --project=${PROJECT_ID})"
echo ""
echo "  gcloud scheduler jobs create http deadline-alerter-daily \\"
echo "    --location=${REGION} \\"
echo "    --schedule=\"0 13 * * *\" \\"      # 8 AM ET = 1 PM UTC
echo "    --uri=\"\${ALERTER_URL}\" \\"
echo "    --http-method=POST \\"
echo "    --oidc-service-account-email=${SCHEDULER_SA} \\"
echo "    --oidc-token-audience=\"\${ALERTER_URL}\" \\"
echo "    --time-zone=\"UTC\" \\"
echo "    --project=${PROJECT_ID}"
echo ""

# ── 9. Store Secrets in Secret Manager ────────────────────────────────────────
echo "[9/9] Secret Manager setup..."
echo "  Create secrets manually (replace values):"
echo ""
echo "  gcloud secrets create SENDGRID_API_KEY --project=${PROJECT_ID}"
echo "  echo -n 'SG.your-key' | gcloud secrets versions add SENDGRID_API_KEY --data-file=- --project=${PROJECT_ID}"
echo ""

echo "=================================================="
echo "Setup complete! Next steps:"
echo "  1. Deploy services: bash scripts/deploy.sh"
echo "  2. Create Eventarc trigger (see step 7 output above)"
echo "  3. Create Cloud Scheduler job (see step 8 output above)"
echo "  4. Deploy Firestore indexes"
echo "  5. Seed firmSettings for VCF firm info"
echo "=================================================="
