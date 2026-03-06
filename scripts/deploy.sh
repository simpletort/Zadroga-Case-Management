#!/bin/bash
set -e

ENV=$1
SERVICE_NAME=$2
REPO=$3
COMMIT_SHA=$4
REGION=$5
PROJECT_ID=$6

echo ">>> ENV is: '$ENV'"

if [ "$ENV" = "prod" ]; then
  echo "Production deployment - running canary..."
  bash scripts/canary-deploy.sh \
    $SERVICE_NAME-$ENV \
    $REPO/$SERVICE_NAME:$COMMIT_SHA \
    $REGION \
    $PROJECT_ID
else
  echo "Staging deployment - deploying directly..."
  gcloud run deploy $SERVICE_NAME-$ENV --image=$REPO/$SERVICE_NAME:$COMMIT_SHA --region=$REGION --platform=managed --allow-unauthenticated --set-env-vars=ENV=$ENV
fi