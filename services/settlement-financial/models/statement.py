"""
models/statement.py
===================
Pydantic models for the settlement statement PDF generation endpoint.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class StatementGenerateRequest(BaseModel):
    """
    Optional overrides for the generated statement.
    All fields fall back to live Firestore / firm-settings data when omitted.
    """
    prepared_by:    Optional[str] = Field(None, description="Name shown in 'Prepared By' field")
    statement_date: Optional[str] = Field(None, description="Display date (e.g. 'May 3, 2026'); defaults to today")
    payment_method: Optional[str] = Field(None, description="e.g. 'Check', 'Wire Transfer'")
    payable_to:     Optional[str] = Field(None, description="Payee name; defaults to client name")
    memo:           Optional[str] = Field(None, description="Memo / reference line on the payment")


class StatementGenerateResponse(BaseModel):
    """Returned after a statement PDF is successfully generated and uploaded."""
    case_id:       str
    statement_id:  str                  # UUID stored in Firestore
    pdf_url:       str                  # Signed GCS download URL (15 min TTL)
    generated_at:  datetime
    prepared_by:   str
    statement_date: str
    gcs_path:      str                  # gs://bucket/path — for audit / re-download
