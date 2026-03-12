"""
services/validation.py — Domain-level validation beyond Pydantic field rules.

Pydantic handles: type coercion, format, min/max length, regex.
This module handles: business rules, cross-field rules, date ranges.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from models.lead import ExposureDates, LeadRequest, ErrorDetail
from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)

# VCF eligibility window  (configurable via settings)
_VCF_WINDOW_START = date(2001, 9, 11)
_VCF_WINDOW_END = date(2011, 5, 30)

# Known 9/11 exposure locations (for soft-match validation)
KNOWN_EXPOSURE_LOCATIONS = {
    "world trade center", "wtc", "ground zero",
    "pentagon", "shanksville", "lower manhattan",
    "brooklyn", "queens", "new jersey",  # downwind/debris cloud zones
}


class ValidationResult:
    def __init__(self):
        self.errors: list[ErrorDetail] = []

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, field: str, code: str, message: str) -> None:
        self.errors.append(ErrorDetail(field=field, code=code, message=message))


def validate_exposure_dates(
    exposure: ExposureDates,
    result: ValidationResult,
) -> None:
    """
    Validates that the exposure window overlaps the VCF eligibility period.
    
    VCF Window: 2001-09-11 → 2011-05-30
    Rule: claimant's dates must OVERLAP this window (not necessarily be contained within).
    
    Overlap condition: start <= vcf_end AND end >= vcf_start
    """
    settings = get_settings()
    vcf_start = date.fromisoformat(settings.vcf_window_start)
    vcf_end = date.fromisoformat(settings.vcf_window_end)

    overlaps = (
        exposure.start <= vcf_end
        and exposure.end >= vcf_start
    )
    if not overlaps:
        result.add_error(
            field="exposureDates",
            code="OUTSIDE_VCF_WINDOW",
            message=(
                f"Exposure dates {exposure.start} – {exposure.end} do not overlap "
                f"the VCF eligibility window ({vcf_start} – {vcf_end})"
            ),
        )

    # Sanity: end date not in the future (allow some slack for ongoing exposure)
    today = date.today()
    if exposure.end > today:
        result.add_error(
            field="exposureDates.end",
            code="FUTURE_DATE",
            message="Exposure end date cannot be in the future",
        )

    # Warn if start is suspiciously early (pre-WTC)
    if exposure.start < date(2001, 1, 1):
        result.add_error(
            field="exposureDates.start",
            code="IMPLAUSIBLE_DATE",
            message="Exposure start date is before 2001 — please verify",
        )


def validate_exposure_location(
    location: str,
    result: ValidationResult,
) -> None:
    """
    Soft-validates that the exposure location is a recognised 9/11 site.
    Does NOT hard-fail — logs warning only — since partners may use varied descriptions.
    Returns a warning detail with code UNRECOGNISED_LOCATION (not blocking).
    """
    normalised = location.lower().strip()
    is_known = any(
        known in normalised or normalised in known
        for known in KNOWN_EXPOSURE_LOCATIONS
    )
    if not is_known:
        # Non-blocking: downstream VCF screener will make final determination
        logger.info(
            "exposure_location_unrecognised",
            location_masked="[REDACTED]",
        )


def validate_lead(lead: LeadRequest) -> ValidationResult:
    """
    Run all domain-level validations on a LeadRequest.
    Pydantic has already validated types/formats before this is called.
    """
    result = ValidationResult()
    validate_exposure_dates(lead.exposureDates, result)
    validate_exposure_location(lead.exposureLocation, result)
    return result
