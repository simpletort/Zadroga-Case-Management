from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class KPIMetric(BaseModel):
    label: str
    value: float
    unit: str
    trend: Optional[float] = None
    trend_direction: Optional[str] = None


class KPIDashboardResponse(BaseModel):
    generated_at: datetime
    period_days: int
    metrics: list[KPIMetric]


class CasesByStatusItem(BaseModel):
    status: str
    count: int
    avg_days_in_status: Optional[float] = None


class CasesByStatusResponse(BaseModel):
    generated_at: datetime
    items: list[CasesByStatusItem]
    total_active: int


class FunnelStage(BaseModel):
    stage: str
    count: int
    conversion_rate: Optional[float] = None
    avg_days_to_next: Optional[float] = None


class FunnelResponse(BaseModel):
    generated_at: datetime
    stages: list[FunnelStage]


class Bottleneck(BaseModel):
    status: str
    case_count: int
    avg_days_stuck: float
    oldest_case_days: float
    assigned_paralegal_ids: list[str]


class BottleneckResponse(BaseModel):
    generated_at: datetime
    bottlenecks: list[Bottleneck]
    threshold_days: int


class StaffPerformanceItem(BaseModel):
    user_id: str
    display_name: str
    role: str
    active_cases: int
    cases_completed_period: int
    cases_handled_ytd: int = 0
    avg_days_to_close: Optional[float] = None
    avg_days_to_review: Optional[float] = None
    performance_rating: Optional[float] = None
    overdue_tasks: int


class StaffPerformanceResponse(BaseModel):
    generated_at: datetime
    period_days: int
    staff: list[StaffPerformanceItem]


class LeadConversionResponse(BaseModel):
    generated_at: datetime
    period_days: int
    total_leads: int
    qualified: int
    converted_to_active: int
    qualification_rate: float
    conversion_rate: float
    avg_days_lead_to_active: Optional[float] = None
    disqualified: int


class MonthlyRevenueItem(BaseModel):
    month: str                  # e.g. "Jul 2025"
    filings: int                # cases created in that calendar month
    awards: int                 # cases moved to Awarded/Settled in that month
    gross_award_total: float    # sum of gross_award from canonical settlement docs


class MonthlyRevenueResponse(BaseModel):
    generated_at: datetime
    months: list[MonthlyRevenueItem]
    ytd_expenses: float = 0.0
    net_margin: Optional[float] = None
