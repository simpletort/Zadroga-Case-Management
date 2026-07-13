"""
scripts/preview_statement.py
=============================
Generates a sample settlement statement PDF using realistic data
and saves it to the Desktop (or current directory if Desktop not found).

Usage (from the settlement-financial service directory):
    python scripts/preview_statement.py

No Firestore or GCS connection required — all data is hardcoded here
so you can visually verify the PDF layout and content.
"""
import os
import sys
from decimal import Decimal

# Make sure the service root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from templates.settlement_statement_template import build_settlement_pdf

# ── Sample data (mirrors what Firestore would return) ─────────────────────────

GROSS     = Decimal("150000.00")
FEE_PCT   = Decimal("33.33")
ATT_FEE   = (GROSS * FEE_PCT / Decimal("100")).quantize(Decimal("0.01"))

pdf_data = {
    # Firm info — from firmSettings/profile
    "firm_name":    "ABC Law Group",
    "firm_address": "123 Main Street, New York, NY 10001",
    "firm_phone":   "(212) 555-0100",
    "firm_email":   "settlements@abclawgroup.com",

    # Case info — from cases/{caseId}
    "client_name":    "John Q. Smith",
    "case_id":        "CASE-2024-0042",
    "case_type":      "Workers Compensation",   # ← comes from firmSettings/intake.programName

    # Statement meta
    "statement_date": "May 23, 2026",
    "prepared_by":    "Settlement Department",

    # Financials — from cases/{caseId}/settlement/inputs
    "gross_award":      GROSS,
    "attorney_fee_pct": FEE_PCT,
    "attorney_fee":     ATT_FEE,

    # Expenses — from cases/{caseId}/settlement/expenses
    "expenses": [
        {"description": "Medical Records",  "amount": Decimal("250.00")},
        {"description": "Court Filing Fee", "amount": Decimal("400.00")},
        {"description": "Expert Witness",   "amount": Decimal("1500.00")},
    ],
    "total_expenses": Decimal("2150.00"),

    # Liens — from cases/{caseId}/settlement/liens
    "liens": [
        {"lienholder": "Medicare",     "type": "Federal",  "amount": Decimal("8200.00"),  "disputed": False},
        {"lienholder": "Health Plus",  "type": "Private",  "amount": Decimal("3400.00"),  "disputed": True},
    ],
    "total_liens": Decimal("11600.00"),

    # Loans — from cases/{caseId}/settlement/loans
    "loans": [
        {"lender": "LegalFund LLC", "amount": Decimal("5000.00"), "payoff": Decimal("5500.00")},
    ],
    "total_loans": Decimal("5500.00"),

    # Computed totals
    "total_deductions": (ATT_FEE + Decimal("2150.00") + Decimal("11600.00") + Decimal("5500.00")).quantize(Decimal("0.01")),
    "net_to_client":    (GROSS  - (ATT_FEE + Decimal("2150.00") + Decimal("11600.00") + Decimal("5500.00"))).quantize(Decimal("0.01")),

    # Disbursement info
    "payment_method": "Check",
    "payable_to":     "John Q. Smith",
    "memo":           "Settlement – CASE-2024-0042",
}

# ── Output path ───────────────────────────────────────────────────────────────

desktop = os.path.join(os.path.expanduser("~"), "Desktop")
out_dir  = desktop if os.path.isdir(desktop) else os.getcwd()
out_path = os.path.join(out_dir, "sample_settlement_statement.pdf")

# ── Generate ──────────────────────────────────────────────────────────────────

print("Generating PDF...")
build_settlement_pdf(pdf_data, out_path, logo_path=None)
print(f"\nPDF saved to: {out_path}")
print("Open it to verify the layout, firm name, case type, and all financial figures.")
