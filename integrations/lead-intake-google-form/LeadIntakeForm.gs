// ============================================================
// SimpleTort — Lead Intake Google Form + Apps Script
// ============================================================
//
// SETUP (one-time):
//   1. Go to script.google.com → New project
//   2. Paste this entire file, replacing the default code
//   3. Project Settings → Script Properties → Add properties:
//        LEAD_API_URL  =  https://<your-lead-intake-cloud-run-url>/api/v1/leads
//        LEAD_API_KEY  =  <partner api key>
//   4. Run createLeadForm() once — it creates the form and installs the trigger
//   5. Share the published form URL with intake staff
//
// FIELDS:
//   Required:  firstName, lastName, email, phone, exposureLocation,
//              exposureDates.start/end, wtcHealthProgramStatus,
//              priorAttorney, marketingSource
//   Optional:  dateOfBirth, address, conditions, referralCode
// ============================================================

var PROP_API_URL = 'LEAD_API_URL';
var PROP_API_KEY = 'LEAD_API_KEY';


// ── 1. Form creation ─────────────────────────────────────────────────────────
// Run this function ONCE from the Apps Script editor (Run → createLeadForm).
// It creates the Google Form and installs the onFormSubmit trigger.

function createLeadForm() {
  var form = FormApp.create('SimpleTort — New Lead Intake');
  form.setDescription(
    'Submit a new Zadroga / 9-11 VCF lead. ' +
    'Fields marked with * are required. ' +
    'All submissions go directly into the SimpleTort case management system.'
  );
  form.setCollectEmail(false);
  form.setLimitOneResponsePerUser(false);
  form.setShowLinkToRespondAgain(true);

  // ── Personal Information ──────────────────────────────────────────────────
  form.addSectionHeaderItem().setTitle('Personal Information');

  form.addTextItem()
    .setTitle('First Name *')
    .setRequired(true);

  form.addTextItem()
    .setTitle('Last Name *')
    .setRequired(true);

  form.addTextItem()
    .setTitle('Email Address *')
    .setHelpText('e.g. john.doe@email.com')
    .setRequired(true);

  form.addTextItem()
    .setTitle('Phone Number *')
    .setHelpText('US number in any format — e.g. (212) 555-1234 or 2125551234')
    .setRequired(true);

  form.addDateItem()
    .setTitle('Date of Birth')
    .setRequired(false);

  // ── Address ───────────────────────────────────────────────────────────────
  form.addSectionHeaderItem().setTitle('Address (Optional)');

  form.addTextItem()
    .setTitle('Street Address')
    .setHelpText('e.g. 123 Main St');

  form.addTextItem()
    .setTitle('City');

  form.addTextItem()
    .setTitle('State')
    .setHelpText('Two-letter abbreviation, e.g. NY');

  form.addTextItem()
    .setTitle('ZIP Code')
    .setHelpText('5-digit ZIP, e.g. 10001');

  // ── 9/11 Exposure Details ─────────────────────────────────────────────────
  form.addSectionHeaderItem().setTitle('9/11 Exposure Details');

  form.addTextItem()
    .setTitle('Exposure Location *')
    .setHelpText('e.g. World Trade Center site, Pentagon, Fresh Kills Landfill, Shanksville PA')
    .setRequired(true);

  form.addDateItem()
    .setTitle('Exposure Start Date *')
    .setRequired(true);

  form.addDateItem()
    .setTitle('Exposure End Date *')
    .setRequired(true);

  // ── Medical & Eligibility ─────────────────────────────────────────────────
  form.addSectionHeaderItem().setTitle('Medical & Eligibility');

  form.addMultipleChoiceItem()
    .setTitle('WTC Health Program Status *')
    .setChoiceValues(['enrolled', 'applied', 'not_applied', 'unknown'])
    .setRequired(true);

  form.addMultipleChoiceItem()
    .setTitle('Prior Attorney? *')
    .setHelpText('Has the client previously retained an attorney for a 9-11 claim?')
    .setChoiceValues(['Yes', 'No'])
    .setRequired(true);

  form.addCheckboxItem()
    .setTitle('Medical Conditions (select all that apply)')
    .setHelpText('Check all VCF-covered conditions the client has been diagnosed with')
    .setChoiceValues([
      'aerodigestive',
      'cancer',
      'mental health',
      'musculoskeletal',
      'sleep disorder',
      'respiratory',
      'gastrointestinal',
      'neurological',
    ]);

  // ── Lead Source ───────────────────────────────────────────────────────────
  form.addSectionHeaderItem().setTitle('Lead Source');

  form.addTextItem()
    .setTitle('Marketing Source *')
    .setHelpText('e.g. google-ads, facebook, tv-ad, referral, walk-in, event')
    .setRequired(true);

  form.addTextItem()
    .setTitle('Referral Code')
    .setHelpText('Optional partner or affiliate referral code');

  // ── Install trigger & report URL ──────────────────────────────────────────
  installTrigger_(form);

  var url = form.getPublishedUrl();
  Logger.log('Form created: ' + form.getEditUrl());
  Logger.log('Public URL:   ' + url);
  return url;
}


// ── 2. Trigger installer ──────────────────────────────────────────────────────

function installTrigger_(form) {
  // Remove any existing onFormSubmit triggers to prevent duplicates
  ScriptApp.getProjectTriggers()
    .filter(function(t) { return t.getHandlerFunction() === 'onFormSubmit'; })
    .forEach(function(t) { ScriptApp.deleteTrigger(t); });

  ScriptApp.newTrigger('onFormSubmit')
    .forForm(form)
    .onFormSubmit()
    .create();

  Logger.log('onFormSubmit trigger installed.');
}


// ── 3. Form submit handler ────────────────────────────────────────────────────
// Automatically called by Google when a form response is submitted.

function onFormSubmit(e) {
  var props  = PropertiesService.getScriptProperties();
  var apiUrl = props.getProperty(PROP_API_URL);
  var apiKey = props.getProperty(PROP_API_KEY);

  if (!apiUrl || !apiKey) {
    Logger.log('ERROR: LEAD_API_URL or LEAD_API_KEY not set in Script Properties.');
    return;
  }

  // Map every item response by question title
  var answers = {};
  (e.response.getItemResponses() || []).forEach(function(r) {
    answers[r.getItem().getTitle()] = r.getResponse();
  });

  var payload = buildPayload_(answers);
  if (!payload) return; // validation failure already logged

  var options = {
    method: 'post',
    contentType: 'application/json',
    headers: {
      'X-API-Key':    apiKey,
      'X-Request-ID': Utilities.getUuid(),
    },
    payload:          JSON.stringify(payload),
    muteHttpExceptions: true,
  };

  try {
    var response = UrlFetchApp.fetch(apiUrl, options);
    var code     = response.getResponseCode();
    var body     = response.getContentText();

    if (code === 201) {
      var result = JSON.parse(body);
      Logger.log(
        'Lead created: ' + result.leadId +
        ' | VCF: ' + result.vcfScreeningStatus +
        ' | Status: ' + result.status
      );
    } else if (code === 409) {
      Logger.log('Duplicate lead rejected (409): ' + body);
    } else {
      Logger.log('Lead intake failed [' + code + ']: ' + body);
    }
  } catch (err) {
    Logger.log('Network error submitting lead: ' + err.message);
  }
}


// ── 4. Payload builder ────────────────────────────────────────────────────────

function buildPayload_(answers) {
  var firstName        = (answers['First Name *']        || '').trim();
  var lastName         = (answers['Last Name *']         || '').trim();
  var email            = (answers['Email Address *']     || '').trim().toLowerCase();
  var phoneRaw         = answers['Phone Number *']        || '';
  var dobRaw           = answers['Date of Birth'];
  var street           = (answers['Street Address']      || '').trim();
  var city             = (answers['City']                || '').trim();
  var stateRaw         = (answers['State']               || '').trim().toUpperCase();
  var zip              = (answers['ZIP Code']            || '').trim();
  var exposureLocation = (answers['Exposure Location *'] || '').trim();
  var expStartRaw      = answers['Exposure Start Date *'];
  var expEndRaw        = answers['Exposure End Date *'];
  var wtcStatus        = answers['WTC Health Program Status *'] || '';
  var priorAttyRaw     = answers['Prior Attorney? *']           || '';
  var conditionsRaw    = answers['Medical Conditions (select all that apply)'] || [];
  var marketingSource  = (answers['Marketing Source *']  || '').trim();
  var referralCode     = (answers['Referral Code']       || '').trim();

  if (!firstName || !lastName || !email || !exposureLocation || !marketingSource) {
    Logger.log('Missing required fields in form response — submission skipped.');
    return null;
  }

  var phone = normalisePhone_(phoneRaw);
  if (!phone) {
    Logger.log('Invalid US phone number: ' + phoneRaw + ' — submission skipped.');
    return null;
  }

  var expStart = formatDate_(expStartRaw);
  var expEnd   = formatDate_(expEndRaw);
  if (!expStart || !expEnd) {
    Logger.log('Invalid exposure dates — submission skipped.');
    return null;
  }

  var payload = {
    firstName:       firstName,
    lastName:        lastName,
    email:           email,
    phone:           phone,
    exposureLocation: exposureLocation,
    exposureDates:   { start: expStart, end: expEnd },
    wtcHealthProgramStatus: wtcStatus,
    priorAttorney:   priorAttyRaw === 'Yes',
    conditions:      Array.isArray(conditionsRaw)
                       ? conditionsRaw
                       : conditionsRaw ? [conditionsRaw] : [],
    marketingSource: marketingSource,
  };

  // Optional: date of birth
  if (dobRaw) {
    var dob = formatDate_(dobRaw);
    if (dob) payload.dateOfBirth = dob;
  }

  // Optional: address (only include if at least one field is present)
  var hasAddress = street || city || stateRaw || zip;
  if (hasAddress) {
    var address = {};
    if (street)                                    address.street = street;
    if (city)                                      address.city   = city;
    if (/^[A-Z]{2}$/.test(stateRaw))              address.state  = stateRaw;
    if (/^\d{5}(-\d{4})?$/.test(zip))             address.zip    = zip;
    if (Object.keys(address).length) payload.address = address;
  }

  // Optional: referral code
  if (referralCode) payload.referralCode = referralCode;

  return payload;
}


// ── 5. Helpers ────────────────────────────────────────────────────────────────

// Normalises a US phone number to E.164 (+1XXXXXXXXXX).
// Accepts formats: (212) 555-1234 / 212-555-1234 / 2125551234 / +12125551234
// Returns null if the number cannot be parsed as a 10-digit US number.
function normalisePhone_(raw) {
  if (!raw) return null;
  var digits = raw.replace(/\D/g, '');
  if (digits.length === 10) return '+1' + digits;
  if (digits.length === 11 && digits[0] === '1') return '+' + digits;
  return null;
}

// Formats a Google Forms date response (JS Date object) or YYYY-MM-DD string
// into the YYYY-MM-DD string required by the API.
function formatDate_(val) {
  if (!val) return null;
  if (val instanceof Date) {
    var y = val.getFullYear();
    var m = String(val.getMonth() + 1).padStart(2, '0');
    var d = String(val.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + d;
  }
  if (typeof val === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(val)) return val;
  return null;
}
