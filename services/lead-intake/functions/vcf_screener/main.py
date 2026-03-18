"""
functions/vcf_screener/main.py — Cloud Function 2nd Gen
Triggered by Pub/Sub 'lead-created' topic.

VCF (Victim Compensation Fund) Eligibility Rule Engine
-------------------------------------------------------
Rules:
  R01 — Exposure site verification (hard fail if not a recognised 9/11 site)
  R02 — Exposure date overlap with VCF window 2001-09-11 to 2011-05-30 (hard fail)
  R03 — WTC Health Program enrollment (soft flag if not enrolled)
  R04 — Prior attorney (soft flag)
  R05 — Minimum data completeness (hard fail if missing required fields)
  R06 — Medical conditions match VCF-covered categories (soft flag if no match)

Scoring:
  - ELIGIBLE: all hard rules pass, no soft flags → score 95
  - NEEDS_REVIEW: all hard rules pass, soft flags present → score 60
  - INELIGIBLE: any hard rule fails → score 0

Processing target: < 5 seconds
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from datetime import date

import functions_framework
from google.cloud import firestore
from google.cloud import pubsub_v1
from cloudevents.http import CloudEvent


# ── Configuration ──────────────────────────────────────────────────────────────

GCP_PROJECT = os.environ["GCP_PROJECT_ID"]
CASES_COLLECTION = os.environ.get("FIRESTORE_CASES_COLLECTION", "cases")
LEAD_SCREENED_TOPIC = os.environ.get("PUBSUB_LEAD_SCREENED_TOPIC", "lead-screened")

VCF_WINDOW_START = date(2001, 9, 11)
VCF_WINDOW_END = date(2011, 5, 30)

VCF_ELIGIBLE_SITES = {
    "world trade center", "wtc", "ground zero",
    "pentagon", "shanksville", "lower manhattan",
    "brooklyn", "queens", "bronx", "new jersey",
    "fresh kills", "staten island",
}

# WTC Health Program certified condition categories
# Full reference: WTCHP Covered Conditions List (42 U.S.C. § 300mm-22)
WTC_CERTIFIED_CONDITIONS = {
    # Aerodigestive disorders
    "aerodigestive", "rhinosinusitis", "nasopharyngitis", "laryngitis",
    "pharyngitis", "upper airway", "sleep apnea", "interstitial lung",
    "asthma", "reactive airways", "wld", "reactive upper airways",
    # Cancer categories (45 cancers covered)
    "cancer", "mesothelioma", "lymphoma", "leukemia", "myeloma",
    "thyroid", "prostate", "breast", "bladder", "colon", "rectal",
    "esophageal", "skin cancer", "melanoma",
    # Mental health
    "mental health", "ptsd", "depression", "anxiety", "adjustment disorder",
    # Musculoskeletal
    "musculoskeletal", "carpal tunnel", "tendinitis",
    # Gastroesophageal
    "gastrointestinal", "gerd", "gastroesophageal",
    # Sleep disorders
    "sleep disorder", "insomnia",
    # Neurological
    "neurological", "peripheral neuropathy",
    # Respiratory
    "respiratory", "copd", "chronic bronchitis", "emphysema",
}


# ── Rule engine ───────────────────────────────────────────────────────────────

@dataclass
class RuleResult:
    rule_id: str
    passed: bool
    severity: str  # "hard_fail" | "soft_flag" | "pass"
    code: str
    reason: str


@dataclass
class ScreeningResult:
    case_id: str
    eligibility: str  # "eligible" | "ineligible" | "needs_review"
    rule_results: list[RuleResult] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    score: int = 0

    def to_dict(self) -> dict:
        return {
            "eligibility": self.eligibility,
            "score": self.score,
            "flags": self.flags,
            "ruleResults": [
                {
                    "ruleId": r.rule_id,
                    "passed": r.passed,
                    "severity": r.severity,
                    "code": r.code,
                    "reason": r.reason,
                }
                for r in self.rule_results
            ],
        }


def rule_minimum_data_completeness(case_data: dict) -> RuleResult:
    """R05: Required fields must be present."""
    required = ["firstName", "lastName", "email", "phone", "exposureLocation"]
    missing = [f for f in required if not case_data.get(f)]
    return RuleResult(
        rule_id="R05_DATA_COMPLETENESS",
        passed=len(missing) == 0,
        severity="hard_fail" if missing else "pass",
        code="INCOMPLETE" if missing else "COMPLETE",
        reason=f"Missing required fields: {missing}" if missing else "All required fields present",
    )


def rule_exposure_site(case_data: dict) -> RuleResult:
    """R01: Exposure location must be a recognised VCF site."""
    location = (case_data.get("exposureLocation") or "").lower().strip()

    # Guard: empty string is a substring of every string in Python ("" in "wtc" → True)
    # so we must reject missing/empty location before the membership test.
    if not location:
        return RuleResult(
            rule_id="R01_EXPOSURE_SITE",
            passed=False,
            severity="hard_fail",
            code="INELIGIBLE_SITE",
            reason="Exposure location is missing or empty",
        )

    is_eligible = any(site in location or location in site for site in VCF_ELIGIBLE_SITES)
    return RuleResult(
        rule_id="R01_EXPOSURE_SITE",
        passed=is_eligible,
        severity="hard_fail" if not is_eligible else "pass",
        code="ELIGIBLE_SITE" if is_eligible else "INELIGIBLE_SITE",
        reason=(
            "Exposure location matches a recognised VCF-eligible site"
            if is_eligible
            else "Exposure location does not match known VCF sites"
        ),
    )


def rule_exposure_date_overlap(case_data: dict) -> RuleResult:
    """R02: Exposure dates must overlap VCF eligibility window 2001-09-11 – 2011-05-30."""
    try:
        start = date.fromisoformat(str(case_data["exposureDateStart"]))
        end = date.fromisoformat(str(case_data["exposureDateEnd"]))
    except (KeyError, ValueError, TypeError):
        return RuleResult(
            rule_id="R02_EXPOSURE_DATES",
            passed=False,
            severity="hard_fail",
            code="MISSING_DATES",
            reason="Exposure dates are missing or invalid",
        )

    # Boundary: exactly on VCF_WINDOW_START or VCF_WINDOW_END still qualifies
    overlaps = start <= VCF_WINDOW_END and end >= VCF_WINDOW_START
    return RuleResult(
        rule_id="R02_EXPOSURE_DATES",
        passed=overlaps,
        severity="hard_fail" if not overlaps else "pass",
        code="DATES_OVERLAP" if overlaps else "DATES_OUTSIDE_WINDOW",
        reason=(
            f"Exposure {start}–{end} overlaps VCF window {VCF_WINDOW_START}–{VCF_WINDOW_END}"
            if overlaps
            else f"Exposure dates {start}–{end} are entirely outside the VCF window"
        ),
    )


def rule_wtc_health_program(case_data: dict) -> RuleResult:
    """R03: WTC Health Program enrollment (non-blocking, soft flag if not enrolled)."""
    status = case_data.get("wtcHealthProgramStatus", "unknown")
    enrolled = status in ("enrolled", "applied")
    return RuleResult(
        rule_id="R03_WTC_HEALTH_PROGRAM",
        passed=True,
        severity="soft_flag" if not enrolled else "pass",
        code="WTC_ENROLLED" if enrolled else "WTC_NOT_ENROLLED",
        reason=f"WTC Health Program status: {status}",
    )


def rule_prior_attorney(case_data: dict) -> RuleResult:
    """R04: Prior attorney flag (non-blocking, soft flag)."""
    has_prior = bool(case_data.get("priorAttorney", False))
    return RuleResult(
        rule_id="R04_PRIOR_ATTORNEY",
        passed=True,
        severity="soft_flag" if has_prior else "pass",
        code="PRIOR_ATTORNEY_FLAG" if has_prior else "NO_PRIOR_ATTORNEY",
        reason=(
            "Claimant indicated prior legal representation — manual review required"
            if has_prior
            else "No prior attorney indicated"
        ),
    )


def rule_conditions_match(case_data: dict) -> RuleResult:
    """R06: Medical conditions match VCF-covered categories (soft flag if no match)."""
    conditions: list = case_data.get("conditions", [])
    if not conditions:
        return RuleResult(
            rule_id="R06_CONDITIONS",
            passed=True,
            severity="soft_flag",
            code="NO_CONDITIONS_PROVIDED",
            reason="No medical conditions provided — condition verification required at intake",
        )

    normalised = [str(c).lower().strip() for c in conditions]
    matched = []
    for cond in normalised:
        for covered in WTC_CERTIFIED_CONDITIONS:
            if covered in cond or cond in covered:
                matched.append(cond)
                break

    if matched:
        return RuleResult(
            rule_id="R06_CONDITIONS",
            passed=True,
            severity="pass",
            code="CONDITIONS_MATCHED",
            reason=f"Conditions matching VCF coverage: {matched}",
        )
    else:
        return RuleResult(
            rule_id="R06_CONDITIONS",
            passed=True,
            severity="soft_flag",
            code="CONDITIONS_UNMATCHED",
            reason="Provided conditions do not clearly match WTC certified categories — clinical review needed",
        )


# Rules in evaluation order (completeness first, then hard rules, then soft)
RULES = [
    rule_minimum_data_completeness,
    rule_exposure_site,
    rule_exposure_date_overlap,
    rule_wtc_health_program,
    rule_prior_attorney,
    rule_conditions_match,
]


def run_screening(case_id: str, case_data: dict) -> ScreeningResult:
    """
    Execute all rules and compute final eligibility.

    Decision logic:
      - Any hard_fail → INELIGIBLE (score=0)
      - All pass, no soft_flags → ELIGIBLE (score=95)
      - All pass, any soft_flags → NEEDS_REVIEW (score=60)
    """
    result = ScreeningResult(case_id=case_id, eligibility="pending")
    hard_fails = []
    soft_flags = []

    for rule_fn in RULES:
        rule_result = rule_fn(case_data)
        result.rule_results.append(rule_result)

        if not rule_result.passed and rule_result.severity == "hard_fail":
            hard_fails.append(rule_result.code)
        elif rule_result.severity == "soft_flag":
            soft_flags.append(rule_result.code)
            result.flags.append(rule_result.reason)

    if hard_fails:
        result.eligibility = "ineligible"
        result.score = 0
    elif soft_flags:
        result.eligibility = "needs_review"
        result.score = 60
    else:
        result.eligibility = "eligible"
        result.score = 95

    return result


# ── Cloud Function entrypoint ──────────────────────────────────────────────────

db = firestore.Client(project=GCP_PROJECT)
publisher = pubsub_v1.PublisherClient()


@functions_framework.cloud_event
def vcf_screener(cloud_event: CloudEvent) -> None:
    """
    Triggered by Pub/Sub 'lead-created' topic.
    Screens the case and updates Firestore, then publishes 'lead-screened'.
    Target completion: < 5 seconds.
    """
    # Decode Pub/Sub message
    raw = base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
    message = json.loads(raw)

    case_id = message.get("caseId")
    if not case_id:
        print(f"ERROR: No caseId in message: {message}")
        return

    print(f"VCF screening started: {case_id}")

    # Fetch case from Firestore
    case_ref = db.collection(CASES_COLLECTION).document(case_id)
    case_doc = case_ref.get()

    if not case_doc.exists:
        print(f"ERROR: Case not found: {case_id}")
        return

    case_data = case_doc.to_dict()

    # Run rule engine
    screening = run_screening(case_id, case_data)
    screening_dict = screening.to_dict()

    # Map eligibility to case status
    status_map = {
        "eligible": "Qualified",
        "ineligible": "Disqualified",
        "needs_review": "Needs Review",
    }
    new_status = status_map.get(screening.eligibility, "Screened")

    # Build history entry
    from datetime import datetime
    history_entry = {
        "status": new_status,
        "timestamp": datetime.utcnow().isoformat(),
        "updatedBy": "vcf-screener",
        "note": f"VCF screening: {screening.eligibility} (score={screening.score})",
    }

    # Update Firestore
    case_ref.update({
        "vcfEligibility": screening.eligibility,
        "vcfScreeningDetails": screening_dict,
        "status": new_status,
        "statusHistory": firestore.ArrayUnion([history_entry]),
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })

    print(f"VCF screening complete: {case_id} → {screening.eligibility} (score={screening.score}, status={new_status})")

    # Publish 'lead-screened' event
    topic_path = publisher.topic_path(GCP_PROJECT, LEAD_SCREENED_TOPIC)
    event_payload = json.dumps({
        "eventType": "lead-screened",
        "caseId": case_id,
        "eligibility": screening.eligibility,
        "score": screening.score,
        "flags": screening.flags,
        "newStatus": new_status,
        "requestId": message.get("requestId"),
    }).encode("utf-8")

    future = publisher.publish(
        topic_path,
        data=event_payload,
        caseId=case_id,
        eligibility=screening.eligibility,
    )
    future.result(timeout=10)
    print(f"Published lead-screened event for {case_id}")
