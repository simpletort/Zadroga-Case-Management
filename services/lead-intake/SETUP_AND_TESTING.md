 # Lead Intake — GCP Setup & Testing Guide

## 1. Parameters you must set before deploying

### GCP project variables
| Variable | What it is | Example |
|---|---|---|
| `PROJECT_ID` | Your GCP project ID | `zad-lead-intake-prod` |
| `REGION` | Cloud Run / Functions region | `us-central1` |
| `SERVICE_NAME` | Cloud Run service name | `zad-lead-intake` |
| `REPO_NAME` | Artifact Registry repo name | `zad-docker-repo` |

### Secret Manager secrets (create with `gcloud secrets create`)
| Secret name | What it holds |
|---|---|
| `sendgrid-api-key` | SendGrid API key |
| `twilio-account-sid` | Twilio Account SID |
| `twilio-auth-token` | Twilio Auth Token |
| `twilio-from-number` | Twilio sender phone in E.164 e.g. `+12125550000` |
| `partner-hmac-secret-<partner_id>` | HMAC secret per partner (if requireHmac=true) |

### Cloud Run environment variables
| Env var | Default | Required in prod |
|---|---|---|
| `GCP_PROJECT_ID` | — | YES |
| `APP_ENV` | `development` | Set to `production` |
| `FIRESTORE_CASES_COLLECTION` | `cases` | optional |
| `FIRESTORE_COUNTERS_COLLECTION` | `counters` | optional |
| `FIRESTORE_PARTNERS_COLLECTION` | `partners` | optional |
| `JWT_AUDIENCE` | — | YES (Firebase project ID) |
| `JWT_ISSUER` | — | YES (`https://securetoken.google.com/<project>`) |
| `JWKS_URI` | Google default | optional |
| `CLOUD_TASKS_QUEUE` | `lead-followup-queue` | YES |
| `CLOUD_TASKS_LOCATION` | `us-central1` | YES |
| `CLOUD_TASKS_HANDLER_URL` | — | YES (Cloud Run URL, no trailing slash) |
| `CLOUD_TASKS_SA_EMAIL` | auto-generated | YES |
| `FOLLOWUP_DELAY_HOURS` | `48` | optional |
| `SENDGRID_API_KEY` | — | YES (or use Secret Manager mount) |
| `SENDGRID_FROM_EMAIL` | `noreply@zadlegal.com` | optional |
| `TWILIO_ACCOUNT_SID` | — | YES |
| `TWILIO_AUTH_TOKEN` | — | YES |
| `TWILIO_FROM_NUMBER` | — | YES |
| `PUBSUB_LEAD_CREATED_TOPIC` | `lead-created` | optional |
| `PUBSUB_LEAD_SCREENED_TOPIC` | `lead-screened` | optional |
| `RATE_LIMIT_REQUESTS` | `100` | optional |

### Cloud Function environment variables
All three functions need:
| Env var | Value |
|---|---|
| `GCP_PROJECT_ID` | Your project ID |
| `FIRESTORE_CASES_COLLECTION` | `cases` |

`followup_monitor` also needs:
| Env var | Value |
|---|---|
| `FOLLOWUP_DELAY_HOURS` | `48` |
| `DEFAULT_ASSIGNEE_EMAIL` | `paralegal@yourfirm.com` |

---

## 2. One-time GCP setup

```bash
export PROJECT_ID="zad-lead-intake-prod"
export REGION="us-central1"
export SERVICE_ACCOUNT="lead-intake-sa"

# Enable APIs
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  cloudtasks.googleapis.com \
  secretmanager.googleapis.com \
  cloudfunctions.googleapis.com \
  cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com \
  --project=$PROJECT_ID

# Create service account
gcloud iam service-accounts create $SERVICE_ACCOUNT \
  --display-name="Lead Intake Service Account" \
  --project=$PROJECT_ID

SA_EMAIL="$SERVICE_ACCOUNT@$PROJECT_ID.iam.gserviceaccount.com"

# Grant IAM roles to the service account
for ROLE in \
  roles/datastore.user \
  roles/pubsub.publisher \
  roles/cloudtasks.enqueuer \
  roles/secretmanager.secretAccessor \
  roles/run.invoker; do
  gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SA_EMAIL" \
    --role="$ROLE"
done

# Create Firestore database (native mode)
gcloud firestore databases create \
  --location=$REGION \
  --project=$PROJECT_ID

# Deploy Firestore indexes (Bug 4 fix — required for followup_monitor query)
firebase deploy --only firestore:indexes --project=$PROJECT_ID
# OR manually via console:
# Firestore → Indexes → Composite → Add Index:
#   Collection: cases
#   Fields: status (ASC), followupTaskCreated (ASC), createdAt (ASC)

# Create Pub/Sub topics
gcloud pubsub topics create lead-created --project=$PROJECT_ID
gcloud pubsub topics create lead-screened --project=$PROJECT_ID

# Create Cloud Tasks queue
gcloud tasks queues create lead-followup-queue \
  --location=$REGION \
  --project=$PROJECT_ID

# Create Artifact Registry repo
gcloud artifacts repositories create zad-docker-repo \
  --repository-format=docker \
  --location=$REGION \
  --project=$PROJECT_ID

# Store secrets
echo -n "YOUR_SENDGRID_KEY" | gcloud secrets create sendgrid-api-key \
  --data-file=- --project=$PROJECT_ID

echo -n "YOUR_TWILIO_SID" | gcloud secrets create twilio-account-sid \
  --data-file=- --project=$PROJECT_ID

echo -n "YOUR_TWILIO_TOKEN" | gcloud secrets create twilio-auth-token \
  --data-file=- --project=$PROJECT_ID

echo -n "+12125550000" | gcloud secrets create twilio-from-number \
  --data-file=- --project=$PROJECT_ID
```

---

## 3. Build and deploy Cloud Run

```bash
# Build and push Docker image
gcloud builds submit \
  --tag $REGION-docker.pkg.dev/$PROJECT_ID/zad-docker-repo/lead-intake:latest \
  --project=$PROJECT_ID

# Deploy to Cloud Run
gcloud run deploy zad-lead-intake \
  --image=$REGION-docker.pkg.dev/$PROJECT_ID/zad-docker-repo/lead-intake:latest \
  --region=$REGION \
  --platform=managed \
  --service-account=$SA_EMAIL \
  --no-allow-unauthenticated \
  --set-env-vars="GCP_PROJECT_ID=$PROJECT_ID,APP_ENV=production,\
JWT_AUDIENCE=$PROJECT_ID,\
JWT_ISSUER=https://securetoken.google.com/$PROJECT_ID,\
CLOUD_TASKS_QUEUE=lead-followup-queue,\
CLOUD_TASKS_LOCATION=$REGION,\
CLOUD_TASKS_SA_EMAIL=$SA_EMAIL" \
  --set-secrets="SENDGRID_API_KEY=sendgrid-api-key:latest,\
TWILIO_ACCOUNT_SID=twilio-account-sid:latest,\
TWILIO_AUTH_TOKEN=twilio-auth-token:latest,\
TWILIO_FROM_NUMBER=twilio-from-number:latest" \
  --project=$PROJECT_ID

# Capture the service URL and add it back as env var
SERVICE_URL=$(gcloud run services describe zad-lead-intake \
  --region=$REGION --format="value(status.url)" --project=$PROJECT_ID)

gcloud run services update zad-lead-intake \
  --region=$REGION \
  --update-env-vars="CLOUD_TASKS_HANDLER_URL=$SERVICE_URL" \
  --project=$PROJECT_ID

echo "Service URL: $SERVICE_URL"
```

---

## 4. Deploy Cloud Functions

```bash
# vcf_screener — triggered by lead-created Pub/Sub
gcloud functions deploy vcf-screener \
  --gen2 \
  --runtime=python312 \
  --region=$REGION \
  --source=functions/vcf_screener \
  --entry-point=vcf_screener \
  --trigger-topic=lead-created \
  --service-account=$SA_EMAIL \
  --set-env-vars="GCP_PROJECT_ID=$PROJECT_ID,FIRESTORE_CASES_COLLECTION=cases" \
  --project=$PROJECT_ID

# notification_dispatcher — triggered by lead-screened Pub/Sub
gcloud functions deploy notification-dispatcher \
  --gen2 \
  --runtime=python312 \
  --region=$REGION \
  --source=functions/notification_dispatcher \
  --entry-point=notification_dispatcher \
  --trigger-topic=lead-screened \
  --service-account=$SA_EMAIL \
  --set-env-vars="GCP_PROJECT_ID=$PROJECT_ID,FIRESTORE_CASES_COLLECTION=cases" \
  --project=$PROJECT_ID

# followup_monitor — triggered by Cloud Scheduler (HTTP)
gcloud functions deploy followup-monitor \
  --gen2 \
  --runtime=python312 \
  --region=$REGION \
  --source=functions/followup_monitor \
  --entry-point=followup_monitor \
  --trigger-http \
  --no-allow-unauthenticated \
  --service-account=$SA_EMAIL \
  --set-env-vars="GCP_PROJECT_ID=$PROJECT_ID,FIRESTORE_CASES_COLLECTION=cases,\
FOLLOWUP_DELAY_HOURS=48,DEFAULT_ASSIGNEE_EMAIL=paralegal@yourfirm.com" \
  --project=$PROJECT_ID

MONITOR_URL=$(gcloud functions describe followup-monitor \
  --region=$REGION --format="value(serviceConfig.uri)" --project=$PROJECT_ID)

# Create Cloud Scheduler job for followup_monitor (hourly)
gcloud scheduler jobs create http followup-monitor-hourly \
  --location=$REGION \
  --schedule="0 * * * *" \
  --uri="$MONITOR_URL" \
  --message-body="{}" \
  --oidc-service-account-email=$SA_EMAIL \
  --oidc-token-audience=$MONITOR_URL \
  --project=$PROJECT_ID
```

---

## 5. Create your first admin partner & API key

```bash
BASE_URL="$SERVICE_URL"

# Get a Firebase ID token with admin role
# (set role=admin custom claim via Firebase Admin SDK or GCP console first)
ADMIN_TOKEN="<your-firebase-admin-jwt>"

# Create a partner
curl -X POST "$BASE_URL/api/v1/admin/partners" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Partner", "allowedIps": [], "requireHmac": false}'
# Save the partnerId from the response

PARTNER_ID="partner_<hex>"

# Generate an API key
curl -X POST "$BASE_URL/api/v1/admin/partners/$PARTNER_ID/keys" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"label": "prod-key-1"}'
# Copy the apiKey — it is shown ONCE only

API_KEY="zad_<key>"
```

---

## 6. curl test suite — every action

Set these first:
```bash
BASE_URL="https://<your-cloud-run-url>"
API_KEY="zad_<your-key>"
ADMIN_TOKEN="<firebase-admin-jwt>"
LEAD_ID=""   # filled in after create
```

### Health check
```bash
curl -s "$BASE_URL/health" | jq .
# {"status":"healthy","version":"2.0.0"}
```

### Auth tests
```bash
# No auth → 401
curl -s "$BASE_URL/api/v1/leads" | jq .error

# Bad key → 401
curl -s -H "X-API-Key: zad_badkey" "$BASE_URL/api/v1/leads" | jq .error

# Valid key → 200
curl -s -H "X-API-Key: $API_KEY" "$BASE_URL/api/v1/leads" | jq .total
```

### POST /leads — create lead
```bash
LEAD_ID=$(curl -s -X POST "$BASE_URL/api/v1/leads" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "firstName": "John",
    "lastName": "Smith",
    "email": "john.smith@example.com",
    "phone": "+12125551234",
    "exposureLocation": "World Trade Center",
    "exposureDates": {"start": "2001-09-11", "end": "2002-06-30"},
    "wtcHealthProgramStatus": "enrolled",
    "priorAttorney": false,
    "conditions": ["asthma", "ptsd"],
    "marketingSource": "google-ads"
  }' | jq -r .leadId)
echo "Created: $LEAD_ID"
# Triggers: Pub/Sub → vcf_screener → lead-screened → notification_dispatcher
# Also queues: Cloud Tasks (48hr followup)
```

### POST /leads — duplicate → 409
```bash
curl -s -X POST "$BASE_URL/api/v1/leads" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"firstName":"John","lastName":"Smith","email":"john.smith@example.com",
       "phone":"+12125551234","exposureLocation":"World Trade Center",
       "exposureDates":{"start":"2001-09-11","end":"2002-06-30"},
       "wtcHealthProgramStatus":"enrolled","priorAttorney":false,
       "marketingSource":"google-ads"}' | jq .error
# DUPLICATE_LEAD
```

### POST /leads — idempotency
```bash
curl -s -X POST "$BASE_URL/api/v1/leads" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Request-ID: idempotency-test-001" \
  -H "Content-Type: application/json" \
  -d '{"firstName":"Jane","lastName":"Doe","email":"jane.doe.unique@example.com",
       "phone":"+12125559876","exposureLocation":"Ground Zero",
       "exposureDates":{"start":"2001-09-11","end":"2003-01-01"},
       "wtcHealthProgramStatus":"applied","priorAttorney":false,
       "marketingSource":"referral"}' | jq .leadId

# Run same command again — same leadId returned
```

### POST /leads — validation failure → 400
```bash
curl -s -X POST "$BASE_URL/api/v1/leads" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"firstName":"","email":"not-an-email"}' | jq .error
# VALIDATION_ERROR
```

### GET /leads — list & filter
```bash
# All leads
curl -s -H "X-API-Key: $API_KEY" "$BASE_URL/api/v1/leads" | jq .total

# Filter by status
curl -s -H "X-API-Key: $API_KEY" "$BASE_URL/api/v1/leads?status=New%20Lead" | jq .total

# Filter by VCF eligibility
curl -s -H "X-API-Key: $API_KEY" "$BASE_URL/api/v1/leads?vcfEligibility=eligible" | jq .total

# Search by email prefix
curl -s -H "X-API-Key: $API_KEY" "$BASE_URL/api/v1/leads?search=john" | jq .total

# Pagination
curl -s -H "X-API-Key: $API_KEY" "$BASE_URL/api/v1/leads?pageSize=2" | jq '{hasMore,nextPageToken}'
```

### GET /leads/{lead_id} — single lead
```bash
curl -s -H "X-API-Key: $API_KEY" "$BASE_URL/api/v1/leads/$LEAD_ID" | jq '{caseId,status,vcfEligibility}'

# Not found → 404
curl -s -H "X-API-Key: $API_KEY" "$BASE_URL/api/v1/leads/ZAD-0000-00-0000" | jq .error
```

### PATCH /leads/{lead_id}/status
```bash
curl -s -X PATCH "$BASE_URL/api/v1/leads/$LEAD_ID/status" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status":"Active","note":"Converted to active case","updatedBy":"admin@zadlegal.com"}' | jq .

# Invalid status → 400
curl -s -X PATCH "$BASE_URL/api/v1/leads/$LEAD_ID/status" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status":"Bogus"}' | jq .error
```

### POST /leads/bulk-assign (now reachable after Bug 1 fix)
```bash
curl -s -X POST "$BASE_URL/api/v1/leads/bulk-assign" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"caseIds\":[\"$LEAD_ID\"],\"assignTo\":\"paralegal@zadlegal.com\"}" | jq .

# Over limit → 400
curl -s -X POST "$BASE_URL/api/v1/leads/bulk-assign" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"caseIds":[],"assignTo":""}' | jq .error
```

### GET /leads/export/csv (now reachable after Bug 1 fix)
```bash
curl -s -H "X-API-Key: $API_KEY" \
  "$BASE_URL/api/v1/leads/export/csv" \
  -o leads_export.csv && head -3 leads_export.csv

# With filters
curl -s -H "X-API-Key: $API_KEY" \
  "$BASE_URL/api/v1/leads/export/csv?status=Qualified" \
  -o qualified.csv
```

### POST /internal/tasks/followup (Cloud Tasks handler — Bug 2 fixed)
```bash
# In production this is called by Cloud Tasks with an OIDC token.
# In development (APP_ENV=development) OIDC check is skipped for easy testing:
curl -s -X POST "$BASE_URL/api/v1/leads/internal/tasks/followup" \
  -H "Content-Type: application/json" \
  -d "{\"caseId\":\"$LEAD_ID\"}" | jq .
# {"status":"skipped","reason":"Follow-up already created"} or {"status":"created","taskId":"..."}
```

### Partner admin endpoints (require admin JWT)
```bash
# List partners
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  "$BASE_URL/api/v1/admin/partners" | jq .[].name

# Create partner
NEW_PARTNER=$(curl -s -X POST "$BASE_URL/api/v1/admin/partners" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Acme Leads","allowedIps":[],"requireHmac":false}')
echo $NEW_PARTNER | jq .partnerId
PARTNER_ID=$(echo $NEW_PARTNER | jq -r .partnerId)

# Generate API key
NEW_KEY=$(curl -s -X POST "$BASE_URL/api/v1/admin/partners/$PARTNER_ID/keys" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"label":"key-1"}')
echo $NEW_KEY | jq .apiKey   # shown once only — save this

KEY_ID=$(echo $NEW_KEY | jq -r .keyId)

# Partner stats
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  "$BASE_URL/api/v1/admin/partners/$PARTNER_ID/stats" | jq .

# Revoke key
curl -s -X DELETE \
  "$BASE_URL/api/v1/admin/partners/$PARTNER_ID/keys/$KEY_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq .status

# Non-admin → 403
curl -s -X POST "$BASE_URL/api/v1/admin/partners" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"Should fail"}' | jq .error
```

### Cloud Functions — manual test via Pub/Sub
```bash
# Test vcf_screener (triggers full pipeline: screener → screened topic → dispatcher)
gcloud pubsub topics publish lead-created \
  --message="{\"caseId\":\"$LEAD_ID\",\"partnerId\":\"test\",\"requestId\":\"manual-test\"}" \
  --project=$PROJECT_ID

# Check function logs
gcloud functions logs read vcf-screener --region=$REGION --limit=20 --project=$PROJECT_ID
gcloud functions logs read notification-dispatcher --region=$REGION --limit=20 --project=$PROJECT_ID
```

### followup_monitor — manual trigger
```bash
MONITOR_URL=$(gcloud functions describe followup-monitor \
  --region=$REGION --format="value(serviceConfig.uri)" --project=$PROJECT_ID)

curl -s -X POST "$MONITOR_URL" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{}' | jq .
```

### Rate limit test
```bash
# Burst 105 requests — requests 101+ should return 429
for i in $(seq 1 105); do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "X-API-Key: $API_KEY" "$BASE_URL/api/v1/leads")
  echo "Request $i: HTTP $CODE"
done
```

---

## 7. Verify bug fixes after deploy

```bash
# Bug 1: confirm /bulk-assign is NOT treated as a lead ID
curl -s -X POST "$BASE_URL/api/v1/leads/bulk-assign" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"caseIds":["ZAD-2026-03-0001"],"assignTo":"paralegal@zadlegal.com"}' | jq .
# Must return {updated:[...]} NOT {error:"NOT_FOUND"}

# Bug 1: confirm /export/csv is NOT treated as a lead ID
curl -s -H "X-API-Key: $API_KEY" "$BASE_URL/api/v1/leads/export/csv" \
  -o /tmp/test.csv && file /tmp/test.csv
# Must return CSV file NOT a 404 JSON error

# Bug 2: in production, /internal/tasks/followup without token returns 401
curl -s -X POST "$BASE_URL/api/v1/leads/internal/tasks/followup" \
  -H "Content-Type: application/json" \
  -d '{"caseId":"ZAD-2026-03-0001"}' | jq .error
# Must return UNAUTHORIZED (when APP_ENV=production)

# Bug 4: confirm followup_monitor does not 500 on first run
# (requires index to exist — deploy it first in step 2)
curl -s -X POST "$MONITOR_URL" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{}' | jq .errors
# Must be 0, not a 500
```
