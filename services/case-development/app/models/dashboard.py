from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class CaseSummary(BaseModel):
    case_id: str
    first_name: str
    last_name: str
    status: str
    case_type: Optional[str] = None                # "WTC" | "VCF"
    vcf_deadline: Optional[datetime] = None
    doc_completeness_pct: Optional[float] = None   # vcfQualScore proxy (0-100)
    qual_score: Optional[float] = None             # medicalQualScore (0-100)
    last_activity: Optional[datetime] = None       # updatedAt
    assigned_paralegal: Optional[str] = None
    is_flagged: bool = False                        # local UI toggle, always False from API


class DashboardPage(BaseModel):
    items: list[CaseSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


class DashboardSummary(BaseModel):
    total_assigned: int
    overdue_deadline: int          # vcfRegDeadline < today
    pending_review: int            # status == "Pending Paralegal Review"
    avg_qual_score: Optional[float] = None


class DashboardResponse(BaseModel):
    summary: DashboardSummary
    page: DashboardPage
