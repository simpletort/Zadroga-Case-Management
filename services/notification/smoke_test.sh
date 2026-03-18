#!/usr/bin/env bash
# =============================================================================
# smoke_test.sh — Manual smoke tests for the Notification Service
#
# Usage (local dev server running on :8080)
#   chmod +x smoke_test.sh
#   ./smoke_test.sh
#
# Usage (against deployed Cloud Run)
#   BASE_URL=https://notification-service-dev-uc.a.run.app ./smoke_test.sh
#
# The script uses Twilio's "magic" test numbers:
#   +15005550006 — always succeeds  (TWILIO_FROM_NUMBER for dev)
#   +15005550001 — queue is full
#   +15005550002 — invalid number
#
# Prerequisites:
#   curl, jq
# =============================================================================

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
PASS=0
FAIL=0

# Colour helpers
GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'

pass() { echo -e "${GREEN}✓ PASS${NC} — $1"; ((PASS++)); }
fail() { echo -e "${RED}✗ FAIL${NC} — $1 (got: $2)"; ((FAIL++)); }

check_status() {
  local label=$1
  local expected=$2
  local actual=$3
  if [ "$actual" -eq "$expected" ]; then
    pass "$label (HTTP $actual)"
  else
    fail "$label (expected HTTP $expected)" "$actual"
  fi
}

check_json() {
  local label=$1
  local field=$2
  local expected=$3
  local actual=$4
  if [ "$actual" = "$expected" ]; then
    pass "$label ($field=$actual)"
  else
    fail "$label ($field expected='$expected')" "$actual"
  fi
}

echo ""
echo "========================================"
echo " Notification Service — Smoke Tests"
echo " Base URL: $BASE_URL"
echo "========================================"
echo ""

# ── 1. Health check ───────────────────────────────────────────────────────────
echo "── 1. Health check"
RESP=$(curl -s -o /tmp/smoke_body.json -w "%{http_code}" "$BASE_URL/health")
check_status "GET /health" 200 "$RESP"
STATUS=$(jq -r '.status' /tmp/smoke_body.json 2>/dev/null || echo "parse_error")
check_json "GET /health body" "status" "healthy" "$STATUS"
echo ""

# ── 2. POST /tasks/sms — happy path (will actually send via Twilio in dev) ───
echo "── 2. POST /tasks/sms — valid payload"
RESP=$(curl -s -X POST "$BASE_URL/tasks/sms" \
  -H "Content-Type: application/json" \
  -o /tmp/smoke_body.json \
  -w "%{http_code}" \
  -d '{
    "to": "+15005550006",
    "templateId": "welcome_sms",
    "variables": {"first_name": "SmokeTest", "case_id": "ZAD-2025-99-0001"},
    "caseId": "ZAD-2025-99-0001",
    "requestId": "smoke-test-001"
  }')
check_status "POST /tasks/sms (valid)" 200 "$RESP"
SUCCESS=$(jq -r '.success' /tmp/smoke_body.json 2>/dev/null || echo "parse_error")
check_json "POST /tasks/sms body.success" "success" "true" "$SUCCESS"
DELIVERY_ID=$(jq -r '.deliveryId' /tmp/smoke_body.json 2>/dev/null || echo "")
echo "  deliveryId: $DELIVERY_ID"
echo ""

# ── 3. POST /tasks/sms — missing required field ───────────────────────────────
echo "── 3. POST /tasks/sms — missing 'to' field (expect 422)"
RESP=$(curl -s -X POST "$BASE_URL/tasks/sms" \
  -H "Content-Type: application/json" \
  -o /tmp/smoke_body.json \
  -w "%{http_code}" \
  -d '{"templateId": "welcome_sms", "variables": {}}')
check_status "POST /tasks/sms (missing 'to')" 422 "$RESP"
echo ""

# ── 4. POST /tasks/sms — unknown template (expect 200 with template_error) ───
echo "── 4. POST /tasks/sms — non-existent template"
RESP=$(curl -s -X POST "$BASE_URL/tasks/sms" \
  -H "Content-Type: application/json" \
  -o /tmp/smoke_body.json \
  -w "%{http_code}" \
  -d '{
    "to": "+15005550006",
    "templateId": "does_not_exist_template",
    "variables": {},
    "requestId": "smoke-test-003"
  }')
check_status "POST /tasks/sms (unknown template)" 200 "$RESP"
TSTATUS=$(jq -r '.status' /tmp/smoke_body.json 2>/dev/null || echo "parse_error")
check_json "POST /tasks/sms body.status" "status" "template_error" "$TSTATUS"
echo ""

# ── 5. POST /webhooks/twilio/inbound — STOP keyword ──────────────────────────
echo "── 5. POST /webhooks/twilio/inbound — STOP"
RESP=$(curl -s -X POST "$BASE_URL/webhooks/twilio/inbound" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -o /tmp/smoke_body.txt \
  -w "%{http_code}" \
  --data-urlencode "From=+15005550006" \
  --data-urlencode "Body=STOP")
check_status "POST /webhooks/twilio/inbound (STOP)" 200 "$RESP"
if grep -q "<Response>" /tmp/smoke_body.txt 2>/dev/null; then
  pass "TwiML <Response> in body"
else
  fail "TwiML <Response> in body" "$(cat /tmp/smoke_body.txt)"
fi
echo ""

# ── 6. POST /webhooks/twilio/inbound — START (re-subscribe) ──────────────────
echo "── 6. POST /webhooks/twilio/inbound — START"
RESP=$(curl -s -X POST "$BASE_URL/webhooks/twilio/inbound" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -o /tmp/smoke_body.txt \
  -w "%{http_code}" \
  --data-urlencode "From=+15005550006" \
  --data-urlencode "Body=START")
check_status "POST /webhooks/twilio/inbound (START)" 200 "$RESP"
echo ""

# ── 7. POST /tasks/sms — opted-out number (should now be opted out from step 5)
echo "── 7. POST /tasks/sms — opted-out number (expect status=opted_out)"
RESP=$(curl -s -X POST "$BASE_URL/tasks/sms" \
  -H "Content-Type: application/json" \
  -o /tmp/smoke_body.json \
  -w "%{http_code}" \
  -d '{
    "to": "+15005550006",
    "templateId": "welcome_sms",
    "variables": {"first_name": "SmokeOptOut"},
    "requestId": "smoke-test-007"
  }')
# NOTE: This will only show "opted_out" if Firestore has the opt-out record
# from step 5 (i.e. running against a real Firestore instance, not a mock).
# Against a local dev server without Firestore it will show "sent".
check_status "POST /tasks/sms (opted-out check)" 200 "$RESP"
TSTATUS=$(jq -r '.status' /tmp/smoke_body.json 2>/dev/null || echo "parse_error")
echo "  (status='$TSTATUS' — 'opted_out' expected only if Firestore is live)"
echo ""

# ── Summary ───────────────────────────────────────────────────────────────────
echo "========================================"
echo " Results:  ${PASS} passed  /  ${FAIL} failed"
echo "========================================"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
