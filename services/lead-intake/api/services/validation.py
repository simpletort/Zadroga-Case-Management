"""
api/services/validation.py — Stub. Domain validation now handled by the screening rule engine.

All eligibility checks (exposure dates, exposure site, conditions, etc.) are configurable
rules stored in Firestore `screeningRules` and evaluated by `vcf_screener.run_screening()`.

This class is kept as a no-op stub to avoid breaking any imports or tests that reference it.
"""
from __future__ import annotations

from models.lead import ErrorDetail


class ValidationResult:
    def __init__(self):
        self.errors: list[ErrorDetail] = []

    @property
    def is_valid(self) -> bool:
        return True
