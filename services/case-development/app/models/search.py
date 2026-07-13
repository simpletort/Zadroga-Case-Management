from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class SearchCaseSummary(BaseModel):
    case_id: str
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    status: str
    case_type: Optional[str] = None               # "WTC" | "VCF"
    vcf_deadline: Optional[datetime] = None
    doc_completeness_pct: Optional[float] = None  # vcfQualScore proxy (0-100)
    qual_score: Optional[float] = None            # medicalQualScore (0-100)
    screening_result: Optional[str] = None
    last_activity: Optional[datetime] = None      # updatedAt
    created_at: Optional[datetime] = None
    assigned_paralegal: Optional[str] = None
    assigned_attorney: Optional[str] = None
    is_flagged: bool = False


class SearchPage(BaseModel):
    items: list[SearchCaseSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


class SearchResponse(BaseModel):
    page: SearchPage


class FilterPresetFilters(BaseModel):
    q: Optional[str] = None
    statuses: Optional[list[str]] = None
    case_type: Optional[str] = None
    assignees: Optional[list[str]] = None
    attorney: Optional[list[str]] = None
    deadline_from: Optional[datetime] = None
    deadline_to: Optional[datetime] = None
    created_from: Optional[datetime] = None
    created_to: Optional[datetime] = None
    completeness_min: Optional[float] = None
    completeness_max: Optional[float] = None
    qual_min: Optional[float] = None
    qual_max: Optional[float] = None
    screening_result: Optional[str] = None
    sort_by: Optional[str] = None
    sort_dir: Optional[str] = None


class FilterPreset(BaseModel):
    preset_id: str
    name: str
    filters: FilterPresetFilters
    created_at: datetime
    updated_at: datetime


class FilterPresetRequest(BaseModel):
    name: str
    filters: FilterPresetFilters


class FilterPresetListResponse(BaseModel):
    presets: list[FilterPreset]
