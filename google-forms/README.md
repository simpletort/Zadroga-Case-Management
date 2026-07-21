# SimpleTort — Client Intake Form Setup Guide

This document covers the one-time setup of the Google Form and Apps Script
that power the tokenized, pre-filled intake experience.

`Code.gs` includes a `createIntakeForm()` function that builds the form
structure, sections, questions, and branching logic automatically. Two things
remain manual regardless — Apps Script's `FormApp` service cannot create
file-upload questions or set form branding (header image / theme color); both
are UI-only, with no scriptable equivalent.

---

## Prerequisites

- Google Workspace account with access to Google Forms, Sheets, Apps Script, and Drive
- `intake-form-dispatcher` and `intake-drive-sync` Cloud Functions deployed
- GCP Secret Manager secrets created:
  - `SENDGRID_API_KEY` — SendGrid API key
  - `INTAKE_DRIVE_SYNC_SECRET` — shared secret (generate a random UUID)
- A partner API key provisioned in Firestore (`partners` collection, `active: true`)
  for calling case-development's API — see `services/case-development` for the
  partner-key auth path

---

## Step 1 — Create the Sheet and Paste the Script

1. Create a new blank Google Sheet. Name it "SimpleTort Intake Responses".
2. Open **Extensions → Apps Script**.
3. Delete all default content in `Code.gs` and paste the contents of
   `google-forms/apps-script/Code.gs`.
4. Open `appsscript.json` via **Project Settings → Show "appsscript.json"
   manifest file** and replace it with the contents of
   `google-forms/apps-script/appsscript.json`.

   > The manifest already declares the Drive API in `enabledAdvancedServices` —
   > Apps Script enables it automatically. **Do NOT also add Drive via the
   > Services panel** — doing so when it's already in the manifest causes
   > `"Found a service identifier used more than once: Drive"` on save. If you
   > already added it via the panel, go to **Services → three-dot menu next to
   > Drive API → Remove**, then save again.

5. At the top of `Code.gs`, update these constants:

```javascript
var PROJECT_ID            = "your-gcp-project-id";
var INTAKE_DRIVE_SYNC_URL = "https://REGION-PROJECT_ID.cloudfunctions.net/intake-drive-sync/sync";
var DRIVE_SYNC_SECRET     = "...";  // value of Secret Manager secret INTAKE_DRIVE_SYNC_SECRET
var ADMIN_EMAIL           = "admin@yourfirm.com";
var CASE_API_BASE         = "https://your-case-development-cloud-run-url/api/v1";
var CASE_API_KEY          = "...";  // partner API key (see Prerequisites)
```

Optionally, set `SENDGRID_API_KEY` if you prefer SendGrid for reminder emails
(leave blank to use GmailApp).

---

## Step 2 — Run `createIntakeForm()`

1. In the Apps Script editor, select **`createIntakeForm`** from the function dropdown.
2. Click **▶ Run**.
3. Approve the OAuth consent prompts (form creation + Sheet access).
4. Check the **Execution Log** for the form's edit and public URLs, and a
   reminder of the manual steps still required (Step 3 below).

This creates a form titled **"SimpleTort Client Intake Form"** with every
section, question, and branching rule below, links its responses to the
current Sheet, and installs both triggers (`onIntakeFormSubmit` on form
submit, `dailyReminderCheck` daily 6am–7am) — so Step 7 from earlier versions
of this guide is no longer a separate manual step.

**Titles must match exactly** — Apps Script and the pre-fill URL use them by
name, and `createIntakeForm()` sources them from the same `Q_*` constants
`onIntakeFormSubmit` reads, so they can't drift.

### Section 1 — About You
| Question title | Type | Required | Notes |
|----------------|------|----------|-------|
| First Name | Short answer | Yes | Pre-filled via URL |
| Last Name | Short answer | Yes | Pre-filled via URL |
| Email Address | Short answer | Yes | Pre-filled via URL |
| Phone Number | Short answer | Yes | Pre-filled via URL |
| Intake Token | Short answer | Yes | Pre-filled via URL — help text "Do not edit this field" |

### Section 2 — WTC Health Program Status
| Question title | Type | Required |
|----------------|------|----------|
| WTC Health Program Status | Multiple choice | Yes |

Choices: `Enrolled` / `Applied` / `Not Applied` / `Unknown`

Branching: `Enrolled` → Section 3A (WTC Member Details); `Applied`, `Not Applied`,
`Unknown` → Section 3B (Exposure Description).

### Section 3A — WTC Member Details *(if enrolled)*
| Question title | Type | Required |
|----------------|------|----------|
| WTC Member ID | Short answer | No |
| Medical Conditions (WTC-related) | Paragraph | No |

At end of section → Section 4 (VCF Claim History)

### Section 3B — Exposure Description *(if not enrolled)*
| Question title | Type | Required |
|----------------|------|----------|
| Exposure Description | Paragraph | Yes |

At end of section → Section 4 (VCF Claim History)

### Section 4 — VCF Claim History
| Question title | Type | Required |
|----------------|------|----------|
| Have you filed a prior VCF claim? | Multiple choice | Yes |

Choices: `Yes` / `No`

Branching: `Yes` → Section 5A (Prior Claim Details); `No` → Section 5B (placeholder).

### Section 5A — Prior Claim Details *(if yes)*
| Question title | Type | Required |
|----------------|------|----------|
| Prior VCF Claim Number | Short answer | No |
| Prior VCF Claim Status | Multiple choice | No |

Choices for "Prior VCF Claim Status": `Pending` / `Approved` / `Denied` / `On Appeal`

At end of section → Section 6 (Deceased Claimant)

### Section 5B *(placeholder — no questions)*
At end of section → Section 6 (Deceased Claimant)

### Section 6 — Deceased Claimant
| Question title | Type | Required |
|----------------|------|----------|
| Is the claimant deceased? | Multiple choice | Yes |

Choices: `Yes` / `No`

Branching: `Yes` → Section 7 (Estate Documents); `No` → Section 8 (Document Uploads).

### Section 7 — Estate Documents *(if deceased)*
Created by `createIntakeForm()` as an empty section — see Step 3 for the
questions that must be added by hand.

At end of section → Section 8 (Document Uploads)

### Section 8 — Document Uploads
Created by `createIntakeForm()` as an empty section — see Step 3 for the
questions that must be added by hand.

---

## Step 3 — Manual Steps `createIntakeForm()` Can't Automate

Apps Script's `FormApp` service has no way to create file-upload questions or
set form branding — both are Forms-UI-only, with no equivalent in `FormApp` or
the Forms REST API.

### File uploads
Open the form in the editor and add these questions to the sections
`createIntakeForm()` already created:

**Section 7 — Estate Documents**
| Question title | Type | Required |
|----------------|------|----------|
| Upload Death Certificate | File upload | No |
| Upload Letters of Administration | File upload | No |

**Section 8 — Document Uploads**
| Question title | Type | Required |
|----------------|------|----------|
| Upload Medical Records | File upload | No |
| Upload Proof of Presence | File upload | No |
| Upload Photo ID | File upload | No |

> **File upload settings** (both sections): allow up to 10 files, max 10 MB
> per file, accept any file type.

### Branding
In the form editor (gear icon and paint-roller icon):
- **Collect email addresses**: confirm **OFF** (already set by `createIntakeForm()`)
- **Header image**: upload the firm logo (recommended size 1600 × 400 px)
- **Color**: set theme accent color to `#1A3C6B`

---

## Step 4 — Sync Entry IDs to Firestore (automated)

Once Step 3 is done, run the one-click sync function instead of extracting
entry IDs manually:

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

## Step 5 — Grant IAM Permissions

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

## Step 6 — Test End-to-End

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
- `cases/{caseId}.status == "Pending Paralegal Review"` in Firestore (via case-development's
  `PATCH /cases/{caseId}/status` — not written directly)
- Case profile fields (name/email/phone/exposure location/conditions) updated on
  `cases/{caseId}` via case-development's `PATCH /cases/{caseId}`, with a matching
  `audit_logs` entry
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
| Case profile/status update fails (logged, admin alert sent) | `CASE_API_BASE`/`CASE_API_KEY` incorrect, or partner key inactive/missing in Firestore `partners` | Check the constants and the `partners/{id}` doc's `active`/`apiKeys[]` fields |
| `Firestore PATCH returned 403` (intake_tokens writes) | Apps Script account lacks Firestore IAM role | Re-run Step 5 |
| Pre-fill URL has wrong values | Entry IDs set incorrectly | Re-run `syncFormEntryIds()` (Step 4) |
| `createIntakeForm()` throws "must be run from a Google Sheet's bound Apps Script project" | Run from a standalone script, not one bound to a Sheet | Follow Step 1 — paste the code into a Sheet's Apps Script project first |
