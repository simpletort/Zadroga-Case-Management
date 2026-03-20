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

## Step 3 — Sync Entry IDs to Firestore (automated)

After completing Steps 4–5 (Apps Script setup), run the one-click sync function
instead of extracting entry IDs manually:

1. In the Apps Script editor, select **`syncFormEntryIds`** from the function dropdown
2. Click **▶ Run**
3. Approve the OAuth consent prompt on first run (grants `forms.body.readonly`)
4. Check the **Execution Log** — you should see all 5 entry IDs confirmed:
   ```
   syncFormEntryIds complete — config/intake_form updated.
     formBaseUrl  : https://docs.google.com/forms/d/FORM_ID/viewform
     firstName    : entry.1111111111
     lastName     : entry.2222222222
     email        : entry.3333333333
     phone        : entry.4444444444
     intakeToken  : entry.5555555555
   intake-form-dispatcher will use these IDs on next cold start.
   ```

The function writes `config/intake_form` to Firestore automatically — no Firebase
Console, no URL copy-pasting, no manual extraction required.

> **Re-run any time** you recreate the form. The function does a full document
> replace, so new entry IDs are picked up immediately on the next
> `intake-form-dispatcher` cold start — no redeploy needed.

> **If the function throws** `"Could not find form questions: ..."`, one of the
> question titles in Section 1 doesn't match exactly. Check that the titles are
> spelled and capitalised as specified in Step 2 above.

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

## Step 6 — Drive Advanced Service (already declared in manifest)

The `appsscript.json` you pasted in Step 5 already declares the Drive API
in `enabledAdvancedServices` — Apps Script enables it automatically from the manifest.

> ⚠️ **Do NOT add Drive via the Services panel.** Adding it manually when it is
> already in the manifest causes this error on save:
> `"Found a service identifier used more than once: Drive"`
>
> If you already added it via the panel, go to **Services → three-dot menu next
> to Drive API → Remove** to resolve the conflict, then save again.

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
