"""
api/services/vcf_screener.py — Inline VCF eligibility rule engine.

Previously lived in functions/vcf_screener/main.py as a Cloud Function
triggered by the 'lead-created' Pub/Sub topic.

Architecture change: VCF screening is now SYNCHRONOUS and runs inside the
FastAPI POST /leads handler immediately after case creation.  This removes
the async Pub/Sub round-trip (lead → Pub/Sub → Cloud Function → Firestore
re-read → Pub/Sub lead-screened) and gives callers an immediate eligibility
verdict in the 201 response.

The 'lead-screened' Pub/Sub topic is still published after screening so the
external Notification Dispatcher service can react to the result.

Rules:
  R01 — Exposure site must match a recognised VCF-eligible site (hard fail)
  R02 — Exposure dates must overlap VCF window 2001-09-11 – 2011-05-30 (hard fail)
  R03 — WTC Health Program enrollment status (soft flag)
  R04 — Prior attorney flag (soft flag)
  R05 — Minimum data completeness (hard fail)
  R06 — Medical conditions match VCF-covered categories (soft flag)

Scoring:
  ELIGIBLE     — all hard rules pass, no soft flags  → score 95
  NEEDS_REVIEW — all hard rules pass, soft flags present → score 60
  INELIGIBLE   — any hard rule fails                 → score 0
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


# ── Constants ──────────────────────────────────────────────────────────────────

VCF_WINDOW_START = date(2001, 9, 11)
VCF_WINDOW_END   = date(2011, 5, 30)

# Recognised VCF exposure sites (42 U.S.C. § 300mm et seq.)
VCF_ELIGIBLE_SITES: frozenset[str] = frozenset({
    "world trade center", "wtc", "ground zero",
    "pentagon", "shanksville", "lower manhattan",
    "brooklyn", "queens", "bronx", "new jersey",
    "fresh kills", "staten island",
})

# WTC Health Program certified condition keywords (42 U.S.C. § 300mm-22)
WTC_CERTIFIED_CONDITIONS: frozenset[str] = frozenset({
    # Aerodigestive
    "aerodigestive", "rhinosinusitis", "nasopharyngitis", "laryngitis",
    "pharyngitis", "upper airway", "sleep apnea", "interstitial lung",
    "asthma", "reactive airways", "wld", "reactive upper airways",
    # Cancer (45 categories covered)
    "cancer", "mesothelioma", "lymphoma", "leukemia", "myeloma",
    "thyroid", "prostate", "breast", "bladder", "colon", "rectal",
    "esophageal", "skin cancer", "melanoma",
    # Mental health
    "mental health", "ptsd", "depression", "anxiety", "adjustment disorder",
    # Musculoskeletal
    "musculoskeletal", "carpal tunnel", "tendinitis",
    # Gastroesophageal
    "gastrointestinal", "gerd", "gastroesophageal",
    # Sleep
    "sleep disorder", "insomnia",
    # Neurological
    "neurological", "peripheral neuropathy",
    # Respiratory
    "respiratory", "copd", "chronic bronchitis", "emphysema",
})


# ── Result models ──────────────────────────────────────────────────────────────

@dataclass
class RuleResult:
    rule_id:  str
    passed:   bool
    severity: str   # "hard_fail" | "soft_flag" | "pass"
    code:     str
    reason:   str


@dataclass
class ScreeningResult:
    case_id:     str
    eligibility: str          # "eligible" | "ineligible" | "needs_review"
    score:       int = 0
    flags:       list[str] = field(default_factory=list)
    rule_results: list[RuleResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "eligibility":  self.eligibility,
            "score":        self.score,
            "flags":        self.flags,
            "ruleResults":  [
                {
                    "ruleId":   r.rule_id,
                    "passed":   r.passed,
                    "severity": r.severity,
                    "code":     r.code,
                    "reason":   r.reason,
                }
                for r in self.rule_results
            ],
        }

    @property
    def case_status(self) -> str:
        """Map eligibility → CaseStatus string used in Firestore."""
        return {
            "eligible":     "Qualified",
            "ineligible":   "Disqualified",
            "needs_review": "Needs Review",
        }.get(self.eligibility, "Screened")


# ── Individual rule functions ──────────────────────────────────────────────────

def rule_minimum_data_completeness(case_data: dict) -> RuleResult:
    """R05 — Required fields must be present."""
    required = ["firstName", "lastName", "email", "phone", "exposureLocation"]
    missing  = [f for f in required if not case_data.get(f)]
    return RuleResult(
        rule_id  = "R05_DATA_COMPLETENESS",
        passed   = not missing,
        severity = "hard_fail" if missing else "pass",
        code     = "INCOMPLETE" if missing else "COMPLETE",
        reason   = f"Missing required fields: {missing}" if missing else "All required fields present",
    )


def rule_exposure_site(case_data: dict) -> RuleResult:
    """R01 — Exposure location must match a recognised VCF site."""
    location = (case_data.get("exposureLocation") or "").lower().strip()
    if not location:
        return RuleResult(
            rule_id  = "R01_EXPOSURE_SITE",
            passed   = False,
            severity = "hard_fail",
            code     = "INELIGIBLE_SITE",
            reason   = "Exposure location is missing or empty",
        )
    is_eligible = any(site in location or location in site for site in VCF_ELIGIBLE_SITES)
    return RuleResult(
        rule_id  = "R01_EXPOSURE_SITE",
        passed   = is_eligible,
        severity = "hard_fail" if not is_eligible else "pass",
        code     = "ELIGIBLE_SITE" if is_eligible else "INELIGIBLE_SITE",
        reason   = (
            "Exposure location matches a recognised VCF-eligible site"
            if is_eligible
            else "Exposure location does not match known VCF sites"
        ),
    )


def rule_exposure_date_overlap(case_data: dict) -> RuleResult:
    """R02 — Exposure dates must overlap the VCF window 2001-09-11 – 2011-05-30."""
    try:
        start = date.fromisoformat(str(case_data["exposureDateStart"]))
        end   = date.fromisoformat(str(case_data["exposureDateEnd"]))
    except (KeyError, ValueError, TypeError):
        return RuleResult(
            rule_id  = "R02_EXPOSURE_DATES",
            passed   = False,
            severity = "hard_fail",
            code     = "MISSING_DATES",
            reason   = "Exposure dates are missing or invalid",
        )
    overlaps = start <= VCF_WINDOW_END and end >= VCF_WINDOW_START
    return RuleResult(
        rule_id  = "R02_EXPOSURE_DATES",
        passed   = overlaps,
        severity = "hard_fail" if not overlaps else "pass",
        code     = "DATES_OVERLAP" if overlaps else "DATES_OUTSIDE_WINDOW",
        reason   = (
            f"Exposure {start}–{end} overlaps VCF window {VCF_WINDOW_START}–{VCF_WINDOW_END}"
            if overlaps
            else f"Exposure dates {start}–{end} are entirely outside the VCF window"
        ),
    )


def rule_wtc_health_program(case_data: dict) -> RuleResult:
    """R03 — WTC Health Program enrollment status (soft flag if not enrolled)."""
    status   = case_data.get("wtcHealthProgramStatus", "unknown")
    enrolled = status in ("enrolled", "applied")
    return RuleResult(
        rule_id  = "R03_WTC_HEALTH_PROGRAM",
        passed   = True,
        severity = "soft_flag" if not enrolled else "pass",
        code     = "WTC_ENROLLED" if enrolled else "WTC_NOT_ENROLLED",
        reason   = f"WTC Health Program status: {status}",
    )


def rule_prior_attorney(case_data: dict) -> RuleResult:
    """R04 — Prior attorney flag (soft flag, triggers substitution workflow later)."""
    has_prior = bool(case_data.get("priorAttorney", False))
    return RuleResult(
        rule_id  = "R04_PRIOR_ATTORNEY",
        passed   = True,
        severity = "soft_flag" if has_prior else "pass",
        code     = "PRIOR_ATTORNEY_FLAG" if has_prior else "NO_PRIOR_ATTORNEY",
        reason   = (
            "Claimant indicated prior legal representation — manual review required"
            if has_prior
            else "No prior attorney indicated"
        ),
    )


def rule_conditions_match(case_data: dict) -> RuleResult:
    """R06 — Medical conditions match VCF-covered categories (soft flag if no match)."""
    conditions: list = case_data.get("conditions", [])
    if not conditions:
        return RuleResult(
            rule_id  = "R06_CONDITIONS",
            passed   = True,
            severity = "soft_flag",
            code     = "NO_CONDITIONS_PROVIDED",
            reason   = "No medical conditions provided — condition verification required at intake",
        )
    normalised = [str(c).lower().strip() for c in conditions]
    matched    = [
        cond for cond in normalised
        if any(covered in cond or cond in covered for covered in WTC_CERTIFIED_CONDITIONS)
    ]
    if matched:
        return RuleResult(
            rule_id  = "R06_CONDITIONS",
            passed   = True,
            severity = "pass",
            code     = "CONDITIONS_MATCHED",
            reason   = f"Conditions matching VCF coverage: {matched}",
        )
    return RuleResult(
        rule_id  = "R06_CONDITIONS",
        passed   = True,
        severity = "soft_flag",
        code     = "CONDITIONS_UNMATCHED",
        reason   = "Provided conditions do not clearly match WTC certified categories — clinical review needed",
    )


# Rules evaluated in order: completeness → hard rules → soft flags
_RULES = [
    rule_minimum_data_completeness,
    rule_exposure_site,
    rule_exposure_date_overlap,
    rule_wtc_health_program,
    rule_prior_attorney,
    rule_conditions_match,
]


# ── Public API ─────────────────────────────────────────────────────────────────

def run_screening(case_id: str, case_data: dict) -> ScreeningResult:
    """
    Run all VCF eligibility rules against a case dict and return the result.

    Decision logic:
      - Any hard_fail  → INELIGIBLE (score 0)
      - All pass, soft flags present → NEEDS_REVIEW (score 60)
      - All pass, no soft flags      → ELIGIBLE (score 95)
    """
    result     = ScreeningResult(case_id=case_id, eligibility="pending")
    hard_fails = []
    soft_flags = []

    for rule_fn in _RULES:
        rule_result = rule_fn(case_data)
        result.rule_results.append(rule_result)

        if not rule_result.passed and rule_result.severity == "hard_fail":
            hard_fails.append(rule_result.code)
        elif rule_result.severity == "soft_flag":
            soft_flags.append(rule_result.code)
            result.flags.append(rule_result.reason)

    if hard_fails:
        result.eligibility = "ineligible"
        result.score       = 0
    elif soft_flags:
        result.eligibility = "needs_review"
        result.score       = 60
    else:
        result.eligibility = "eligible"
        result.score       = 95

    return result
