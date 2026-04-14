# Notification Delivery Tracking — Firestore Schema

## Overview

All notification delivery events (SMS + Email) are written to **two places**:

| Collection | Purpose |
|---|---|
| `cases/{caseId}/notifications/{notificationId}` | Case-scoped subcollection — fast per-case timeline queries |
| `notifications/{notificationId}` | Top-level collection — cross-case queries by status, channel, date |

Both documents are **identical in schema** — written atomically in the same service call.
The subcollection path makes it trivial to fetch the full notification history for a case
without a query (just `.collection("notifications").stream()`).

---

## Document Schema

### Path
```
cases/{caseId}/notifications/{notificationId}
notifications/{notificationId}
```

### Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `notificationId` | `string` | ✅ | UUID — document ID, same in both collections |
| `caseId` | `string` | ✅ | Firestore case document ID (e.g. `ZAD-2024-01-0001`) |
| `clientId` | `string` | ✅ | Client identifier from the case `leadData` |
| `channel` | `string` | ✅ | `"SMS"` or `"EMAIL"` |
| `templateId` | `string` | ✅ | Firestore template ID (e.g. `welcome_email`) |
| `status` | `string` | ✅ | `"sent"` \| `"delivered"` \| `"failed"` \| `"bounced"` \| `"opted_out"` \| `"template_error"` |
| `sentAt` | `timestamp` | ✅ | When the API call was made (Twilio/SendGrid accepted) |
| `deliveredAt` | `timestamp` | ❌ | Set on webhook confirmation (Twilio delivered / SendGrid delivered event) |
| `errorMessage` | `string` | ❌ | Human-readable error — null on success |
| `errorCode` | `integer` | ❌ | Provider error code (Twilio error code / SendGrid status code) |
| `retryCount` | `integer` | ✅ | Number of dispatch attempts. Starts at `0`, incremented on each retry |
| `requestId` | `string` | ✅ | Upstream trace ID for log correlation |
| `providerMessageId` | `string` | ❌ | Twilio `MessageSid` or SendGrid `X-Message-Id` |
| `createdAt` | `timestamp` | ✅ | `SERVER_TIMESTAMP` — Firestore write time |
| `updatedAt` | `timestamp` | ✅ | `SERVER_TIMESTAMP` — last status update time |

### Channel-specific fields (SMS only)

| Field | Type | Description |
|---|---|---|
| `smsSegmentCount` | `integer` | Number of SMS segments billed |
| `smsCharCount` | `integer` | Character count of rendered body |
| `twilioStatus` | `string` | Raw Twilio status: `queued`, `sent`, `delivered`, `failed`, `undelivered` |

### Channel-specific fields (EMAIL only)

| Field | Type | Description |
|---|---|---|
| `emailSubject` | `string` | Rendered subject line (no PII — variables already substituted) |
| `sendgridStatusCode` | `integer` | HTTP status code from SendGrid API response |

---

## Status Lifecycle

```
                    ┌─────────────┐
                    │   queued    │  (Cloud Tasks scheduled, not yet dispatched)
                    └──────┬──────┘
                           │ dispatch attempt
                    ┌──────▼──────┐
               ┌────│    sent     │────┐
               │    └──────┬──────┘   │
               │           │ webhook  │ error
        ┌──────▼──────┐    │          │
        │  delivered  │    │    ┌─────▼──────┐
        └─────────────┘    │    │   failed   │──► retryCount++
                           │    └─────┬──────┘
                    ┌──────▼──────┐   │ max retries
                    │   bounced   │   │ exceeded
                    └─────────────┘   ▼
                                  (permanent fail)
```

---

## Example Documents

### SMS — Sent Successfully
```json
{
  "notificationId": "a1b2c3d4-0001-4abc-8def-000000000001",
  "caseId": "ZAD-2024-01-0001",
  "clientId": "lead-john-doe-001",
  "channel": "SMS",
  "templateId": "welcome_sms",
  "status": "delivered",
  "sentAt": "2026-04-09T08:00:00Z",
  "deliveredAt": "2026-04-09T08:00:04Z",
  "errorMessage": null,
  "errorCode": null,
  "retryCount": 0,
  "requestId": "cli-abc12345",
  "providerMessageId": "SMabc123def456",
  "smsSegmentCount": 1,
  "smsCharCount": 122,
  "twilioStatus": "delivered",
  "createdAt": "<SERVER_TIMESTAMP>",
  "updatedAt": "<SERVER_TIMESTAMP>"
}
```

### Email — Failed (Sender Unverified)
```json
{
  "notificationId": "b2c3d4e5-0002-4abc-8def-000000000002",
  "caseId": "ZAD-2024-01-0001",
  "clientId": "lead-john-doe-001",
  "channel": "EMAIL",
  "templateId": "welcome_email",
  "status": "failed",
  "sentAt": "2026-04-09T08:05:00Z",
  "deliveredAt": null,
  "errorMessage": "HTTP Error 403: Forbidden",
  "errorCode": 403,
  "retryCount": 1,
  "requestId": "qa-tc1-a1b2c3d4",
  "providerMessageId": null,
  "emailSubject": "Welcome to Zadroga Law, John Doe — Your Case ZAD-2024-01-0001",
  "sendgridStatusCode": 403,
  "createdAt": "<SERVER_TIMESTAMP>",
  "updatedAt": "<SERVER_TIMESTAMP>"
}
```

### Email — Bounced (via Webhook)
```json
{
  "notificationId": "c3d4e5f6-0003-4abc-8def-000000000003",
  "caseId": "ZAD-2024-01-0001",
  "clientId": "lead-john-doe-001",
  "channel": "EMAIL",
  "templateId": "document_reminder_48hr_email",
  "status": "bounced",
  "sentAt": "2026-04-09T09:00:00Z",
  "deliveredAt": null,
  "errorMessage": "550 5.1.1 The email account does not exist",
  "errorCode": 550,
  "retryCount": 0,
  "requestId": "task-reminder-48hr",
  "providerMessageId": "SGmsg-xyz789",
  "emailSubject": "Action Required: Documents Needed for Case ZAD-2024-01-0001",
  "sendgridStatusCode": 202,
  "createdAt": "<SERVER_TIMESTAMP>",
  "updatedAt": "<SERVER_TIMESTAMP>"
}
```

---

## Indexing Requirements

### Composite Indexes Required

| Collection | Fields | Order | Query Use Case |
|---|---|---|---|
| `notifications` | `caseId` ASC, `createdAt` DESC | ↑ ↓ | All notifications for a case, newest first |
| `notifications` | `status` ASC, `createdAt` DESC | ↑ ↓ | Dashboard: all failed/bounced notifications |
| `notifications` | `channel` ASC, `status` ASC, `createdAt` DESC | ↑ ↑ ↓ | Failed SMS only / Failed EMAIL only |
| `notifications` | `caseId` ASC, `channel` ASC, `createdAt` DESC | ↑ ↑ ↓ | All SMS for a case / All emails for a case |
| `notifications` | `caseId` ASC, `status` ASC, `createdAt` DESC | ↑ ↑ ↓ | Failed notifications for a specific case |
| `notifications` | `templateId` ASC, `status` ASC, `createdAt` DESC | ↑ ↑ ↓ | Template performance reporting |
| `notifications` | `retryCount` ASC, `status` ASC, `createdAt` DESC | ↑ ↑ ↓ | Find notifications that exhausted retries |

### Single-field Indexes (auto-created by Firestore)
- `notificationId` — document ID
- `caseId`
- `status`
- `channel`
- `createdAt`
- `sentAt`

### Subcollection Indexes
The subcollection `cases/{caseId}/notifications` only needs:
- `createdAt` DESC — timeline view per case
- `status` ASC, `createdAt` DESC — filter by status within a case
- `channel` ASC, `createdAt` DESC — filter by channel within a case

---

## Migration from Existing Collections

Current collections to migrate:

| Old Collection | New Path | Notes |
|---|---|---|
| `sms_delivery_records` | `notifications` + `cases/{id}/notifications` | Add `channel=SMS`, `clientId`, `retryCount` |
| `email_delivery_records` | `notifications` + `cases/{id}/notifications` | Add `channel=EMAIL`, `clientId`, `retryCount` |

Old collections kept read-only for 30 days post-migration, then deleted.
