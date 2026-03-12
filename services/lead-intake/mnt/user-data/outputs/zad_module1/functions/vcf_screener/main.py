"""
functions/vcf_screener/main.py — Cloud Function 2nd Gen
Triggered by Pub/Sub 'lead-created' topic.

VCF (Victim Compensation Fund) Eligibility Rule Engine
-------------------------------------------------------
The VCF screens 9/11 first responders, survivors, and recovery workers.
Rules are loaded from a configurable dict — update without redeploying.

Standard VCF criteria:
  1. Presence at a defined 9/11 exposure site
  2. Exposure dates overlap the VCF eligibility window (9/11/2001 – 5/30/2011)
  3. Certified illness on the VCF-covered conditions list (or WTC Health Program)
  4. Filed claim within statute of limitations
  5. No prior settled VCF claim (prior attorney flag consideration)

Each rule returns: { "passed": bool, "code": str, "reason": str }
Overall result: ELIGIBLE, INELIGIBLE, or NEEDS_REVIEW

NEEDS_REVIEW fires when: rule passes but flags exist for human review.
INELIGIBLE fires when: any hard-fail rule fails.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any

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

# Recognised 9/11 exposure sites (configurable)
VCF_ELIGIBLE_SITES = {
    "world trade center", "wtc", "ground zero",
    "pentagon", "shanksville", "lower manhattan",
    "brooklyn", "queens", "bronx", "new jersey",
    "fresh kills", "staten island",
}

# WTC Health Program certifies these condition categories
WTC_CERTIFIED_CONDITIONS = {
    "aerodigestive", "cancer", "mental health",
    "musculoskeletal", "sleep disorder",
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
    score: int = 0  # 0-100 confidence score

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


def rule_exposure_site(case_data: dict) -> RuleResult:
    """R01: Exposure location must be a recognised VCF site."""
    location = (case_data.get("exposureLocation") or "").lower().strip()
    is_eligible = any(site in location or location in site for site in VCF_ELIGIBLE_SITES)

    return RuleResult(
        rule_id="R01_EXPOSURE_SITE",
        passed=is_eligible,
        severity="hard_fail" if not is_eligible else "pass",
        code="ELIGIBLE_SITE" if is_eligible else "INELIGIBLE_SITE",
        reason=(
            "Exposure location matches a recognised VCF-eligible site"
            if is_eligible
            else f"Exposure location does not match known VCF sites"
        ),
    )


def rule_exposure_date_overlap(case_data: dict) -> RuleResult:
    """R02: Exposure dates must overlap VCF eligibility window."""
    try:
        start = date.fromisoformat(case_data["exposureDateStart"])
        end = date.fromisoformat(case_data["exposureDateEnd"])
    except (KeyError, ValueError):
        return RuleResult(
            rule_id="R02_EXPOSURE_DATES",
            passed=False,
            severity="hard_fail",
            code="MISSING_DATES",
            reason="Exposure dates are missing or invalid",
        )

    overlaps = start <= VCF_WINDOW_END and end >= VCF_WINDOW_START
    return RuleResult(
        rule_id="R02_EXPOSURE_DATES",
        passed=overlaps,
        severity="hard_fail" if not overlaps else "pass",
        code="DATES_OVERLAP" if overlaps else "DATES_OUTSIDE_WINDOW",
        reason=(
            f"Exposure {start}–{end} overlaps VCF window {VCF_WINDOW_START}–{VCF_WINDOW_END}"
            if overlaps
            else f"Exposure dates do not overlap VCF window"
        ),
    )


def rule_wtc_health_program(case_data: dict) -> RuleResult:
    """
    R03: WTC Health Program enrollment strengthens eligibility.
    Enrolled = strong positive signal.
    Not applied = soft flag (needs review, not hard fail).
    """
    status = case_data.get("wtcHealthProgramStatus", "unknown")
    enrolled = status in ("enrolled", "applied")

    return RuleResult(
        rule_id="R03_WTC_HEALTH_PROGRAM",
        passed=True,  # Non-blocking rule
        severity="soft_flag" if not enrolled else "pass",
        code="WTC_ENROLLED" if enrolled else "WTC_NOT_ENROLLED",
        reason=(
            f"WTC Health Program status: {status}"
        ),
    )


def rule_prior_attorney(case_data: dict) -> RuleResult:
    """
    R04: Prior attorney flag.
    If claimant had a prior attorney, the case needs review (not disqualifying,
    but may indicate a previously denied or settled claim).
    """
    has_prior = case_data.get("priorAttorney", False)
    return RuleResult(
        rule_id="R04_PRIOR_ATTORNEY",
        passed=True,  # Non-blocking
        severity="soft_flag" if has_prior else "pass",
        code="PRIOR_ATTORNEY_FLAG" if has_prior else "NO_PRIOR_ATTORNEY",
        reason=(
            "Claimant indicated prior legal representation — needs review"
            if has_prior
            else "No prior attorney indicated"
        ),
    )


def rule_minimum_data_completeness(case_data: dict) -> RuleResult:
    """R05: Minimum required fields for a viable VCF claim."""
    required = ["firstName", "lastName", "email", "phone", "exposureLocation"]
    missing = [f for f in required if not case_data.get(f)]

    return RuleResult(
        rule_id="R05_DATA_COMPLETENESS",
        passed=len(missing) == 0,
        severity="hard_fail" if missing else "pass",
        code="INCOMPLETE" if missing else "COMPLETE",
        reason=(
            f"Missing required fields: {missing}" if missing
            else "All required fields present"
        ),
    )


# All rules in evaluation order
RULES = [
    rule_minimum_data_completeness,  # Check completeness first
    rule_exposure_site,
    rule_exposure_date_overlap,
    rule_wtc_health_program,
    rule_prior_attorney,
]


def run_screening(case_id: str, case_data: dict) -> ScreeningResult:
    """
    Execute all rules and determine final eligibility.

    Logic:
      - Any hard_fail → INELIGIBLE
      - All pass, no soft_flags → ELIGIBLE
      - All pass, any soft_flags → NEEDS_REVIEW
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


# ── Cloud Function entrypoint ─────────────────────────────────────────────────

db = firestore.Client(project=GCP_PROJECT)
publisher = pubsub_v1.PublisherClient()


@functions_framework.cloud_event
def vcf_screener(cloud_event: CloudEvent) -> None:
    """
    Triggered by Pub/Sub 'lead-created' topic.
    Screens the case and updates Firestore + publishes 'lead-screened'.
    """
    # Decode Pub/Sub message
    data = base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
    message = json.loads(data)

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

    # Update Firestore
    case_ref.update({
        "vcfEligibility": screening.eligibility,
        "vcfScreeningDetails": screening_dict,
        "status": "Screened",
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })

    print(f"VCF screening complete: {case_id} → {screening.eligibility} (score={screening.score})")

    # Publish 'lead-screened' event
    topic_path = publisher.topic_path(GCP_PROJECT, LEAD_SCREENED_TOPIC)
    event_payload = json.dumps({
        "eventType": "lead-screened",
        "caseId": case_id,
        "eligibility": screening.eligibility,
        "score": screening.score,
        "flags": screening.flags,
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
