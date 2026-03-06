#!/bin/bash
SERVICE=$1
REGION=$2

echo "Rolling back service: $SERVICE"

PREVIOUS_REVISION=$(gcloud run revisions list \
  --service=$SERVICE \
  --region=$REGION \
  --sort-by="~createTime" \
  --format="value(metadata.name)" \
  | sed -n 2p)

if [ -z "$PREVIOUS_REVISION" ]; then
  echo "No previous revision found"
  exit 1
fi

echo "Previous revision: $PREVIOUS_REVISION"

gcloud run services update-traffic $SERVICE \
  --region=$REGION \
  --to-revisions=$PREVIOUS_REVISION=100

echo "Rollback complete"