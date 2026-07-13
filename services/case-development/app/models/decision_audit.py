from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator


# ── Per-record item ────────────────────────────────────────────────────────────

class DecisionAuditItem(BaseModel):
    event_id:                    str
    case_id:                     str
    decision_type:               str
    event_type:                  str
    performed_by:                str
    performed_by_name:           Optional[str] = None
    performed_by_role:           str
    timestamp:                   datetime
    previous_status:             str
    new_status:                  str
    reason:                      Optional[str] = None
    notes:                       Optional[str] = None
    review_duration_seconds:     Optional[int] = None
    case_submitted_for_review_at: Optional[datetime] = None
    related_doc_id:              Optional[str] = None
    created_at:                  datetime


# ── Paginated list response ────────────────────────────────────────────────────

class DecisionAuditPage(BaseModel):
    items:       list[DecisionAuditItem]
    total:       int
    page:        int
    page_size:   int
    total_pages: int


class DecisionAuditResponse(BaseModel):
    total_decisions: int
    page:            DecisionAuditPage


# ── Single-case history ────────────────────────────────────────────────────────

class CaseDecisionHistory(BaseModel):
    case_id:   str
    decisions: list[DecisionAuditItem]
    total:     int


# ── Metrics response ───────────────────────────────────────────────────────────

class AttorneyMetrics(BaseModel):
    performed_by:                str
    performed_by_name:           Optional[str] = None
    decision_count:              int
    avg_review_duration_seconds: Optional[float] = None
    decisions_by_type:           dict[str, int]


class DecisionMetricsResponse(BaseModel):
    total_decisions:              int
    by_decision_type:             dict[str, int]
    avg_review_duration_seconds:  Optional[float] = None
    avg_review_duration_by_type:  dict[str, Optional[float]]
    by_attorney:                  list[AttorneyMetrics]
    date_from:                    Optional[datetime] = None
    date_to:                      Optional[datetime] = None


# ── Compliance report response ─────────────────────────────────────────────────

class DecisionReportResponse(BaseModel):
    generated_at:    datetime
    filters_applied: dict
    total_records:   int
    records:         list[DecisionAuditItem]
