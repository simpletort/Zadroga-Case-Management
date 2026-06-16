"""
routers/dashboard.py — Enrollment pipeline dashboard API endpoints.

Endpoints:
  GET /api/v1/dashboard/enrollment   Full enrollment pipeline view (WTC + VCF)
  GET /api/v1/dashboard/deadlines    Deadline summary with color coding
  GET /api/v1/dashboard/export       Export enrollment data to CSV
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from middleware.auth import StaffUser, require_paralegal_or_above
from models.vcf_models import (
    DeadlineStatus,
    EnrollmentDashboardResponse,
    EnrollmentDashboardRow,
    DeadlineSummaryItem,
)
from services.firestore_client import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/enrollment",
    response_model=EnrollmentDashboardResponse,
    summary="Enrollment pipeline dashboard — WTC and VCF status overview",
)
async def enrollment_dashboard(
    paralegal_id: Optional[str] = Query(None, description="Filter by assigned paralegal UID"),
    wtc_status: Optional[str] = Query(None, description="Filter by WTC enrollment status"),
    vcf_status: Optional[str] = Query(None, description="Filter by VCF registration status"),
    deadline_status: Optional[str] = Query(None, description="Filter by deadline status (warning_30, warning_60, warning_90, expired)"),
    limit: int = Query(100, ge=1, le=500),
    current_user: StaffUser = Depends(require_paralegal_or_above),
):
    """
    Returns enrollment pipeline data for all cases.
    Supports filters by paralegal, WTC status, VCF status, deadline status.
    """
    db = get_db()
    today = date.today()

    # Build base query
    query = db.collection("cases")
    if paralegal_id:
        query = query.where("assignment.assignedParalegal", "==", paralegal_id)

    cases: list[EnrollmentDashboardRow] = []
    wtc_pipeline: dict[str, int] = {}
    vcf_pipeline: dict[str, int] = {}
    deadline_summary: dict[str, int] = {
        "active": 0,
        "warning_90": 0,
        "warning_60": 0,
        "warning_30": 0,
        "expired": 0,
        "not_set": 0,
    }
    overdue_count = 0

    async for doc in query.limit(limit * 3).stream():
        data = doc.to_dict() or {}
        case_id = doc.id
        enrollment = data.get("enrollment", {})
        case_wtc = enrollment.get("certificationStatus", "Not Enrolled")
        case_vcf = enrollment.get("registrationStatus", "Not Registered")
        deadline_str = enrollment.get("filingDeadline")
        case_paralegal = data.get("assignment", {}).get("assignedParalegal")

        # Apply filters
        if wtc_status and case_wtc != wtc_status:
            continue
        if vcf_status and case_vcf != vcf_status:
            continue

        # Compute deadline info
        dl_status = DeadlineStatus.NOT_SET
        days_rem = None
        if deadline_str:
            try:
                dl_date = date.fromisoformat(deadline_str[:10])
                days_rem = (dl_date - today).days
                if days_rem < 0:
                    dl_status = DeadlineStatus.EXPIRED
                elif days_rem <= 30:
                    dl_status = DeadlineStatus.WARNING_30
                elif days_rem <= 60:
                    dl_status = DeadlineStatus.WARNING_60
                elif days_rem <= 90:
                    dl_status = DeadlineStatus.WARNING_90
                else:
                    dl_status = DeadlineStatus.ACTIVE
            except (ValueError, TypeError):
                pass

        if deadline_status and dl_status.value != deadline_status:
            continue

        # Tally pipeline counts
        wtc_pipeline[case_wtc] = wtc_pipeline.get(case_wtc, 0) + 1
        vcf_pipeline[case_vcf] = vcf_pipeline.get(case_vcf, 0) + 1
        deadline_summary[dl_status.value] = deadline_summary.get(dl_status.value, 0) + 1
        if dl_status == DeadlineStatus.EXPIRED:
            overdue_count += 1

        last_updated = enrollment.get("registrationUpdatedAt") or enrollment.get("certificationUpdatedAt")
        last_updated_str = None
        if last_updated:
            try:
                last_updated_str = (
                    last_updated.isoformat()
                    if hasattr(last_updated, "isoformat")
                    else str(last_updated)
                )
            except Exception:
                pass

        cases.append(EnrollmentDashboardRow(
            case_id=case_id,
            wtc_status=case_wtc,
            vcf_status=case_vcf,
            vcf_filing_deadline=deadline_str,
            deadline_status=dl_status,
            days_until_deadline=days_rem,
            assigned_paralegal=case_paralegal,
            last_updated=last_updated_str,
        ))

        if len(cases) >= limit:
            break

    return EnrollmentDashboardResponse(
        wtc_pipeline=wtc_pipeline,
        vcf_pipeline=vcf_pipeline,
        deadline_summary=deadline_summary,
        overdue_count=overdue_count,
        cases=cases,
        total=len(cases),
        filtered_by_paralegal=paralegal_id,
        filtered_by_status=wtc_status or vcf_status,
    )


@router.get(
    "/deadlines",
    response_model=list[DeadlineSummaryItem],
    summary="Deadline summary — cases with approaching VCF deadlines",
)
async def deadline_summary(
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description="Filter: warning_30, warning_60, warning_90, expired, active",
    ),
    paralegal_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    current_user: StaffUser = Depends(require_paralegal_or_above),
):
    """
    Returns all cases with VCF filing deadlines, sorted by urgency.
    Color coding: expired (red), warning_30 (orange), warning_60 (yellow), warning_90 (blue).
    """
    db = get_db()
    today = date.today()

    # query = db.collection("cases").where("enrollment.filingDeadline", ">", None)
    # Field name fixed: cases store the VCF filing deadline under
    # enrollment.filingDeadline, not enrollment.vcfFilingDeadline — the old
    # field name matched zero documents, so this endpoint always returned [].
    query = (db.collection("cases")
         .order_by("enrollment.filingDeadline")
         .start_after({"enrollment.filingDeadline": None}))

    results: list[DeadlineSummaryItem] = []

    async for doc in query.stream():
        data = doc.to_dict() or {}
        enrollment = data.get("enrollment", {})
        deadline_str = enrollment.get("filingDeadline")
        case_paralegal = data.get("assignment", {}).get("assignedParalegal")

        if paralegal_id and case_paralegal != paralegal_id:
            continue

        try:
            dl_date = date.fromisoformat(deadline_str[:10])
        except (ValueError, TypeError):
            continue

        days_rem = (dl_date - today).days
        if days_rem < 0:
            dl_status = DeadlineStatus.EXPIRED
        elif days_rem <= 30:
            dl_status = DeadlineStatus.WARNING_30
        elif days_rem <= 60:
            dl_status = DeadlineStatus.WARNING_60
        elif days_rem <= 90:
            dl_status = DeadlineStatus.WARNING_90
        else:
            dl_status = DeadlineStatus.ACTIVE

        if status_filter and dl_status.value != status_filter:
            continue

        results.append(DeadlineSummaryItem(
            case_id=doc.id,
            vcf_filing_deadline=deadline_str,
            days_until_deadline=days_rem,
            deadline_status=dl_status,
            vcf_registration_status=enrollment.get(
                "registrationStatus", "Not Registered"
            ),
            assigned_paralegal=case_paralegal,
        ))

        if len(results) >= limit:
            break

    # Sort by urgency: expired first, then fewest days
    results.sort(key=lambda r: r.days_until_deadline)

    return results


@router.get(
    "/export",
    summary="Export enrollment dashboard data to CSV",
)
async def export_csv(
    paralegal_id: Optional[str] = Query(None),
    current_user: StaffUser = Depends(require_paralegal_or_above),
):
    """Export all enrollment data as CSV. Filterable by paralegal."""
    db = get_db()
    today = date.today()

    query = db.collection("cases")
    if paralegal_id:
        query = query.where("assignment.assignedParalegal", "==", paralegal_id)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Case ID",
        "WTC Enrollment Status",
        "VCF Registration Status",
        "VCF Claim Number",
        "VCF Filing Deadline",
        "Days Until Deadline",
        "Deadline Status",
        "Assigned Paralegal",
        "Last Updated",
    ])

    async for doc in query.stream():
        data = doc.to_dict() or {}
        enrollment = data.get("enrollment", {})
        deadline_str = enrollment.get("vcfFilingDeadline", "")
        days_rem = ""
        dl_status = ""

        if deadline_str:
            try:
                dl_date = date.fromisoformat(deadline_str[:10])
                days_rem = str((dl_date - today).days)
                d = int(days_rem)
                if d < 0:
                    dl_status = "expired"
                elif d <= 30:
                    dl_status = "warning_30"
                elif d <= 60:
                    dl_status = "warning_60"
                elif d <= 90:
                    dl_status = "warning_90"
                else:
                    dl_status = "active"
            except (ValueError, TypeError):
                pass

        last_upd = enrollment.get("registrationUpdatedAt") or enrollment.get("certificationUpdatedAt")
        writer.writerow([
            doc.id,
            enrollment.get("certificationStatus", "Not Enrolled"),
            enrollment.get("registrationStatus", "Not Registered"),
            enrollment.get("registrationNumber", ""),
            deadline_str,
            days_rem,
            dl_status,
            data.get("assignment", {}).get("assignedParalegal", ""),
            str(last_upd)[:19] if last_upd else "",
        ])

    output.seek(0)
    filename = f"enrollment_export_{today.isoformat()}.csv"

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )