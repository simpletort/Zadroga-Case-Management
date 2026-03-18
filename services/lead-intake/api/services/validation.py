"""
api/services/validation.py — Domain-level validation beyond Pydantic.
"""
from __future__ import annotations
from datetime import date
from models.lead import ExposureDates, LeadRequest, ErrorDetail
from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)


class ValidationResult:
    def __init__(self):
        self.errors: list[ErrorDetail] = []

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, field: str, code: str, message: str) -> None:
        self.errors.append(ErrorDetail(field=field, code=code, message=message))


KNOWN_EXPOSURE_LOCATIONS = {
    "world trade center", "wtc", "ground zero",
    "pentagon", "shanksville", "lower manhattan",
    "brooklyn", "queens", "new jersey",
    "fresh kills", "staten island", "bronx",
}


def validate_exposure_dates(exposure: ExposureDates, result: ValidationResult) -> None:
    settings = get_settings()
    vcf_start = date.fromisoformat(settings.vcf_window_start)
    vcf_end = date.fromisoformat(settings.vcf_window_end)

    overlaps = exposure.start <= vcf_end and exposure.end >= vcf_start
    if not overlaps:
        result.add_error(
            "exposureDates", "OUTSIDE_VCF_WINDOW",
            f"Exposure dates {exposure.start} – {exposure.end} do not overlap the VCF window ({vcf_start} – {vcf_end})",
        )

    if exposure.end > date.today():
        result.add_error("exposureDates.end", "FUTURE_DATE", "Exposure end date cannot be in the future")

    if exposure.start < date(2001, 1, 1):
        result.add_error("exposureDates.start", "IMPLAUSIBLE_DATE", "Exposure start date is before 2001 — please verify")


def validate_exposure_location(location: str, result: ValidationResult) -> None:
    normalised = location.lower().strip()
    is_known = any(known in normalised or normalised in known for known in KNOWN_EXPOSURE_LOCATIONS)
    if not is_known:
        logger.info("exposure_location_unrecognised", location_masked="[REDACTED]")


def validate_lead(lead: LeadRequest) -> ValidationResult:
    result = ValidationResult()
    validate_exposure_dates(lead.exposureDates, result)
    validate_exposure_location(lead.exposureLocation, result)
    return result
