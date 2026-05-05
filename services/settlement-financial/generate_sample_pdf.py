"""
generate_sample_pdf.py
======================
Run this script to preview the settlement statement PDF template.

    python generate_sample_pdf.py
    python generate_sample_pdf.py --logo simpletort-icon-accent.png

Opens  ->  settlement_statement_SAMPLE.pdf
"""
import os
import sys
from templates.settlement_statement_template import build_settlement_pdf
from decimal import Decimal

LOGO_DIR  = r"C:\Zadroga-Case-Management\services\Logo"
LOGO_PATH = os.path.join(LOGO_DIR, "simpletort-icon-accent.png")  # default

SAMPLE_DATA = {
    # Firm branding
    "firm_name":    "ABC Law Group",
    "firm_address": "123 Legal Plaza, Suite 400, New York, NY 10001",
    "firm_phone":   "(212) 555-0100",
    "firm_email":   "settlements@simpletort.com",

    # Case info
    "client_name":      "John Michael Doe",
    "case_id":          "ZAD-2026-04-0001",
    "case_type":        "Zadroga / WTC Health Program",
    "statement_date":   "April 29, 2026",
    "prepared_by":      "Sarah Johnson, Paralegal",

    # Settlement figures
    "gross_award":      Decimal("500000.00"),
    "attorney_fee_pct": Decimal("33.33"),
    "attorney_fee":     Decimal("166650.00"),

    # Itemized expenses
    "expenses": [
        {"description": "Filing Fee",      "amount": Decimal("500.00")},
        {"description": "Medical Records", "amount": Decimal("850.00")},
        {"description": "Expert Witness",  "amount": Decimal("3500.00")},
    ],

    # Liens
    "liens": [
        {"lienholder": "Medicare",  "type": "Medical",    "amount": Decimal("12000.00"), "disputed": False},
        {"lienholder": "Medicaid",  "type": "Government", "amount": Decimal("3200.00"),  "disputed": False},
        {"lienholder": "Aetna",     "type": "Private",    "amount": Decimal("5500.00"),  "disputed": True},
    ],

    # Loans
    "loans": [
        {"lender": "LawCash Advances", "amount": Decimal("5000.00"), "payoff": Decimal("5750.00")},
    ],

    # Totals
    "total_expenses":   Decimal("4850.00"),
    "total_liens":      Decimal("20700.00"),
    "total_loans":      Decimal("5750.00"),
    "total_deductions": Decimal("197950.00"),
    "net_to_client":    Decimal("302050.00"),

    # Payment
    "payment_method":   "Check",
    "payable_to":       "John Michael Doe",
    "memo":             "Settlement - ZAD-2026-04-0001",
}

if __name__ == "__main__":
    # Optional: pass a logo filename as argument
    # e.g.  python generate_sample_pdf.py simpletort-icon-transparent-white.png
    if len(sys.argv) > 1:
        LOGO_PATH = os.path.join(LOGO_DIR, sys.argv[1])

    out = "settlement_statement_SAMPLE.pdf"
    build_settlement_pdf(SAMPLE_DATA, out, logo_path=LOGO_PATH)
    print(f"[OK]  PDF  : {out}")
    print(f"[OK]  Logo : {LOGO_PATH}")
    os.startfile(os.path.abspath(out))
