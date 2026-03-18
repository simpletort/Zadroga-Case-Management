# SimpleTort — Client Intake Form Setup Guide

This document covers the one-time manual setup of the Google Form and Apps Script
that power the tokenized, pre-filled intake experience.

---

## Prerequisites

- Google Workspace account with access to Google Forms, Sheets, Apps Script, and Drive
- `intake-form-dispatcher` and `intake-drive-sync` Cloud Functions deployed
- GCP Secret Manager secrets created:
  - `SENDGRID_API_KEY` — SendGrid API key
  - `INTAKE_DRIVE_SYNC_SECRET` — shared secret (generate a random UUID)

---

## Step 1 — Create the Google Form

Open [Google Forms](https://forms.google.com) and create a new blank form titled
**"SimpleTort Client Intake Form"**.

### Form Settings (gear icon)
| Setting | Value |
|---------|-------|
| Collect email addresses | **OFF** (email is pre-filled in a field) |
| Limit to 1 response | **OFF** (token enforces single-use) |
| Confirmation message | *Thank you. Your intake form has been received. Our team will review your submission and be in touch within 2–3 business days.* |

### Branding
- **Header image**: upload the firm logo (recommended size 1600 × 400 px)
- **Color**: set theme accent color to `#1A3C6B`

---

## Step 2 — Build the Form Sections

Create each section with the exact question titles listed below.
**Titles must match exactly** — Apps Script and the pre-fill URL use them by name.

### Section 1 — About You
| Question title | Type | Required | Notes |
|----------------|------|----------|-------|
| First Name | Short answer | Yes | Pre-filled via URL |
| Last Name | Short answer | Yes | Pre-filled via URL |
| Email Address | Short answer | Yes | Pre-filled via URL |
| Phone Number | Short answer | Yes | Pre-filled via URL |
| Intake Token | Short answer | Yes | Pre-filled via URL — add description "**Do not edit this field**" |

### Section 2 — WTC Health Program Status
| Question title | Type | Required |
|----------------|------|----------|
| WTC Health Program Status | Multiple choice | Yes |

Choices: `Enrolled` / `Applied` / `Not Applied` / `Unknown`

**Branching**: click the three-dot menu on the question → "Go to section based on answer":
- `Enrolled` → Section 3A (WTC Member Details)
- `Applied`, `Not Applied`, `Unknown` → Section 3B (Exposure Description)

### Section 3A — WTC Member Details *(if enrolled)*
| Question title | Type | Required |
|----------------|------|----------|
| WTC Member ID | Short answer | No |
| Medical Conditions (WTC-related) | Paragraph | No |

At end of section: set "After section 3A" → **Go to section 4 (VCF History)**

### Section 3B — Exposure Description *(if not enrolled)*
| Question title | Type | Required |
|----------------|------|----------|
| Exposure Description | Paragraph | Yes |

At end of section: set "After section 3B" → **Go to section 4 (VCF History)**

### Section 4 — VCF Claim History
| Question title | Type | Required |
|----------------|------|----------|
| Have you filed a prior VCF claim? | Multiple choice | Yes |

Choices: `Yes` / `No`

**Branching**:
- `Yes` → Section 5A (Prior Claim Details)
- `No` → Section 5B (placeholder)

### Section 5A — Prior Claim Details *(if yes)*
| Question title | Type | Required |
|----------------|------|----------|
| Prior VCF Claim Number | Short answer | No |
| Prior VCF Claim Status | Multiple choice | No |

Choices for "Prior VCF Claim Status": `Pending` / `Approved` / `Denied` / `On Appeal`

At end of section: **Go to section 6 (Deceased Claimant)**

### Section 5B *(placeholder — no questions)*
At end of section: **Go to section 6 (Deceased Claimant)**

### Section 6 — Deceased Claimant
| Question title | Type | Required |
|----------------|------|----------|
| Is the claimant deceased? | Multiple choice | Yes |

Choices: `Yes` / `No`

**Branching**:
- `Yes` → Section 7 (Estate Documents)
- `No` → Section 8 (Document Uploads)

### Section 7 — Estate Documents *(if deceased)*
| Question title | Type | Required |
|----------------|------|----------|
| Upload Death Certificate | File upload | No |
| Upload Letters of Administration | File upload | No |

> **File upload settings**: allow up to 10 files, max 10 MB per file, accept any file type.

At end of section: **Go to section 8 (Document Uploads)**

### Section 8 — Document Uploads
| Question title | Type | Required |
|----------------|------|----------|
| Upload Medical Records | File upload | No |
| Upload Proof of Presence | File upload | No |
| Upload Photo ID | File upload | No |

> **File upload settings**: same as above.

---

## Step 3 — Get the Entry IDs for Pre-fill

1. Open the form in the editor
2. Click the three-dot menu → **"Get pre-filled link"**
3. Fill in a dummy value in every field and click **"Get link"**
4. Copy the generated URL — it looks like:
   ```
   https://docs.google.com/forms/d/FORM_ID/viewform?usp=pp_url
     &entry.111111111=Test
     &entry.222222222=User
     ...
   ```
5. Extract the `entry.XXXXXXXXX` value for each field and record them:

| Field | entry ID |
|-------|----------|
| First Name | `entry.XXXXXXXXX` |
| Last Name | `entry.XXXXXXXXX` |
| Email Address | `entry.XXXXXXXXX` |
| Phone Number | `entry.XXXXXXXXX` |
| Intake Token | `entry.XXXXXXXXX` |

6. Write these to the **Firestore config document** at `config/intake_form` in Firebase
   Console (Firestore → `config` collection → `intake_form` document):
   ```json
   {
     "formBaseUrl": "https://docs.google.com/forms/d/<FORM_ID>/viewform",
     "fieldMappings": {
       "firstName":   "entry.XXXXXXXXX",
       "lastName":    "entry.XXXXXXXXX",
       "email":       "entry.XXXXXXXXX",
       "phone":       "entry.XXXXXXXXX",
       "intakeToken": "entry.XXXXXXXXX"
     },
     "updatedAt": "<today's date>",
     "updatedBy": "your-email@simpletort.com"
   }
   ```

   > **No redeploy needed.** The `intake-form-dispatcher` reads this document on
   > cold start and caches it per instance. If you recreate the form and get new
   > entry IDs, just update this Firestore document — the next Cloud Run instance
   > will pick up the new mapping automatically.

---

## Step 4 — Link a Google Sheet and Open Apps Script

1. In the form editor, click the **Responses** tab → spreadsheet icon → **Create a new spreadsheet**
2. Name it "SimpleTort Intake Responses"
3. Open the linked Sheet → **Extensions → Apps Script**
4. Delete all default content in `Code.gs`
5. Paste the contents of `google-forms/apps-script/Code.gs`
6. Open `appsscript.json` via **Project Settings → Show "appsscript.json" manifest file**
   and replace with the contents of `google-forms/apps-script/appsscript.json`

---

## Step 5 — Update Constants in Code.gs

At the top of `Code.gs`, update these constants:

```javascript
var PROJECT_ID            = "your-gcp-project-id";
var INTAKE_DRIVE_SYNC_URL = "https://REGION-PROJECT_ID.cloudfunctions.net/intake-drive-sync/sync";
var DRIVE_SYNC_SECRET     = "...";  // value of Secret Manager secret INTAKE_DRIVE_SYNC_SECRET
var ADMIN_EMAIL           = "admin@yourfirm.com";
```

Optionally, set `SENDGRID_API_KEY` if you prefer SendGrid for reminder emails
(leave blank to use GmailApp).

---

## Step 6 — Enable Drive Advanced Service

1. In Apps Script, click **Services** (+ icon in left panel)
2. Find **Drive API** → select **v2** → click **Add**
3. Confirm `Drive` appears in the Services list

---

## Step 7 — Install the Triggers

1. In Apps Script, click **Triggers** (clock icon in left panel) → **+ Add Trigger**

**Trigger 1 — Form submission:**
| Setting | Value |
|---------|-------|
| Function | `onIntakeFormSubmit` |
| Event source | From spreadsheet |
| Event type | On form submit |

**Trigger 2 — Daily reminder:**
| Setting | Value |
|---------|-------|
| Function | `dailyReminderCheck` |
| Event source | Time-driven |
| Time-based trigger type | Day timer |
| Time of day | 6am to 7am |

---

## Step 8 — Grant IAM Permissions

The Apps Script runs as your Google account. Grant that account access to Firestore:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="user:your-google-account@gmail.com" \
  --role="roles/datastore.user"
```

For the `intake-drive-sync` Cloud Function to download Drive files, the Cloud Run
service account needs Drive read access. Share the Google Forms upload destination
folder with the service account email:

```
intake-drive-sync@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

---

## Step 9 — Test End-to-End

### Send a test intake form link
```bash
curl -X POST https://REGION-PROJECT_ID.cloudfunctions.net/intake-form-dispatcher/send \
  -H "Content-Type: application/json" \
  -H "X-Staff-UID: test-staff-uid" \
  -d '{"caseId": "ZAD-2026-03-0001"}'
```

Expected response:
```json
{
  "tokenId": "uuid-v4-...",
  "previewUrl": "https://docs.google.com/forms/d/.../viewform?entry.xxx=...",
  "emailSent": true
}
```

### Verify pre-fill
Open `previewUrl` in an incognito browser window — confirm all personal info fields
are populated and the Intake Token field contains the UUID.

### Submit the form
Fill in the remaining fields, upload test documents, and submit.

Check:
- `intake_tokens/{tokenId}.used == true` in Firestore
- `cases/{caseId}.status == "Pending Paralegal Review"` in Firestore
- `cases/{caseId}/documents` subcollection has records for each uploaded file
- GCS bucket contains objects at `{caseId}/medical-records/` etc.

### Test the 7-day reminder
1. In Firestore, temporarily set a test token's `createdAt` to 8 days ago
2. In Apps Script editor, run `dailyReminderCheck()` manually (▶ button)
3. Confirm reminder email arrives and `reminderSentAt` is set on the token

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `emailSent: false` | Missing/invalid `SENDGRID_API_KEY` | Check Secret Manager binding in Cloud Run |
| Token not found in Apps Script logs | `PROJECT_ID` constant incorrect | Update `Code.gs` PROJECT_ID |
| Drive file download fails | Service account not shared on Drive folder | Share folder with Cloud Run SA |
| `Firestore PATCH returned 403` | Apps Script account lacks Firestore IAM role | Re-run Step 8 |
| Pre-fill URL has wrong values | Entry IDs set incorrectly | Re-extract entry IDs (Step 3) |
