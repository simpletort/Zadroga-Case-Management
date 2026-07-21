/**
 * SimpleTort — Intake Form Apps Script
 *
 * Bound to the Google Sheet linked to the intake Google Form.
 *
 * Two installable triggers are required (set up via Apps Script UI > Triggers):
 *   1. onIntakeFormSubmit  — From spreadsheet > On form submit
 *   2. dailyReminderCheck  — Time-driven > Day timer > 6am–7am
 *
 * See google-forms/README.md for full setup instructions.
 *
 * ── SETUP: update ALL constants in this section before deploying ─────────────
 */

var PROJECT_ID           = "YOUR_GCP_PROJECT_ID";
var FIRESTORE_REST_BASE  = "https://firestore.googleapis.com/v1/projects/" + PROJECT_ID + "/databases/(default)/documents";
var INTAKE_DRIVE_SYNC_URL = "https://YOUR_REGION-YOUR_PROJECT_ID.cloudfunctions.net/intake-drive-sync/sync";
var DRIVE_SYNC_SECRET    = "YOUR_DRIVE_SYNC_SECRET";  // must match CF Secret Manager value
var ADMIN_EMAIL          = "admin@simpletort.com";
var SENDGRID_API_KEY     = "";       // optional — leave blank to use GmailApp for reminders
var REMINDER_FROM_EMAIL  = "noreply@simpletort.com";

// Case-development API — case profile + status updates go through here, NOT direct
// Firestore writes (see onIntakeFormSubmit). Same X-API-Key pattern as
// integrations/lead-intake-google-form/LeadIntakeForm.gs.
// The key must belong to an active Firestore partners/{id} doc (active: true, with an
// apiKeys[] entry whose keyHash matches — see shared/shared/middlewares/auth.py). Any
// valid partner key is authenticated as role "partner" (fixed by the middleware, not
// configurable per-partner-doc) — case_profile_service.py's role guard grants that role
// edit access to any case, scoped to the fixed field catalog only
// (see app/models/case_profile.py).
var CASE_API_BASE  = "https://YOUR_CASE_DEVELOPMENT_CLOUD_RUN_URL/api/v1";
var CASE_API_KEY   = "YOUR_CASE_DEVELOPMENT_PARTNER_API_KEY";
var POST_INTAKE_STATUS = "Pending Paralegal Review";

// ── Google Form question titles — must match exactly ─────────────────────────
// Section 1 — About You
var Q_TOKEN       = "Intake Token";
var Q_FIRST_NAME  = "First Name";
var Q_LAST_NAME   = "Last Name";
var Q_EMAIL       = "Email Address";
var Q_PHONE       = "Phone Number";
// Section 2 — WTC Status
var Q_WTC_STATUS  = "WTC Health Program Status";
// Section 3A — WTC Enrolled
var Q_WTC_MEMBER  = "WTC Member ID";
var Q_CONDITIONS  = "Medical Conditions (WTC-related)";
// Section 3B — Not Enrolled
var Q_EXPOSURE    = "Exposure Description";
// Section 4 — VCF History
var Q_PRIOR_CLAIM = "Have you filed a prior VCF claim?";
// Section 5A — Prior Claim
var Q_CLAIM_NUM   = "Prior VCF Claim Number";
var Q_CLAIM_STATUS= "Prior VCF Claim Status";
// Section 6 — Deceased
var Q_DECEASED    = "Is the claimant deceased?";
// Section 8 — Document Uploads
var Q_MED_RECORDS = "Upload Medical Records";
var Q_PROOF_PRES  = "Upload Proof of Presence";
var Q_PHOTO_ID    = "Upload Photo ID";

// Category passed to intake-drive-sync for each upload question
var UPLOAD_CATEGORY_MAP = {};
UPLOAD_CATEGORY_MAP[Q_MED_RECORDS] = "medical_records";
UPLOAD_CATEGORY_MAP[Q_PROOF_PRES]  = "proof_of_presence";
UPLOAD_CATEGORY_MAP[Q_PHOTO_ID]    = "id_documents";


// ════════════════════════════════════════════════════════════════════════════
//  Firestore REST helpers
// ════════════════════════════════════════════════════════════════════════════

/** Returns the Apps Script OAuth token for Firestore API calls. */
function _getToken_() {
  return ScriptApp.getOAuthToken();
}

/** GET a Firestore document. Returns null if 404, throws on other errors. */
function _firestoreGet_(path) {
  var url = FIRESTORE_REST_BASE + "/" + path;
  var response = UrlFetchApp.fetch(url, {
    method: "get",
    headers: { Authorization: "Bearer " + _getToken_() },
    muteHttpExceptions: true,
  });
  var code = response.getResponseCode();
  if (code === 404) return null;
  if (code !== 200) {
    throw new Error("Firestore GET [" + path + "] returned " + code + ": " + response.getContentText().substring(0, 300));
  }
  return JSON.parse(response.getContentText());
}

/**
 * PATCH (merge-update) a Firestore document.
 * @param {string}   path        — e.g. "cases/ZAD-2026-03-0001"
 * @param {Object}   fields      — plain JS object; values are JS primitives / Date
 * @param {string[]} updateMask  — field paths to include in the update mask
 */
function _firestorePatch_(path, fields, updateMask) {
  var body = { fields: _toFsFields_(fields) };
  var maskParam = updateMask && updateMask.length
    ? "?" + updateMask.map(function(f) { return "updateMask.fieldPaths=" + encodeURIComponent(f); }).join("&")
    : "";
  var url = FIRESTORE_REST_BASE + "/" + path + maskParam;
  var response = UrlFetchApp.fetch(url, {
    method: "patch",
    contentType: "application/json",
    headers: { Authorization: "Bearer " + _getToken_() },
    payload: JSON.stringify(body),
    muteHttpExceptions: true,
  });
  var code = response.getResponseCode();
  if (code < 200 || code >= 300) {
    throw new Error("Firestore PATCH [" + path + "] returned " + code + ": " + response.getContentText().substring(0, 300));
  }
  return JSON.parse(response.getContentText());
}

/**
 * Run a Firestore structured query.
 * @param {Object} structuredQuery — Firestore REST StructuredQuery object
 * @returns {Array} array of document objects (may be empty)
 */
function _firestoreQuery_(structuredQuery) {
  var url = FIRESTORE_REST_BASE.replace("/documents", "") + ":runQuery";
  var response = UrlFetchApp.fetch(url, {
    method: "post",
    contentType: "application/json",
    headers: { Authorization: "Bearer " + _getToken_() },
    payload: JSON.stringify({ structuredQuery: structuredQuery }),
    muteHttpExceptions: true,
  });
  var code = response.getResponseCode();
  if (code !== 200) {
    throw new Error("Firestore runQuery returned " + code + ": " + response.getContentText().substring(0, 300));
  }
  var results = JSON.parse(response.getContentText());
  // Each result element may have a "document" key; filter out skipped results
  return results
    .filter(function(r) { return r.document; })
    .map(function(r) { return r.document; });
}

/** Convert a plain JS object to Firestore REST field format. */
function _toFsFields_(obj) {
  var fields = {};
  for (var key in obj) {
    if (!obj.hasOwnProperty(key)) continue;
    var val = obj[key];
    if (val === null || val === undefined) {
      fields[key] = { nullValue: null };
    } else if (typeof val === "boolean") {
      fields[key] = { booleanValue: val };
    } else if (typeof val === "number") {
      fields[key] = Number.isInteger(val)
        ? { integerValue: String(val) }
        : { doubleValue: val };
    } else if (val instanceof Date) {
      fields[key] = { timestampValue: val.toISOString() };
    } else {
      fields[key] = { stringValue: String(val) };
    }
  }
  return fields;
}

/** Safely read a string field from a Firestore REST document. */
function _fsStr_(doc, field) {
  try { return doc.fields[field].stringValue || ""; } catch(e) { return ""; }
}

/** Safely read a boolean field from a Firestore REST document. */
function _fsBool_(doc, field) {
  try { return !!doc.fields[field].booleanValue; } catch(e) { return false; }
}

/** Safely read a timestamp field (returns Date or null). */
function _fsDate_(doc, field) {
  try {
    var ts = doc.fields[field].timestampValue;
    return ts ? new Date(ts) : null;
  } catch(e) { return null; }
}


// ════════════════════════════════════════════════════════════════════════════
//  Case-development API helpers
//
//  Case profile fields and status must go through case-development's API — never
//  written to the cases/{caseId} Firestore document directly from here. That API
//  enforces the field allow-list (firmSettings/case_profile_editable_fields),
//  writes the required audit_logs entry, and keeps status transitions in the
//  approval-chain state machine (a separate endpoint from profile fields — see
//  services/case-development/app/services/case_profile_service.py and
//  status_update_service.py).
// ════════════════════════════════════════════════════════════════════════════

/**
 * PATCH a subset of case-profile fields via case-development's API.
 * @param {string} caseId
 * @param {Object} fields — subset of the FIELD_CATALOG keys in
 *   services/case-development/app/models/case_profile.py (first_name, last_name,
 *   email, phone, address, notes, assigned_attorney, date_of_birth,
 *   exposure_location, exposure_date_start, exposure_date_end, conditions,
 *   prior_attorney). Any other key is rejected by the API.
 * @returns {Object} { ok: boolean, code: number, body: string }
 */
function _caseApiPatchProfile_(caseId, fields) {
  return _caseApiCall_("PATCH", "/cases/" + encodeURIComponent(caseId), fields);
}

/**
 * PATCH a case's status via case-development's dedicated status endpoint
 * (kept separate from profile fields — status is excluded from the profile
 * PATCH on purpose, since it drives the approval-chain state machine).
 * @param {string} caseId
 * @param {string} newStatus
 * @param {string} [notes]
 * @returns {Object} { ok: boolean, code: number, body: string }
 */
function _caseApiPatchStatus_(caseId, newStatus, notes) {
  var body = { status: newStatus };
  if (notes) body.notes = notes;
  return _caseApiCall_("PATCH", "/cases/" + encodeURIComponent(caseId) + "/status", body);
}

/** Shared PATCH caller for the case-development API — X-API-Key auth, same
 * pattern as integrations/lead-intake-google-form/LeadIntakeForm.gs. */
function _caseApiCall_(method, path, body) {
  var response = UrlFetchApp.fetch(CASE_API_BASE + path, {
    method: method,
    contentType: "application/json",
    headers: { "X-API-Key": CASE_API_KEY, "X-Request-ID": Utilities.getUuid() },
    payload: JSON.stringify(body),
    muteHttpExceptions: true,
  });
  var code = response.getResponseCode();
  return { ok: code >= 200 && code < 300, code: code, body: response.getContentText() };
}


// ════════════════════════════════════════════════════════════════════════════
//  Form response helpers
// ════════════════════════════════════════════════════════════════════════════

/** Find an item response by question title and return its string value. */
function _getResponse_(itemResponses, questionTitle) {
  for (var i = 0; i < itemResponses.length; i++) {
    if (itemResponses[i].getItem().getTitle() === questionTitle) {
      var resp = itemResponses[i].getResponse();
      return resp ? String(resp).trim() : "";
    }
  }
  return "";
}

/**
 * Find an item response by question title and return it as an array of trimmed,
 * non-empty strings. Checkbox items already return an array; free-text items are
 * split on commas/semicolons/newlines as a fallback.
 */
function _getResponseArray_(itemResponses, questionTitle) {
  for (var i = 0; i < itemResponses.length; i++) {
    if (itemResponses[i].getItem().getTitle() === questionTitle) {
      var resp = itemResponses[i].getResponse();
      if (!resp) return [];
      if (Array.isArray(resp)) return resp.filter(Boolean);
      return String(resp).split(/[,;\n]+/).map(function(s) { return s.trim(); }).filter(Boolean);
    }
  }
  return [];
}

/**
 * Find a file-upload item by question title and return an array of Drive file IDs.
 * Google Forms file uploads return an array of IDs (or a single ID string).
 */
function _getFileIds_(itemResponses, questionTitle) {
  for (var i = 0; i < itemResponses.length; i++) {
    if (itemResponses[i].getItem().getTitle() === questionTitle) {
      var resp = itemResponses[i].getResponse();
      if (!resp) return [];
      return Array.isArray(resp) ? resp.filter(Boolean) : [resp];
    }
  }
  return [];
}


// ════════════════════════════════════════════════════════════════════════════
//  Email helpers
// ════════════════════════════════════════════════════════════════════════════

function _alertAdmin_(subject, body) {
  try {
    GmailApp.sendEmail(ADMIN_EMAIL, "[SimpleTort Intake] " + subject, body);
  } catch(e) {
    Logger.log("Failed to send admin alert: " + e);
  }
}

function _sendReminderEmail_(toEmail, clientName, previewUrl) {
  var subject = "Reminder: Please complete your SimpleTort intake form";
  var body = [
    "Dear " + (clientName || "Client") + ",",
    "",
    "This is a friendly reminder to complete your client intake form for your",
    "Zadroga Act / 9/11 VCF claim. Please click the link below:",
    "",
    previewUrl,
    "",
    "If you have any questions, please contact our office.",
    "",
    "SimpleTort Legal Services",
  ].join("\n");

  if (SENDGRID_API_KEY) {
    var payload = {
      personalizations: [{ to: [{ email: toEmail }] }],
      from: { email: REMINDER_FROM_EMAIL },
      subject: subject,
      content: [{ type: "text/plain", value: body }],
    };
    UrlFetchApp.fetch("https://api.sendgrid.com/v3/mail/send", {
      method: "post",
      contentType: "application/json",
      headers: { Authorization: "Bearer " + SENDGRID_API_KEY },
      payload: JSON.stringify(payload),
      muteHttpExceptions: true,
    });
  } else {
    GmailApp.sendEmail(toEmail, subject, body);
  }
}


// ════════════════════════════════════════════════════════════════════════════
//  One-time setup: createIntakeForm
//  Run ONCE from the Apps Script editor, from a fresh Google Sheet's bound
//  script project (Extensions > Apps Script), BEFORE running syncFormEntryIds.
//  Builds the form structure documented in google-forms/README.md Step 2,
//  links responses to this Sheet, and installs both triggers.
//
//  PLATFORM LIMITATION — two things Apps Script's FormApp service cannot do,
//  confirmed against the current Apps Script API surface:
//    1. File-upload questions (Sections 7 & 8 — 5 fields total) can only be
//       added through the Forms UI; there is no addFileUploadItem() method.
//    2. Form branding (header image, theme color) is UI-only — neither
//       FormApp nor the Forms REST API expose it.
//  createIntakeForm() builds everything else (all sections, question types,
//  choices, and branching) and logs exactly what's left to add by hand.
// ════════════════════════════════════════════════════════════════════════════

/**
 * Creates the SimpleTort Client Intake Form with every section, question, and
 * branching rule from google-forms/README.md Step 2 that Apps Script can build
 * programmatically. Links form responses to the current Sheet (this function
 * must be run from that Sheet's bound Apps Script project — same one that
 * contains onIntakeFormSubmit) and installs the onIntakeFormSubmit and
 * dailyReminderCheck triggers.
 *
 * SAFE TO RE-RUN: creates a brand-new Form each time (Apps Script cannot edit
 * an existing form's structure from a fresh script run in a meaningful way) —
 * intentionally NOT idempotent. If you re-run this, delete triggers pointing
 * at the old form first (Apps Script editor > Triggers) to avoid duplicates.
 *
 * AFTER RUNNING, YOU STILL NEED TO (see google-forms/README.md Step 2/4):
 *   1. Add the 5 file-upload questions (Section 7: Upload Death Certificate,
 *      Upload Letters of Administration; Section 8: Upload Medical Records,
 *      Upload Proof of Presence, Upload Photo ID) — 10 files max, 10 MB/file.
 *   2. Set branding: header image + theme color #1A3C6B (Settings > gear icon
 *      or the paint-roller icon in the form editor).
 *   3. Run syncFormEntryIds() to sync pre-fill entry IDs to Firestore.
 *
 * @returns {string} the form's edit URL, logged along with the public URL.
 */
function createIntakeForm() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) {
    throw new Error(
      "createIntakeForm() must be run from a Google Sheet's bound Apps Script " +
      "project (Extensions > Apps Script), not a standalone script — the form's " +
      "responses need to land in a real Sheet."
    );
  }

  var form = FormApp.create("SimpleTort Client Intake Form");
  form.setCollectEmail(false);              // email is pre-filled in a field
  form.setLimitOneResponsePerUser(false);   // the intake token enforces single-use
  form.setConfirmationMessage(
    "Thank you. Your intake form has been received. Our team will review your " +
    "submission and be in touch within 2–3 business days."
  );

  // ── Section 1 — About You (page 1, no page break needed) ─────────────────
  form.addSectionHeaderItem().setTitle("About You");
  form.addTextItem().setTitle(Q_FIRST_NAME).setRequired(true);
  form.addTextItem().setTitle(Q_LAST_NAME).setRequired(true);
  form.addTextItem().setTitle(Q_EMAIL).setRequired(true);
  form.addTextItem().setTitle(Q_PHONE).setRequired(true);
  form.addTextItem()
    .setTitle(Q_TOKEN)
    .setHelpText("Do not edit this field")
    .setRequired(true);

  // ── Section 2 — WTC Health Program Status ─────────────────────────────────
  form.addPageBreakItem().setTitle("WTC Health Program Status");
  var wtcStatusItem = form.addMultipleChoiceItem().setTitle(Q_WTC_STATUS).setRequired(true);

  // ── Section 3A — WTC Member Details (if enrolled) ─────────────────────────
  var pb3a = form.addPageBreakItem().setTitle("WTC Member Details");
  form.addTextItem().setTitle(Q_WTC_MEMBER).setRequired(false);
  form.addParagraphTextItem().setTitle(Q_CONDITIONS).setRequired(false);

  // ── Section 3B — Exposure Description (if not enrolled) ──────────────────
  var pb3b = form.addPageBreakItem().setTitle("Exposure Description");
  form.addParagraphTextItem().setTitle(Q_EXPOSURE).setRequired(true);

  // ── Section 4 — VCF Claim History ─────────────────────────────────────────
  var pb4 = form.addPageBreakItem().setTitle("VCF Claim History");
  var priorClaimItem = form.addMultipleChoiceItem().setTitle(Q_PRIOR_CLAIM).setRequired(true);

  // ── Section 5A — Prior Claim Details (if yes) ─────────────────────────────
  var pb5a = form.addPageBreakItem().setTitle("Prior Claim Details");
  form.addTextItem().setTitle(Q_CLAIM_NUM).setRequired(false);
  var claimStatusItem = form.addMultipleChoiceItem().setTitle(Q_CLAIM_STATUS).setRequired(false);
  claimStatusItem.setChoices([
    claimStatusItem.createChoice("Pending"),
    claimStatusItem.createChoice("Approved"),
    claimStatusItem.createChoice("Denied"),
    claimStatusItem.createChoice("On Appeal"),
  ]);

  // ── Section 5B — placeholder (if no prior claim) ──────────────────────────
  var pb5b = form.addPageBreakItem();

  // ── Section 6 — Deceased Claimant ─────────────────────────────────────────
  var pb6 = form.addPageBreakItem().setTitle("Deceased Claimant");
  var deceasedItem = form.addMultipleChoiceItem().setTitle(Q_DECEASED).setRequired(true);

  // ── Section 7 — Estate Documents (if deceased) — file uploads added manually
  var pb7 = form.addPageBreakItem().setTitle("Estate Documents");

  // ── Section 8 — Document Uploads — file uploads added manually ───────────
  var pb8 = form.addPageBreakItem().setTitle("Document Uploads");

  // ── Branching (all wired last, once every page-break reference exists) ───
  wtcStatusItem.setChoices([
    wtcStatusItem.createChoice("Enrolled", pb3a),
    wtcStatusItem.createChoice("Applied", pb3b),
    wtcStatusItem.createChoice("Not Applied", pb3b),
    wtcStatusItem.createChoice("Unknown", pb3b),
  ]);
  pb3a.setGoToPage(pb4);
  pb3b.setGoToPage(pb4);

  priorClaimItem.setChoices([
    priorClaimItem.createChoice("Yes", pb5a),
    priorClaimItem.createChoice("No", pb5b),
  ]);
  pb5a.setGoToPage(pb6);
  pb5b.setGoToPage(pb6);

  deceasedItem.setChoices([
    deceasedItem.createChoice("Yes", pb7),
    deceasedItem.createChoice("No", pb8),
  ]);
  pb7.setGoToPage(pb8);
  // pb8 is the last page — falls through to submit by default.

  // ── Link responses to this Sheet, install both triggers ──────────────────
  form.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());
  installTriggers_(form);

  var editUrl = form.getEditUrl();
  var publicUrl = form.getPublishedUrl();
  Logger.log("createIntakeForm complete.");
  Logger.log("  Edit URL   : " + editUrl);
  Logger.log("  Public URL : " + publicUrl);
  Logger.log("REMAINING MANUAL STEPS (see google-forms/README.md):");
  Logger.log("  1. Add 5 file-upload questions to 'Estate Documents' and 'Document Uploads' sections.");
  Logger.log("  2. Set header image + theme color #1A3C6B.");
  Logger.log("  3. Run syncFormEntryIds() once the above is done.");
  return editUrl;
}

/** Installs the onIntakeFormSubmit (form submit) and dailyReminderCheck
 * (daily 6–7am) triggers, removing any pre-existing ones first to avoid
 * duplicates on re-run. */
function installTriggers_(form) {
  ScriptApp.getProjectTriggers().forEach(function(t) {
    var fn = t.getHandlerFunction();
    if (fn === "onIntakeFormSubmit" || fn === "dailyReminderCheck") {
      ScriptApp.deleteTrigger(t);
    }
  });

  ScriptApp.newTrigger("onIntakeFormSubmit").forForm(form).onFormSubmit().create();
  ScriptApp.newTrigger("dailyReminderCheck").timeBased().everyDays(1).atHour(6).create();

  Logger.log("Triggers installed: onIntakeFormSubmit (on form submit), dailyReminderCheck (daily 6–7am).");
}


// ════════════════════════════════════════════════════════════════════════════
//  One-time setup: syncFormEntryIds
//  Run ONCE from the Apps Script editor after creating or recreating the form.
//  Reads item IDs directly from the linked Google Form (no URL copy-pasting)
//  and writes the complete config/intake_form document to Firestore.
// ════════════════════════════════════════════════════════════════════════════

/**
 * Reads the pre-fill entry IDs for the 5 pre-filled fields directly from the
 * linked Google Form and writes them to Firestore at config/intake_form.
 *
 * HOW TO RUN:
 *   1. Open the Apps Script editor (Extensions > Apps Script from the linked Sheet)
 *   2. Select "syncFormEntryIds" from the function dropdown
 *   3. Click ▶ Run
 *   4. Approve the OAuth prompt on first run (forms.body.readonly scope)
 *   5. Check the Execution Log — all 5 entry IDs will be listed
 *
 * SAFE TO RE-RUN: replaces the full Firestore document, so running again after
 * recreating the form will pick up new entry IDs automatically.
 *
 * Requires the forms.body.readonly OAuth scope in appsscript.json.
 */
function syncFormEntryIds() {
  // ── 1. Get the linked form ─────────────────────────────────────────────
  var ss      = SpreadsheetApp.getActiveSpreadsheet();
  var formUrl = ss.getFormUrl();
  if (!formUrl) {
    throw new Error(
      "This spreadsheet has no linked form. " +
      "Link the form first: Form editor > Responses tab > spreadsheet icon."
    );
  }
  var form = FormApp.openByUrl(formUrl);

  // ── 2. Map question titles → Firestore fieldMapping keys ───────────────
  // Uses the same title constants declared at the top of this file so any
  // future rename only needs to be changed in one place.
  var TITLE_TO_KEY = {};
  TITLE_TO_KEY[Q_FIRST_NAME] = "firstName";
  TITLE_TO_KEY[Q_LAST_NAME]  = "lastName";
  TITLE_TO_KEY[Q_EMAIL]      = "email";
  TITLE_TO_KEY[Q_PHONE]      = "phone";
  TITLE_TO_KEY[Q_TOKEN]      = "intakeToken";

  // Unique placeholder per field so we can identify which entry.XXXXXXXXX
  // maps to which field after parsing the pre-fill URL.
  var TITLE_TO_MARKER = {};
  TITLE_TO_MARKER[Q_FIRST_NAME] = "__MARKER_FIRST_NAME__";
  TITLE_TO_MARKER[Q_LAST_NAME]  = "__MARKER_LAST_NAME__";
  TITLE_TO_MARKER[Q_EMAIL]      = "__MARKER_EMAIL__";
  TITLE_TO_MARKER[Q_PHONE]      = "__MARKER_PHONE__";
  TITLE_TO_MARKER[Q_TOKEN]      = "__MARKER_INTAKE_TOKEN__";

  // ── 3. Derive entry IDs via toPrefilledUrl() ───────────────────────────
  // item.getId()            → Apps Script internal item ID  ❌ (wrong number)
  // Forms REST API v1       → requires enabling forms.googleapis.com in GCP ❌
  // toPrefilledUrl()        → built-in FormApp method, generates a real
  //                           Google Forms pre-fill URL with correct entry IDs ✅
  var formResp = form.createResponse();
  var items    = form.getItems();
  for (var i = 0; i < items.length; i++) {
    var item  = items[i];
    var title = item.getTitle();
    if (TITLE_TO_MARKER.hasOwnProperty(title) && item.getType() === FormApp.ItemType.TEXT) {
      formResp.withItemResponse(item.asTextItem().createResponse(TITLE_TO_MARKER[title]));
    }
  }

  var prefillUrl    = formResp.toPrefilledUrl();
  var fieldMappings = {};
  for (var t in TITLE_TO_MARKER) {
    if (!TITLE_TO_MARKER.hasOwnProperty(t)) continue;
    var marker = TITLE_TO_MARKER[t];
    var re     = new RegExp("[?&](entry\\.\\d+)=" + marker);
    var match  = prefillUrl.match(re);
    if (match) fieldMappings[TITLE_TO_KEY[t]] = match[1];  // e.g. "entry.318541363"
  }

  // ── 4. Guard: all 5 fields must be found before writing ───────────────
  var missing = [];
  for (var expectedTitle in TITLE_TO_KEY) {
    if (TITLE_TO_KEY.hasOwnProperty(expectedTitle)) {
      var key = TITLE_TO_KEY[expectedTitle];
      if (!fieldMappings[key]) {
        missing.push('"' + expectedTitle + '"');
      }
    }
  }
  if (missing.length > 0) {
    throw new Error(
      "Could not find form questions: " + missing.join(", ") + ". " +
      "Check that the question titles match exactly (case-sensitive)."
    );
  }

  // ── 5. Write to Firestore config/intake_form ───────────────────────────
  // _toFsFields_ does not support nested maps (it would stringify the object).
  // Build the Firestore REST document body manually using mapValue encoding.
  var mappingFields = {};
  for (var fkey in fieldMappings) {
    if (fieldMappings.hasOwnProperty(fkey)) {
      mappingFields[fkey] = { stringValue: fieldMappings[fkey] };
    }
  }

  var docBody = {
    fields: {
      formBaseUrl:   { stringValue: form.getPublishedUrl() },
      fieldMappings: { mapValue: { fields: mappingFields } },
      updatedAt:     { timestampValue: new Date().toISOString() },
      updatedBy:     { stringValue: Session.getActiveUser().getEmail() }
    }
  };

  // PATCH with no updateMask = replace the full document
  var url = FIRESTORE_REST_BASE + "/config/intake_form";
  var response = UrlFetchApp.fetch(url, {
    method: "patch",
    contentType: "application/json",
    headers: { Authorization: "Bearer " + _getToken_() },
    payload: JSON.stringify(docBody),
    muteHttpExceptions: true
  });

  var code = response.getResponseCode();
  if (code < 200 || code >= 300) {
    throw new Error(
      "Firestore write failed (HTTP " + code + "): " +
      response.getContentText().substring(0, 300)
    );
  }

  // ── 6. Log results for verification ───────────────────────────────────
  Logger.log("syncFormEntryIds complete — config/intake_form updated.");
  Logger.log("  formBaseUrl : " + form.getPublishedUrl());
  for (var lkey in fieldMappings) {
    if (fieldMappings.hasOwnProperty(lkey)) {
      Logger.log("  " + lkey + " : " + fieldMappings[lkey]);
    }
  }
  Logger.log("intake-form-dispatcher will use these IDs on next cold start.");
}


// ════════════════════════════════════════════════════════════════════════════
//  Main trigger: onIntakeFormSubmit
//  Install via: Triggers > Add trigger > onIntakeFormSubmit > From form > On form submit
// ════════════════════════════════════════════════════════════════════════════

function onIntakeFormSubmit(e) {
  var formResponse = e.response;
  var submissionId = formResponse.getId();
  var itemResponses = formResponse.getItemResponses();

  Logger.log("onIntakeFormSubmit: submissionId=" + submissionId);

  // ── 1. Read token ──────────────────────────────────────────────────────
  var tokenId = _getResponse_(itemResponses, Q_TOKEN);
  if (!tokenId) {
    var msg = "No token in submission " + submissionId;
    Logger.log(msg);
    _alertAdmin_("Intake Submission Missing Token", msg);
    return;
  }

  // ── 2. Validate token in Firestore ─────────────────────────────────────
  var tokenDoc;
  try {
    tokenDoc = _firestoreGet_("intake_tokens/" + tokenId);
  } catch(err) {
    Logger.log("Token fetch error: " + err);
    _alertAdmin_("Token Fetch Error", "tokenId=" + tokenId + "\n" + err);
    return;
  }

  if (!tokenDoc) {
    _alertAdmin_("Invalid Token", "tokenId=" + tokenId + " not found (submissionId=" + submissionId + ")");
    return;
  }

  var tokenUsed  = _fsBool_(tokenDoc, "used");
  var expiresAt  = _fsDate_(tokenDoc, "expiresAt");
  var caseId     = _fsStr_(tokenDoc, "caseId");

  if (tokenUsed) {
    _alertAdmin_("Duplicate Submission",
      "Token already used: " + tokenId + "\ncaseId=" + caseId + "\nsubmissionId=" + submissionId);
    return;
  }

  if (expiresAt && new Date() > expiresAt) {
    _alertAdmin_("Expired Token",
      "tokenId=" + tokenId + " expired at " + expiresAt.toISOString() + "\ncaseId=" + caseId);
    // Record expiry in audit log
    try {
      _firestorePatch_("intake_tokens/" + tokenId,
        { lastAuditEvent: "expired_on_submit" },
        ["lastAuditEvent"]
      );
    } catch(e) { Logger.log("Could not record expiry: " + e); }
    return;
  }

  // ── 3. Collect form field values ───────────────────────────────────────
  var firstName   = _getResponse_(itemResponses, Q_FIRST_NAME);
  var lastName    = _getResponse_(itemResponses, Q_LAST_NAME);
  var email       = _getResponse_(itemResponses, Q_EMAIL);
  var phone       = _getResponse_(itemResponses, Q_PHONE);
  var wtcStatus   = _getResponse_(itemResponses, Q_WTC_STATUS);
  var wtcMemberId = _getResponse_(itemResponses, Q_WTC_MEMBER);
  var conditions  = _getResponseArray_(itemResponses, Q_CONDITIONS);
  var exposure    = _getResponse_(itemResponses, Q_EXPOSURE);
  var priorClaim  = _getResponse_(itemResponses, Q_PRIOR_CLAIM);
  var claimNum    = _getResponse_(itemResponses, Q_CLAIM_NUM);
  var claimStatus = _getResponse_(itemResponses, Q_CLAIM_STATUS);
  var deceased    = _getResponse_(itemResponses, Q_DECEASED);

  // wtcMemberId, priorClaim/claimNum/claimStatus, deceased, and wtcStatus have no home
  // in case-development's editable-field catalog yet (app/models/case_profile.py —
  // FIELD_CATALOG). Logged here so the gap stays visible instead of silently dropped;
  // they belong on either a future case-profile catalog field or enrollment-workflow's
  // enrollment.* fields, which is a separate decision from wiring up this endpoint.
  var uncapturedFields = [];
  if (wtcStatus)   uncapturedFields.push("wtc_health_program_status");
  if (wtcMemberId) uncapturedFields.push("wtc_member_id");
  if (priorClaim)  uncapturedFields.push("prior_vcf_claim");
  if (claimNum)    uncapturedFields.push("prior_vcf_claim_number");
  if (claimStatus) uncapturedFields.push("prior_vcf_claim_status");
  if (deceased)    uncapturedFields.push("deceased_claimant");
  if (uncapturedFields.length > 0) {
    Logger.log(
      "WARNING: submission " + submissionId + " (caseId=" + caseId + ") collected " +
      "fields with no case-profile catalog field yet, not sent to the API: " +
      uncapturedFields.join(", ")
    );
  }

  // ── 4. Update case via case-development's API — never direct Firestore ─
  // Two calls: profile fields (PATCH /cases/{caseId}) and status
  // (PATCH /cases/{caseId}/status) are deliberately separate endpoints — status
  // drives the approval-chain state machine and is excluded from the profile PATCH.
  var profileFields = {};
  if (firstName)       profileFields.first_name        = firstName;
  if (lastName)        profileFields.last_name         = lastName;
  if (email)            profileFields.email             = email;
  if (phone)            profileFields.phone             = phone;
  if (exposure)         profileFields.exposure_location = exposure;
  if (conditions.length) profileFields.conditions       = conditions;

  if (Object.keys(profileFields).length > 0) {
    var profileResult = _caseApiPatchProfile_(caseId, profileFields);
    if (profileResult.ok) {
      Logger.log("Case profile updated via API: " + caseId + " fields=" + Object.keys(profileFields).join(","));
    } else {
      Logger.log("Case profile API update failed [" + profileResult.code + "]: " + profileResult.body);
      _alertAdmin_("Case Profile Update Failed",
        "caseId=" + caseId + " HTTP " + profileResult.code + "\n" + profileResult.body);
      // Continue — still attempt status update, file sync, and mark token used
    }
  }

  var statusResult = _caseApiPatchStatus_(caseId, POST_INTAKE_STATUS, "Intake form submitted (submissionId=" + submissionId + ").");
  if (statusResult.ok) {
    Logger.log("Case status updated via API: " + caseId + " -> " + POST_INTAKE_STATUS);
  } else {
    Logger.log("Case status API update failed [" + statusResult.code + "]: " + statusResult.body);
    _alertAdmin_("Case Status Update Failed",
      "caseId=" + caseId + " HTTP " + statusResult.code + "\n" + statusResult.body);
    // Continue — still attempt file sync and mark token used
  }

  // ── 5. Collect uploaded Drive file IDs ────────────────────────────────
  var filesToSync = [];
  for (var qTitle in UPLOAD_CATEGORY_MAP) {
    var fileIds = _getFileIds_(itemResponses, qTitle);
    var category = UPLOAD_CATEGORY_MAP[qTitle];
    for (var i = 0; i < fileIds.length; i++) {
      var driveFileId = fileIds[i];
      if (!driveFileId) continue;
      var fileName = "intake_upload_" + driveFileId;
      var mimeType = "application/octet-stream";
      try {
        // Drive Advanced Service must be enabled (Services > Drive API v2)
        var meta = Drive.Files.get(driveFileId, { fields: "title,mimeType" });
        fileName = meta.title || fileName;
        mimeType = meta.mimeType || mimeType;
      } catch(driveErr) {
        Logger.log("Drive metadata failed for " + driveFileId + ": " + driveErr);
      }
      filesToSync.push({
        driveFileId: driveFileId,
        fileName:    fileName,
        mimeType:    mimeType,
        category:    category,
      });
    }
  }

  // ── 6. Call intake-drive-sync Cloud Function ───────────────────────────
  if (filesToSync.length > 0) {
    try {
      var syncResp = UrlFetchApp.fetch(INTAKE_DRIVE_SYNC_URL, {
        method: "post",
        contentType: "application/json",
        headers: { Authorization: "Bearer " + DRIVE_SYNC_SECRET },
        payload: JSON.stringify({ caseId: caseId, tokenId: tokenId, files: filesToSync }),
        muteHttpExceptions: true,
      });
      var syncCode = syncResp.getResponseCode();
      Logger.log("drive-sync: " + syncCode + " " + syncResp.getContentText().substring(0, 300));
      if (syncCode >= 500) {
        _alertAdmin_("Drive Sync Error",
          "caseId=" + caseId + " HTTP " + syncCode + "\n" + syncResp.getContentText().substring(0, 500));
      }
    } catch(syncErr) {
      Logger.log("drive-sync call failed: " + syncErr);
      _alertAdmin_("Drive Sync Failed", "caseId=" + caseId + "\n" + syncErr);
    }
  } else {
    Logger.log("No files to sync for submission " + submissionId);
  }

  // ── 7. Mark token as used ──────────────────────────────────────────────
  try {
    _firestorePatch_(
      "intake_tokens/" + tokenId,
      { used: true, usedAt: new Date(), submissionId: submissionId },
      ["used", "usedAt", "submissionId"]
    );
    Logger.log("Token marked used: " + tokenId);
  } catch(err) {
    Logger.log("Failed to mark token used: " + err);
    _alertAdmin_("Token Update Failed", "tokenId=" + tokenId + "\n" + err);
  }

  Logger.log("onIntakeFormSubmit complete: caseId=" + caseId + " submissionId=" + submissionId);
}


// ════════════════════════════════════════════════════════════════════════════
//  Daily reminder trigger
//  Install via: Triggers > Add trigger > dailyReminderCheck > Time-driven > Day timer > 6–7am
// ════════════════════════════════════════════════════════════════════════════

function dailyReminderCheck() {
  var now = new Date();
  var sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);

  Logger.log("dailyReminderCheck: running at " + now.toISOString());

  // Query intake_tokens: used=false AND reminderSentAt=null AND createdAt < 7 days ago
  var docs;
  try {
    docs = _firestoreQuery_({
      from: [{ collectionId: "intake_tokens" }],
      where: {
        compositeFilter: {
          op: "AND",
          filters: [
            {
              fieldFilter: {
                field: { fieldPath: "used" },
                op: "EQUAL",
                value: { booleanValue: false },
              },
            },
            {
              fieldFilter: {
                field: { fieldPath: "reminderSentAt" },
                op: "EQUAL",
                value: { nullValue: null },
              },
            },
            {
              fieldFilter: {
                field: { fieldPath: "createdAt" },
                op: "LESS_THAN",
                value: { timestampValue: sevenDaysAgo.toISOString() },
              },
            },
          ],
        },
      },
      limit: 100,
    });
  } catch(err) {
    Logger.log("dailyReminderCheck query failed: " + err);
    _alertAdmin_("Reminder Query Failed", String(err));
    return;
  }

  Logger.log("dailyReminderCheck: found " + docs.length + " token(s) due for reminder");

  for (var i = 0; i < docs.length; i++) {
    var doc = docs[i];
    // Extract token ID from the document name path
    var docName = doc.name || "";
    var tokenId = docName.split("/").pop();
    var clientEmail = _fsStr_(doc, "clientEmail");
    var clientName  = _fsStr_(doc, "clientName");
    var previewUrl  = _fsStr_(doc, "previewUrl");
    var caseId      = _fsStr_(doc, "caseId");

    if (!clientEmail || !previewUrl) {
      Logger.log("Skipping token " + tokenId + " — missing email or URL");
      continue;
    }

    try {
      _sendReminderEmail_(clientEmail, clientName, previewUrl);
      _firestorePatch_(
        "intake_tokens/" + tokenId,
        { reminderSentAt: new Date() },
        ["reminderSentAt"]
      );
      Logger.log("Reminder sent: tokenId=" + tokenId + " caseId=" + caseId + " email=" + clientEmail);
    } catch(err) {
      Logger.log("Reminder failed for tokenId=" + tokenId + ": " + err);
      _alertAdmin_("Reminder Failed",
        "tokenId=" + tokenId + "\ncaseId=" + caseId + "\n" + err);
    }
  }

  Logger.log("dailyReminderCheck complete");
}
