"""
templates/settlement_statement_template.py
==========================================
Clean one-page Settlement Distribution Statement.

Entry point
-----------
    build_settlement_pdf(data, output_path, logo_path=None) -> str
"""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable, Image, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)

BLACK    = colors.black
GRAY     = colors.HexColor("#555555")
LGRAY    = colors.HexColor("#CCCCCC")


def _money(v):
    if not v and v != 0:
        return ""
    return f"${Decimal(str(v)):,.2f}"

def _p(text, **kw):
    return Paragraph(text, ParagraphStyle("_", **kw))

def _rule():
    return HRFlowable(width="100%", thickness=0.5, color=LGRAY)

def _logo(path, max_h=0.55*inch, max_w=2.0*inch):
    if not path:
        return None, 0
    native = os.path.normpath(os.path.abspath(path))
    if not os.path.isfile(native):
        return None, 0
    try:
        from PIL import Image as PI
        with PI.open(native) as im:
            ow, oh = im.size
        ratio = ow / oh
        h = max_h
        w = min(h * ratio, max_w)
        h = w / ratio
        img = Image(native, width=w, height=h)
        img.hAlign = "LEFT"
        return img, w
    except Exception:
        return None, 0


def build_settlement_pdf(data: dict[str, Any], output_path: str,
                         logo_path: str | None = None) -> str:

    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        leftMargin=0.8*inch, rightMargin=0.8*inch,
        topMargin=0.6*inch, bottomMargin=0.6*inch,
    )
    W = 6.9 * inch
    story = []

    # ── HEADER ───────────────────────────────────────────────────────────────
    logo_img, logo_w = _logo(logo_path)

    firm_block = [
        _p(data["firm_name"],
           fontSize=15, fontName="Helvetica-Bold", textColor=BLACK, leading=19),
        _p(data["firm_address"],
           fontSize=8, fontName="Helvetica", textColor=GRAY, leading=12),
        _p(f'{data["firm_phone"]}  |  {data["firm_email"]}',
           fontSize=8, fontName="Helvetica", textColor=GRAY, leading=12),
    ]

    if logo_img:
        lc = logo_w + 0.15*inch
        hdr = Table(
            [[logo_img, Table([[p] for p in firm_block],
                              colWidths=[W - lc - 0.1*inch])]],
            colWidths=[lc, W - lc],
        )
        hdr.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING", (0,0), (-1,-1), 0),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0),
        ]))
        story.append(hdr)
    else:
        for p in firm_block:
            story.append(p)

    story.append(Spacer(1, 0.12*inch))
    story.append(_rule())
    story.append(Spacer(1, 0.08*inch))

    # ── TITLE ────────────────────────────────────────────────────────────────
    story.append(_p("Settlement Distribution Statement",
                    fontSize=13, fontName="Helvetica-Bold",
                    textColor=BLACK, alignment=TA_CENTER, leading=18))
    story.append(_p("Confidential &amp; Attorney-Client Privileged",
                    fontSize=8, fontName="Helvetica-Oblique",
                    textColor=GRAY, alignment=TA_CENTER, leading=12))
    story.append(Spacer(1, 0.12*inch))
    story.append(_rule())
    story.append(Spacer(1, 0.1*inch))

    # ── CASE INFO ────────────────────────────────────────────────────────────
    ci = Table([
        ["Client:",         data["client_name"],
         "Date:",           data["statement_date"]],
        ["Case ID:",        data["case_id"],
         "Prepared By:",    data["prepared_by"]],
        ["Case Type:",      data["case_type"], "", ""],
    ], colWidths=[0.9*inch, 2.65*inch, 1.0*inch, 2.35*inch])
    ci.setStyle(TableStyle([
        ("FONT",    (0,0), (-1,-1), "Helvetica",      8.5),
        ("FONT",    (0,0), (0,-1),  "Helvetica-Bold", 8.5),
        ("FONT",    (2,0), (2,-1),  "Helvetica-Bold", 8.5),
        ("TEXTCOLOR", (0,0), (-1,-1), BLACK),
        ("TOPPADDING",    (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("LEFTPADDING",   (0,0), (-1,-1), 0),
    ]))
    story.append(ci)
    story.append(Spacer(1, 0.12*inch))
    story.append(_rule())
    story.append(Spacer(1, 0.08*inch))

    # ── AMOUNTS TABLE ────────────────────────────────────────────────────────
    # All figures in one clean table
    COL = [5.4*inch, 1.5*inch]

    def row(label, amount, bold=False, indent=False):
        fn = "Helvetica-Bold" if bold else "Helvetica"
        lbl = _p(("    " if indent else "") + label,
                 fontSize=9, fontName=fn, textColor=BLACK, leading=13)
        amt = _p(_money(amount),
                 fontSize=9, fontName=fn, textColor=BLACK,
                 alignment=TA_RIGHT, leading=13)
        return [lbl, amt]

    def section(title):
        return [_p(title, fontSize=8.5, fontName="Helvetica-Bold",
                   textColor=GRAY, leading=12), ""]

    rows = []

    # Gross award
    rows.append(row("Gross Settlement Award", data["gross_award"], bold=True))
    rows.append(["", ""])   # spacer row

    # Deductions header
    rows.append(section("DEDUCTIONS"))
    rows.append(row(f'Attorney Fees ({data["attorney_fee_pct"]}%)',
                    data["attorney_fee"], indent=True))

    rows.append(row("Case Expenses", "", indent=False))
    for e in data["expenses"]:
        rows.append(row(e["description"], e["amount"], indent=True))
    rows.append(row("Subtotal Expenses", data["total_expenses"], bold=True, indent=True))

    rows.append(row("Liens", "", indent=False))
    for l in data["liens"]:
        desc = f'{l["lienholder"]} ({l["type"]})'
        if l.get("disputed"):
            desc += "  *DISPUTED*"
        rows.append(row(desc, l["amount"], indent=True))
    rows.append(row("Subtotal Liens", data["total_liens"], bold=True, indent=True))

    rows.append(row("Client Loans / Advances", "", indent=False))
    for l in data["loans"]:
        rows.append(row(l["lender"], l.get("payoff") or l["amount"], indent=True))
    rows.append(row("Subtotal Loans", data["total_loans"], bold=True, indent=True))

    rows.append(["", ""])   # spacer row
    rows.append(row("Total Deductions", data["total_deductions"], bold=True))
    rows.append(["", ""])   # spacer row
    rows.append(row("NET AMOUNT TO CLIENT", data["net_to_client"], bold=True))

    amt_table = Table(rows, colWidths=COL)

    # Style rules
    n = len(rows)
    net_idx   = n - 1
    tot_idx   = n - 3
    gross_idx = 0

    ts = [
        ("TOPPADDING",    (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("LEFTPADDING",   (0,0), (-1,-1), 0),
        ("RIGHTPADDING",  (0,0), (-1,-1), 0),
        # line under gross
        ("LINEBELOW", (0, gross_idx), (-1, gross_idx), 0.5, LGRAY),
        # line above / below total deductions
        ("LINEABOVE", (0, tot_idx), (-1, tot_idx), 0.5, LGRAY),
        ("LINEBELOW", (0, tot_idx), (-1, tot_idx), 0.5, LGRAY),
        # box around net to client
        ("BOX",       (0, net_idx), (-1, net_idx), 1.0, BLACK),
        ("TOPPADDING",    (0, net_idx), (-1, net_idx), 5),
        ("BOTTOMPADDING", (0, net_idx), (-1, net_idx), 5),
    ]
    amt_table.setStyle(TableStyle(ts))
    story.append(amt_table)
    story.append(Spacer(1, 0.1*inch))
    story.append(_rule())
    story.append(Spacer(1, 0.08*inch))

    # ── PAYMENT ───────────────────────────────────────────────────────────────
    pay = Table([
        ["Payment Method:",   data["payment_method"],
         "Payable To:",       data["payable_to"]],
        ["Memo:",             data["memo"], "", ""],
    ], colWidths=[1.1*inch, 2.35*inch, 0.9*inch, 2.55*inch])
    pay.setStyle(TableStyle([
        ("FONT",    (0,0), (-1,-1), "Helvetica",      8.5),
        ("FONT",    (0,0), (0,-1),  "Helvetica-Bold", 8.5),
        ("FONT",    (2,0), (2,-1),  "Helvetica-Bold", 8.5),
        ("TEXTCOLOR", (0,0), (-1,-1), BLACK),
        ("TOPPADDING",    (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("LEFTPADDING",   (0,0), (-1,-1), 0),
    ]))
    story.append(pay)
    story.append(Spacer(1, 0.1*inch))
    story.append(_rule())
    story.append(Spacer(1, 0.08*inch))

    # ── SIGNATURES ────────────────────────────────────────────────────────────
    story.append(_p(
        "By signing below, I confirm I have reviewed and agree to this distribution.",
        fontSize=8, fontName="Helvetica-Oblique", textColor=GRAY, leading=11,
        spaceAfter=8,
    ))

    sig = Table([
        ["Client Signature: _______________________________",
         "Date: _______________"],
        ["Attorney Signature: _____________________________",
         "Date: _______________"],
    ], colWidths=[4.5*inch, 2.4*inch])
    sig.setStyle(TableStyle([
        ("FONT",          (0,0), (-1,-1), "Helvetica", 8.5),
        ("TEXTCOLOR",     (0,0), (-1,-1), BLACK),
        ("TOPPADDING",    (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("LEFTPADDING",   (0,0), (-1,-1), 0),
    ]))
    story.append(sig)
    story.append(Spacer(1, 0.1*inch))
    story.append(_rule())
    story.append(Spacer(1, 0.04*inch))

    # ── FOOTER ────────────────────────────────────────────────────────────────
    story.append(_p(
        f'Case: {data["case_id"]}  |  {data["statement_date"]}  |  '
        'Confidential – Attorney-Client Privileged',
        fontSize=7, fontName="Helvetica", textColor=GRAY,
        alignment=TA_CENTER, leading=10,
    ))

    doc.build(story)
    return output_path
