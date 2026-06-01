"""
api/services/vcf_screener.py — Dynamic VCF eligibility rule engine.

Rules are stored in Firestore at `screeningRules/{ruleId}` and fetched once
per process (module-level cache). Call `reset_rules_cache()` after any rule
update so the next screening run picks up the new configuration.

Supported operators:
  fields_not_empty  — all listed fields must be non-empty
  in_list           — field value (or any array element) matches a list
  date_overlap      — two date fields overlap a configured date range
  boolean_equals    — boolean field equals an expected value
  number_in_range   — numeric field falls within [min, max]

Scoring:
  ELIGIBLE     — all hard rules pass, no soft flags  → score 95
  NEEDS_REVIEW — all hard rules pass, soft flags present → score 60
  INELIGIBLE   — any hard rule fails                 → score 0
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from google.cloud import firestore

from logging_config import get_logger

logger = get_logger(__name__)


# ── Module-level rules cache ────────────────────────────────────────────────────
# Same pattern as _case_id_prefix_cache in case_service.py.
# Populated on first call to _fetch_rules(); invalidated by reset_rules_cache().

_rules_cache: Optional[list[dict]] = None


async def _fetch_rules(db: firestore.AsyncClient) -> list[dict]:
    global _rules_cache
    if _rules_cache is not None:
        return _rules_cache
    query = (
        db.collection("screeningRules")
        .where("enabled", "==", True)
        .order_by("order")
    )
    _rules_cache = [doc.to_dict() async for doc in query.stream()]
    logger.info("screening_rules_loaded", count=len(_rules_cache))
    return _rules_cache


def reset_rules_cache() -> None:
    """Invalidate the in-process rules cache. Call after any screeningRules write."""
    global _rules_cache
    _rules_cache = None


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


# ── Operator dispatcher ────────────────────────────────────────────────────────

def _run_operator(operator: str, params: dict, case_data: dict) -> tuple[bool, str]:
    """
    Evaluate a single operator against case_data.
    Returns (condition_met: bool, detail_message: str).
    """
    if operator == "fields_not_empty":
        fields  = params.get("fields", [])
        missing = [f for f in fields if not case_data.get(f)]
        return (
            not missing,
            f"Missing required fields: {missing}" if missing else "All required fields present",
        )

    elif operator == "in_list":
        field_name = params.get("field", "")
        values     = [v.lower() for v in params.get("values", [])]
        match_type = params.get("match_type", "substring")
        raw        = case_data.get(field_name)
        if raw is None:
            return (False, f"Field '{field_name}' not present")
        items = raw if isinstance(raw, list) else [raw]
        items = [str(i).lower().strip() for i in items]
        if match_type == "exact":
            matched = any(item in values for item in items)
        else:  # substring
            matched = any(
                any(v in item or item in v for v in values)
                for item in items
            )
        return (
            matched,
            "Matched in allowed list" if matched else "No match in allowed list",
        )

    elif operator == "date_overlap":
        try:
            start       = date.fromisoformat(str(case_data[params["field_start"]]))
            end         = date.fromisoformat(str(case_data[params["field_end"]]))
            range_start = date.fromisoformat(params["range_start"])
            range_end   = date.fromisoformat(params["range_end"])
        except (KeyError, ValueError, TypeError) as exc:
            return (False, f"Date parse error: {exc}")
        overlaps = start <= range_end and end >= range_start
        return (
            overlaps,
            f"{start}–{end} {'overlaps' if overlaps else 'does not overlap'} {range_start}–{range_end}",
        )

    elif operator == "boolean_equals":
        field_name = params.get("field", "")
        expected   = params.get("expected", False)
        value      = case_data.get(field_name)
        # Coerce string representations of booleans
        if isinstance(value, str):
            value = value.lower() in ("true", "1", "yes")
        met = bool(value) == bool(expected)
        return (met, f"'{field_name}' is {value!r}, expected {expected!r}")

    elif operator == "number_in_range":
        field_name = params.get("field", "")
        try:
            value = float(case_data.get(field_name, 0))
        except (TypeError, ValueError):
            return (False, f"Field '{field_name}' is not numeric")
        lo, hi   = params.get("min"), params.get("max")
        in_range = (lo is None or value >= lo) and (hi is None or value <= hi)
        return (in_range, f"{value} {'in' if in_range else 'outside'} range [{lo}, {hi}]")

    else:
        # Unknown operator — treat as pass (forward-compatible with future operators)
        logger.warning("screening_unknown_operator", operator=operator)
        return (True, f"Unknown operator '{operator}' — skipped")


def _evaluate_rule(rule: dict, case_data: dict) -> RuleResult:
    """Apply one rule definition to case_data and return a RuleResult."""
    condition_met, detail = _run_operator(
        rule.get("operator", ""),
        rule.get("params", {}),
        case_data,
    )
    severity = rule.get("severity", "hard_fail")

    if condition_met:
        return RuleResult(
            rule_id  = rule["ruleId"],
            passed   = True,
            severity = "pass",
            code     = rule.get("passCode", "PASSED"),
            reason   = rule.get("passReason") or detail,
        )

    return RuleResult(
        rule_id  = rule["ruleId"],
        # soft_flag rules keep passed=True (consistent with old behaviour — flags don't
        # hard-reject, they raise the needs_review flag in the aggregate score)
        passed   = severity != "hard_fail",
        severity = severity,
        code     = rule.get("failCode", "FAILED"),
        reason   = rule.get("failReason") or detail,
    )


# ── Public API ─────────────────────────────────────────────────────────────────

async def run_screening(
    case_id:   str,
    case_data: dict,
    db:        firestore.AsyncClient,
) -> ScreeningResult:
    """
    Fetch enabled rules from Firestore (cached), evaluate them in order,
    and return a ScreeningResult.

    If no rules are configured the result is ELIGIBLE with score 95.

    Decision logic:
      - Any hard_fail  → INELIGIBLE (score 0)
      - All pass, soft flags present → NEEDS_REVIEW (score 60)
      - All pass, no soft flags      → ELIGIBLE (score 95)
    """
    rules      = await _fetch_rules(db)
    result     = ScreeningResult(case_id=case_id, eligibility="pending")
    hard_fails = []
    soft_flags = []

    for rule in rules:
        rule_result = _evaluate_rule(rule, case_data)
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

    logger.info(
        "vcf_screening_complete",
        case_id     = case_id,
        eligibility = result.eligibility,
        score       = result.score,
        rules_run   = len(rules),
    )
    return result
