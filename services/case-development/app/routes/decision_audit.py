# Endpoints defined in this module:
#   GET /api/v1/audit/decisions                    — query all decisions        (min: junior_partner)
#   GET /api/v1/cases/{caseId}/audit/decisions     — case decision history      (min: junior_partner)
#   GET /api/v1/audit/decisions/metrics            — time-to-decision metrics   (min: senior_partner)
#   GET /api/v1/audit/decisions/report             — compliance export           (min: senior_partner)
#
# All endpoints are READ-ONLY.  No writes are performed here.

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Path, Query

from app.models.decision_audit import (
    AttorneyMetrics,
    CaseDecisionHistory,
    DecisionAuditItem,
    DecisionAuditPage,
    DecisionAuditResponse,
    DecisionMetricsResponse,
    DecisionReportResponse,
)
from app.services.decision_audit_service import (
    generate_compliance_report,
    get_case_decisions,
    get_decision_metrics,
    get_decisions,
)
from app.utils.auth import require_min_role
from app.utils.firestore import get_firestore_client

router = APIRouter(prefix="/api/v1", tags=["Decision Audit"])


# ── 1. Paginated cross-case query ─────────────────────────────────────────────

@router.get(
    "/audit/decisions",
    response_model=DecisionAuditResponse,
    summary="Query decision audit trail — filterable by case, attorney, date, and type",
)
def get_audit_decisions(
    case_id:       Optional[str]      = Query(default=None, description="Filter by case ID"),
    performed_by:  Optional[str]      = Query(default=None, description="Filter by actor UID"),
    date_from:     Optional[datetime] = Query(default=None, description="Earliest timestamp (inclusive)"),
    date_to:       Optional[datetime] = Query(default=None, description="Latest timestamp (inclusive)"),
    decision_type: Optional[str]      = Query(default=None, description="Filter by decision type"),
    page:          int                = Query(default=1,  ge=1,   description="Page number"),
    page_size:     int                = Query(default=20, ge=1, le=100, description="Items per page"),
    user: dict = Depends(require_min_role("audit_decisions_read")),
):
    db     = get_firestore_client()
    result = get_decisions(
        db=db,
        case_id=case_id,
        performed_by=performed_by,
        date_from=date_from,
        date_to=date_to,
        decision_type=decision_type,
        page=page,
        page_size=page_size,
    )
    page_data = result["page"]
    return DecisionAuditResponse(
        total_decisions=result["total_decisions"],
        page=DecisionAuditPage(
            items=[DecisionAuditItem(**item) for item in page_data["items"]],
            total=page_data["total"],
            page=page_data["page"],
            page_size=page_data["page_size"],
            total_pages=page_data["total_pages"],
        ),
    )


# ── 2. Single-case decision history ──────────────────────────────────────────

@router.get(
    "/cases/{caseId}/audit/decisions",
    response_model=CaseDecisionHistory,
    summary="Return the full decision history for a single case (chronological)",
)
def get_case_audit_decisions(
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
    user: dict = Depends(require_min_role("audit_decisions_read")),
):
    db     = get_firestore_client()
    result = get_case_decisions(db=db, case_id=caseId)
    return CaseDecisionHistory(
        case_id=result["case_id"],
        decisions=[DecisionAuditItem(**d) for d in result["decisions"]],
        total=result["total"],
    )


# ── 3. Time-to-decision metrics ───────────────────────────────────────────────

@router.get(
    "/audit/decisions/metrics",
    response_model=DecisionMetricsResponse,
    summary="Aggregate time-to-decision metrics — by type, attorney, and date range",
)
def get_audit_metrics(
    date_from:     Optional[datetime] = Query(default=None),
    date_to:       Optional[datetime] = Query(default=None),
    performed_by:  Optional[str]      = Query(default=None),
    decision_type: Optional[str]      = Query(default=None),
    user: dict = Depends(require_min_role("audit_metrics_read")),
):
    db     = get_firestore_client()
    result = get_decision_metrics(
        db=db,
        date_from=date_from,
        date_to=date_to,
        performed_by=performed_by,
        decision_type=decision_type,
    )
    return DecisionMetricsResponse(
        total_decisions=result["total_decisions"],
        by_decision_type=result["by_decision_type"],
        avg_review_duration_seconds=result["avg_review_duration_seconds"],
        avg_review_duration_by_type=result["avg_review_duration_by_type"],
        by_attorney=[AttorneyMetrics(**a) for a in result["by_attorney"]],
        date_from=result["date_from"],
        date_to=result["date_to"],
    )


# ── 4. Compliance report export ───────────────────────────────────────────────

@router.get(
    "/audit/decisions/report",
    response_model=DecisionReportResponse,
    summary="Full compliance audit export — all fields, all records, chronological",
)
def get_audit_report(
    date_from:     Optional[datetime] = Query(default=None),
    date_to:       Optional[datetime] = Query(default=None),
    performed_by:  Optional[str]      = Query(default=None),
    case_id:       Optional[str]      = Query(default=None),
    decision_type: Optional[str]      = Query(default=None),
    user: dict = Depends(require_min_role("audit_report_export")),
):
    db     = get_firestore_client()
    result = generate_compliance_report(
        db=db,
        date_from=date_from,
        date_to=date_to,
        performed_by=performed_by,
        case_id=case_id,
        decision_type=decision_type,
    )
    return DecisionReportResponse(
        generated_at=result["generated_at"],
        filters_applied=result["filters_applied"],
        total_records=result["total_records"],
        records=[DecisionAuditItem(**r) for r in result["records"]],
    )
