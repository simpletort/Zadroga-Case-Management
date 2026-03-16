#!/bin/bash
set -e

# Arguments from cloudbuild.yaml
SERVICE_NAME=$1
IMAGE=$2
REGION=$3
PROJECT_ID=$4

OBSERVATION_WINDOW=900  # 15 minutes in seconds
ERROR_THRESHOLD=0.5

echo "=== Canary Deployment Started for $SERVICE_NAME ==="

# ─────────────────────────────────────────────
# Step 1: Check if an active canary already exists
# ─────────────────────────────────────────────
echo "Checking for active canary..."

REVISION_COUNT=$(gcloud run services describe $SERVICE_NAME \
  --region=$REGION \
  --project=$PROJECT_ID \
  --format="value(status.traffic)" | wc -l)

if [ "$REVISION_COUNT" -gt "1" ]; then
  echo "Active canary detected. Promoting stable revision to 100% before proceeding..."

  STABLE_REVISION=$(gcloud run services describe $SERVICE_NAME \
    --region=$REGION \
    --project=$PROJECT_ID \
    --format="value(status.traffic.revisionName)" | head -1)

  gcloud run services update-traffic $SERVICE_NAME \
    --region=$REGION \
    --project=$PROJECT_ID \
    --to-revisions=$STABLE_REVISION=100

  echo "Stable revision promoted. Proceeding with new deployment..."
fi

# ─────────────────────────────────────────────
# Step 2: Capture current stable revision BEFORE deploying
# ─────────────────────────────────────────────
STABLE_REVISION=$(gcloud run services describe $SERVICE_NAME \
  --region=$REGION \
  --project=$PROJECT_ID \
  --format="value(status.traffic.revisionName)" | head -1)

echo "Stable revision: $STABLE_REVISION"

# ─────────────────────────────────────────────
# Step 3: Deploy new revision with no traffic
# ─────────────────────────────────────────────
echo "Deploying new revision with no traffic..."

gcloud run deploy $SERVICE_NAME \
  --image=$IMAGE \
  --region=$REGION \
  --project=$PROJECT_ID \
  --platform=managed \
  --no-traffic

# ─────────────────────────────────────────────
# Step 4: Get the new revision name
# ─────────────────────────────────────────────
NEW_REVISION=$(gcloud run revisions list \
  --service=$SERVICE_NAME \
  --region=$REGION \
  --project=$PROJECT_ID \
  --format="value(name)" \
  --limit=1)

echo "New revision: $NEW_REVISION"

# ─────────────────────────────────────────────
# Step 5: Split traffic 10% canary / 90% stable
# ─────────────────────────────────────────────
echo "Splitting traffic: 10% to $NEW_REVISION, 90% to $STABLE_REVISION..."

gcloud run services update-traffic $SERVICE_NAME \
  --region=$REGION \
  --project=$PROJECT_ID \
  --to-revisions=$NEW_REVISION=10,$STABLE_REVISION=90

echo "Traffic split active. Observing for 15 minutes..."

# ─────────────────────────────────────────────
# Step 6: Observe for 15 minutes
# ─────────────────────────────────────────────
sleep $OBSERVATION_WINDOW

# ─────────────────────────────────────────────
# Step 7: Query error rate from Cloud Monitoring
# ─────────────────────────────────────────────
echo "Checking error rate for $NEW_REVISION..."

TOTAL_REQUESTS=$(gcloud monitoring read \
  "metric.type=\"run.googleapis.com/request_count\" AND \
  resource.labels.service_name=\"$SERVICE_NAME\" AND \
  metric.labels.revision_name=\"$NEW_REVISION\"" \
  --project=$PROJECT_ID \
  --freshness=16m \
  --format="value(points[0].value.int64Value)" 2>/dev/null || echo "0")

ERROR_REQUESTS=$(gcloud monitoring read \
  "metric.type=\"run.googleapis.com/request_count\" AND \
  resource.labels.service_name=\"$SERVICE_NAME\" AND \
  metric.labels.revision_name=\"$NEW_REVISION\" AND \
  metric.labels.response_code_class!=\"2xx\"" \
  --project=$PROJECT_ID \
  --freshness=16m \
  --format="value(points[0].value.int64Value)" 2>/dev/null || echo "0")

echo "Total requests: $TOTAL_REQUESTS"
echo "Error requests: $ERROR_REQUESTS"

# ─────────────────────────────────────────────
# Step 8: Calculate error rate and decide
# ─────────────────────────────────────────────
if [ "$TOTAL_REQUESTS" -eq "0" ]; then
  echo "No traffic received by canary revision."
  echo "Promoting to 100% as no errors were detected..."
  PROMOTE=true
else
  ERROR_RATE=$(echo "scale=2; $ERROR_REQUESTS / $TOTAL_REQUESTS * 100" | bc)
  echo "Error rate: $ERROR_RATE%"

  if (( $(echo "$ERROR_RATE < $ERROR_THRESHOLD" | bc -l) )); then
    PROMOTE=true
  else
    PROMOTE=false
  fi
fi

# ─────────────────────────────────────────────
# Step 9: Promote or rollback
# ─────────────────────────────────────────────
if [ "$PROMOTE" = true ]; then
  echo "✅ Canary healthy. Promoting $NEW_REVISION to 100%..."
  gcloud run services update-traffic $SERVICE_NAME \
    --region=$REGION \
    --project=$PROJECT_ID \
    --to-revisions=$NEW_REVISION=100
  echo "=== Deployment Successful ==="
else
  echo "❌ Canary unhealthy (error rate: $ERROR_RATE%). Rolling back to $STABLE_REVISION..."
  gcloud run services update-traffic $SERVICE_NAME \
    --region=$REGION \
    --project=$PROJECT_ID \
    --to-revisions=$STABLE_REVISION=100
  echo "=== Rollback Successful ==="
  exit 1   # Fail the Cloud Build pipeline so the team is alerted
fi
