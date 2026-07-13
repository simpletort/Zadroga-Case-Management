# Storage Gateway Service

Central gatekeeper for all Google Cloud Storage file access. Generates signed URLs for secure upload/download, tracks virus scan status, manages GCS lifecycle rules, and exposes document metadata stored in Firestore.

**Base URL (dev):** `https://storage-gateway-292736139819.us-central1.run.app`

All endpoints require a Firebase JWT (`Authorization: Bearer <token>`) unless noted otherwise.

---

## Endpoints

- [POST /api/v1/storage/upload/register](#post-apiv1storageuploadregister)
- [GET /api/v1/storage/upload/{file_id}/status](#get-apiv1storageuploadfile_idstatus)
- [GET /api/v1/storage/signed-url](#get-apiv1storagesigned-url)
- [GET /api/v1/storage/{file_id}/metadata](#get-apiv1storagefile_idmetadata)
- [GET /api/v1/storage/cases/{case_id}/documents](#get-apiv1storagecasescase_iddocuments)
- [PATCH /api/v1/storage/cases/{case_id}/documents/{file_id}](#patch-apiv1storagecasescase_iddocumentsfile_id)
- [GET /api/v1/storage/lifecycle](#get-apiv1storagelifecycle)
- [PUT /api/v1/storage/lifecycle](#put-apiv1storagelifecycle)
- [POST /api/v1/storage/lifecycle/apply-default](#post-apiv1storagelifecycleapply-default)
- [PUT /api/v1/storage/lifecycle/soft-delete](#put-apiv1storagelifecyclesoft-delete)
- [PUT /api/v1/storage/cases/{case_id}/hold](#put-apiv1storagecasescase_idhold)

---

## Upload & Virus Scanning

### POST /api/v1/storage/upload/register

Registers a new file upload. Returns a staging signed URL for the client to PUT the file directly to GCS. After upload, a Cloud Function automatically runs a ClamAV virus scan.

**Min role:** `paralegal`

**Request body:**
```json
{
  "file_name": "records_2024.pdf",
  "category": "medical-records",
  "content_type": "application/pdf",
  "case_id": "ZAD-2024-01-0042",
  "size_bytes": 204800
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `file_name` | string | yes | Original file name |
| `category` | string | yes | Document category (see [Document Categories](#document-categories)) |
| `content_type` | string | yes | MIME type (e.g. `application/pdf`) |
| `case_id` | string | no | Required for case-scoped categories |
| `size_bytes` | integer | yes | File size in bytes |

**Response `201 Created`:**
```json
{
  "file_id": "f3a2bc19-...",
  "staging_path": "staging/f3a2bc19-.../records_2024.pdf",
  "signed_url": "https://storage.googleapis.com/...",
  "expires_at": "2024-03-15T12:30:00Z",
  "scan_status": "pending"
}
```

The client must PUT the file bytes to `signed_url` within the expiry window. After upload, poll the status endpoint until `scan_status` is `clean` before treating the file as available.

---

### GET /api/v1/storage/upload/{file_id}/status

Polls the virus scan status for a registered upload.

**Min role:** `paralegal`

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `file_id` | string | File ID returned by register endpoint |

**Response `200 OK`:**
```json
{
  "file_id": "f3a2bc19-...",
  "scan_status": "clean"
}
```

**`scan_status` values:**

| Value | Description |
|---|---|
| `pending` | File registered but not yet uploaded to GCS |
| `scanning` | Cloud Function has picked up the file |
| `clean` | Passed ClamAV scan; file moved to final GCS path |
| `infected` | Malware detected; file quarantined; staff notified via Pub/Sub |
| `error` | Scan failed; alert sent to Cloud Logging |

---

## Signed URLs

### GET /api/v1/storage/signed-url

Generates a short-lived signed URL for direct GCS read or write access.

**Min role:** `paralegal`

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `category` | string | yes | Document category (see [Document Categories](#document-categories)) |
| `file_name` | string | yes | Original file name |
| `action` | string | yes | `read` for download, `write` for upload |
| `case_id` | string | no | Required for case-scoped categories |
| `content_type` | string | no | MIME type — required when `action` is `write` |

**Response `200 OK`:**
```json
{
  "signed_url": "https://storage.googleapis.com/...",
  "blob_path": "ZAD-2024-01-0042/medical-records/records_2024.pdf",
  "bucket": "zadroga-case-files-simpletort-zadroga-dev",
  "expires_at": "2024-03-15T12:30:00Z",
  "action": "read"
}
```

---

## File Metadata

### GET /api/v1/storage/{file_id}/metadata

Retrieves Firestore metadata for a single file.

**Min role:** `paralegal`

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `file_id` | string | File ID |

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `case_id` | string | yes | Case that owns this document |

**Response `200 OK`:**
```json
{
  "file_id": "f3a2bc19-...",
  "case_id": "ZAD-2024-01-0042",
  "file_name": "records_2024.pdf",
  "category": "medical-records",
  "gcs_path": "ZAD-2024-01-0042/medical-records/records_2024.pdf",
  "content_type": "application/pdf",
  "size_bytes": 204800,
  "uploaded_at": "2024-03-15T11:00:00Z",
  "scan_status": "clean",
  "processing_status": "completed",
  "verification_status": "approved",
  "extracted_data": {}
}
```

---

## Document Management

### GET /api/v1/storage/cases/{case_id}/documents

Lists all documents for a case with optional filtering and cursor-based pagination.

**Min role:** `paralegal`

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `case_id` | string | Case ID |

**Query parameters:**

| Parameter | Type | Description |
|---|---|---|
| `category` | string | Filter by document category |
| `processing_status` | string | `pending` \| `in_progress` \| `completed` \| `failed` |
| `verification_status` | string | `unreviewed` \| `approved` \| `rejected` \| `manual_review` |
| `scan_status` | string | `pending` \| `scanning` \| `clean` \| `infected` \| `error` |
| `uploaded_after` | string | ISO-8601 datetime |
| `uploaded_before` | string | ISO-8601 datetime |
| `page_size` | integer | 1–100, default `20` |
| `page_token` | string | `file_id` of the last document from the previous page |

**Response `200 OK`:**
```json
{
  "case_id": "ZAD-2024-01-0042",
  "documents": [
    {
      "file_id": "f3a2bc19-...",
      "case_id": "ZAD-2024-01-0042",
      "file_name": "records_2024.pdf",
      "category": "medical-records",
      "gcs_path": "ZAD-2024-01-0042/medical-records/records_2024.pdf",
      "content_type": "application/pdf",
      "size_bytes": 204800,
      "uploaded_at": "2024-03-15T11:00:00Z",
      "scan_status": "clean",
      "processing_status": "completed",
      "verification_status": "unreviewed",
      "extracted_data": {}
    }
  ],
  "next_page_token": "f3a2bc19-..."
}
```

`next_page_token` is omitted when there are no more pages.

---

### PATCH /api/v1/storage/cases/{case_id}/documents/{file_id}

Updates processing or verification metadata on a document. All fields are optional; only provided fields are updated.

**Min role:** `paralegal`

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `case_id` | string | Case ID |
| `file_id` | string | File ID |

**Request body:**
```json
{
  "processing_status": "completed",
  "verification_status": "approved",
  "extracted_data": {
    "diagnosis": "Reactive Airway Disease",
    "date_of_service": "2023-11-01"
  }
}
```

| Field | Type | Description |
|---|---|---|
| `processing_status` | string | `pending` \| `in_progress` \| `completed` \| `failed` |
| `verification_status` | string | `unreviewed` \| `approved` \| `rejected` \| `manual_review` |
| `extracted_data` | object | Arbitrary key-value pairs from AI extraction |

**Response `200 OK`:** Full document metadata object (same shape as the metadata endpoint).

---

## Lifecycle Management

All lifecycle endpoints require **`system_admin`** role.

### GET /api/v1/storage/lifecycle

Returns the current GCS lifecycle rules and soft-delete retention for the case files bucket.

**Response `200 OK`:**
```json
{
  "bucket": "zadroga-case-files-simpletort-zadroga-dev",
  "rules": [
    {
      "action": {
        "type": "Delete",
        "storageClass": null
      },
      "condition": {
        "age_days": 1,
        "matches_prefix": ["staging/"]
      }
    }
  ],
  "soft_delete_retention_days": 7
}
```

---

### PUT /api/v1/storage/lifecycle

Replaces the bucket's lifecycle rules with the provided set.

**Request body:**
```json
{
  "rules": [
    {
      "action": {
        "type": "Delete"
      },
      "condition": {
        "age_days": 1,
        "matches_prefix": ["staging/"]
      }
    },
    {
      "action": {
        "type": "SetStorageClass",
        "storageClass": "NEARLINE"
      },
      "condition": {
        "age_days": 180,
        "matches_prefix": []
      }
    }
  ]
}
```

**Response `200 OK`:**
```json
{
  "bucket": "zadroga-case-files-simpletort-zadroga-dev",
  "rules_applied": 2,
  "message": "Lifecycle rules updated successfully."
}
```

---

### POST /api/v1/storage/lifecycle/apply-default

Resets the bucket to the standard Zadroga lifecycle policy.

**Default rules applied:**

| Prefix | Action | After |
|---|---|---|
| `staging/` | Delete | 1 day |
| `quarantine/` | Delete | 90 days |
| *(all)* | Move to NEARLINE | 180 days |
| *(all)* | Move to COLDLINE | 365 days |

**Response `200 OK`:**
```json
{
  "bucket": "zadroga-case-files-simpletort-zadroga-dev",
  "rules_applied": 4,
  "message": "Default Zadroga lifecycle policy applied successfully."
}
```

---

### PUT /api/v1/storage/lifecycle/soft-delete

Configures the bucket's soft-delete retention window.

**Request body:**
```json
{
  "retention_days": 30
}
```

| Field | Type | Constraints |
|---|---|---|
| `retention_days` | integer | 7–90 |

**Response `200 OK`:**
```json
{
  "bucket": "zadroga-case-files-simpletort-zadroga-dev",
  "retention_days": 30,
  "message": "Soft-delete retention updated to 30 days."
}
```

---

### PUT /api/v1/storage/cases/{case_id}/hold

Places or releases a `temporaryHold` on all documents for a case, preventing lifecycle transitions from deleting or changing their storage class while the hold is active.

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `case_id` | string | Case ID |

**Request body:**
```json
{
  "hold": true
}
```

**Response `200 OK`:**
```json
{
  "case_id": "ZAD-2024-01-0042",
  "hold": true,
  "documents_updated": 12,
  "message": "Hold applied to 12 documents."
}
```

---

## Reference

### Document Categories

| Category | GCS Path |
|---|---|
| `medical-records` | `{case_id}/medical-records/` |
| `proof-of-presence` | `{case_id}/proof-of-presence/` |
| `id-documents` | `{case_id}/id-documents/` |
| `legal-forms` | `{case_id}/legal-forms/` |
| `vcf-documents` | `{case_id}/vcf-documents/` |
| `settlement-docs` | `{case_id}/settlement-docs/` |
| `client-uploads` | `client-uploads/` |
| `lead-attachments` | `temp-lead-attachments/` |

### GCS Prefixes

| Prefix | Purpose |
|---|---|
| `staging/{file_id}/{file_name}` | Upload landing zone — virus scanner reads from here |
| `quarantine/{timestamp}/{file_id}/{file_name}` | Infected files — auto-deleted after 90 days |

### RBAC Role Hierarchy

```
admin_staff → paralegal → junior_partner → senior_partner → system_admin
```

Higher roles inherit all permissions of lower roles. All lifecycle endpoints require `system_admin`.
