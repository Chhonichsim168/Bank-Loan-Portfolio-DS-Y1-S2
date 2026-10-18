"""
reports.py
==========
Credit Desk - Excel and PDF exports, built on this computer.

* ``portfolio_workbook``  - the loan book and its risk views as an .xlsx workbook.
* ``decision_pdf``        - a one-to-two page decision record for the credit file.
* ``customer_letter_pdf`` - the decline / approval letter to the customer.

PDFs use the built-in Helvetica font, which has no Khmer glyphs: any non-Latin character is replaced
with "?" in the PDF (the on-screen app and the Markdown record keep the original text). Every text
cell in the workbook is formula-neutralised before it is written.
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone

import pandas as pd
# Optional libraries: a missing one disables only its own export, never the page (src/deps.py).
try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    HAVE_XLSX = True
except ImportError:
    HAVE_XLSX = False
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    HAVE_PDF = True
except ImportError:
    HAVE_PDF = False

from src.deps import MissingLibrary

from src.security import csv_safe


def _latin(text) -> str:
    s = "" if text is None else str(text)
    s = s.encode("latin-1", "replace").decode("latin-1")
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ----------------------------------------------------------------------------- Excel
def _sheet(wb: Workbook, name: str, df: pd.DataFrame) -> None:
    ws = wb.create_sheet(name[:31])
    df = csv_safe(df.copy()) if len(df.columns) else df
    ws.append([str(c) for c in df.columns])
    for row in df.itertuples(index=False):
        ws.append([(None if (isinstance(v, float) and pd.isna(v)) else (v.isoformat() if hasattr(v, "isoformat") else v))
                   for v in row])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="0B6B62")
        c.alignment = Alignment(vertical="center")
    for i, col in enumerate(df.columns, 1):
        width = max([len(str(col))] + [len(str(v)) for v in df[col].head(200)]) if len(df) else len(str(col))
        ws.column_dimensions[get_column_letter(i)].width = min(48, max(10, width + 2))
    ws.freeze_panes = "A2"


def portfolio_workbook(summary: dict, loans: pd.DataFrame, vintage: pd.DataFrame, roll: pd.DataFrame,
                       alerts: list[tuple[str, str]], decisions: pd.DataFrame, asof) -> bytes:
    if not HAVE_XLSX:
        raise MissingLibrary("openpyxl")
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    rows = [("Credit Desk - portfolio report", ""), ("As of", str(asof)),
            ("Generated (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")), ("", ""),
            ("Active loans", summary["loans"]), ("Outstanding principal", round(summary["outstanding"], 2)),
            ("NPL ratio (90+ days)", round(summary["npl_ratio"], 4)),
            ("Illustrative expected loss", round(summary["provision"], 2)),
            ("Coverage of outstanding", round(summary["coverage"], 4)),
            ("Stage 1 outstanding", round(summary["stage"][1], 2)), ("Stage 2 outstanding", round(summary["stage"][2], 2)),
            ("Stage 3 outstanding", round(summary["stage"][3], 2)), ("", ""), ("Alerts", "")]
    rows += [(tone.upper(), msg) for tone, msg in alerts] or [("", "none")]
    rows += [("", ""), ("Note", "Expected loss uses assumed default probabilities and an assumed LGD; it is not a regulatory provision.")]
    for r in rows:
        ws.append(list(r))
    ws["A1"].font = Font(bold=True, size=14)
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 80
    keep = [c for c in ["loan_id", "customer_ref", "product", "principal", "annual_rate", "term_months", "disbursed_on",
                        "band", "area", "status", "dpd", "bucket", "stage", "outstanding", "arrears", "next_due",
                        "next_amount"] if c in loans.columns]
    _sheet(wb, "Loans", loans[keep] if len(loans) else pd.DataFrame(columns=keep))
    _sheet(wb, "Vintage", vintage)
    _sheet(wb, "Roll rates", roll.reset_index())
    if len(decisions):
        _sheet(wb, "Decisions", decisions[[c for c in ["application_id", "created_at", "username", "customer_ref",
                                                        "outcome", "loan_amount", "probability", "routing", "status",
                                                        "policy_version", "model_version"] if c in decisions.columns]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------------- PDF
def _doc(buf) -> SimpleDocTemplate:
    return SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                             bottomMargin=16 * mm, title="Credit Desk")


def _styles():
    s = getSampleStyleSheet()
    return {"h1": ParagraphStyle("h1", parent=s["Heading1"], textColor=colors.HexColor("#0B6B62"), fontSize=17),
            "h2": ParagraphStyle("h2", parent=s["Heading2"], fontSize=12, spaceBefore=8),
            "p": ParagraphStyle("p", parent=s["BodyText"], fontSize=9.5, leading=13),
            "small": ParagraphStyle("small", parent=s["BodyText"], fontSize=8, leading=10, textColor=colors.grey)}


def _table(rows, widths=None):
    t = Table([[Paragraph(_latin(c), _styles()["p"]) for c in r] for r in rows], colWidths=widths, hAlign="LEFT")
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E4F1EF")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def decision_pdf(*, app_id: str, customer_ref: str, officer: str, outcome: str, probability: float, interval,
                 routing: str, policy_version: int, model_version: str, policy_pass: bool, breaches: list[str],
                 inputs: dict, reasons: list, rationale: str, loan_econ: dict | None = None) -> bytes:
    if not HAVE_PDF:
        raise MissingLibrary("reportlab")
    st = _styles()
    buf = io.BytesIO()
    out = [Paragraph("Credit decision record", st["h1"]),
           Paragraph(_latin(f"Application {app_id} - case reference {customer_ref}"), st["p"]), Spacer(1, 4),
           _table([["Officer decision", outcome], ["Officer", officer],
                   ["Model score", f"{probability * 100:.1f}% (90% range {interval[0] * 100:.0f}-{interval[1] * 100:.0f}%)"],
                   ["Routing", routing], ["Hard policy", "pass" if policy_pass else "BREACH: " + "; ".join(breaches)],
                   ["Policy / model version", f"v{policy_version} / {model_version}"],
                   ["Saved (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")]], [50 * mm, 120 * mm]),
           Paragraph("Application", st["h2"]),
           _table([["Field", "Value"]] + [[k.replace("_", " "), v] for k, v in inputs.items()], [70 * mm, 100 * mm])]
    if loan_econ:
        out += [Paragraph("Pricing and expected loss (assumption-based)", st["h2"]),
                _table([["Suggested rate", f"{loan_econ['rate']:.2%}"], ["Monthly instalment", f"{loan_econ['emi']:,.0f}"],
                        ["Assumed PD / LGD", f"{loan_econ['el']['pd']:.1%} / {loan_econ['el']['lgd']:.0%}"],
                        ["Expected loss", f"{loan_econ['el']['el']:,.0f} ({loan_econ['el']['el_pct']:.2%} of the loan)"]],
                       [70 * mm, 100 * mm])]
    out += [Paragraph("Reasons (Shapley attribution of the final score, log-odds)", st["h2"]),
            _table([["Factor", "Detail", "Effect"]] + [[r["label"], r["detail"], f"{r['contribution']:+.2f}"] for r in reasons],
                   [45 * mm, 95 * mm, 30 * mm]),
            Paragraph("Officer rationale", st["h2"]), Paragraph(_latin(rationale or "(not recorded)"), st["p"]),
            Spacer(1, 8),
            Paragraph("The score is decision support trained on this institution's past decisions, not repayment. "
                      "It sees no bureau file, collateral or existing liabilities. The recorded officer decision governs.",
                      st["small"])]
    _doc(buf).build(out)
    return buf.getvalue()


def customer_letter_pdf(*, outcome: str, customer_ref: str, reasons: list[str], bank_name: str = "Your bank",
                        terms: str = "", human_reviewed: bool = False) -> bytes:
    """FIX: "A person reviewed this decision" is printed only when ``human_reviewed`` is True
    (a signed-in officer recorded the decision); it used to be printed on every decline."""
    if not HAVE_PDF:
        raise MissingLibrary("reportlab")
    st = _styles()
    buf = io.BytesIO()
    declined = outcome == "Decline"
    out = [Paragraph(_latin(bank_name), st["h1"]),
           Paragraph(f"Date: {datetime.now(timezone.utc):%d %B %Y}", st["p"]),
           Paragraph(_latin(f"Re: your loan application ({customer_ref})"), st["p"]), Spacer(1, 8)]
    if declined:
        out.append(Paragraph("We are unable to approve your application at this time. The main reasons were:", st["p"]))
        out += [Paragraph(_latin(f"{i}. {r}"), st["p"]) for i, r in enumerate(reasons, 1)] or \
               [Paragraph("1. The combination of factors on your application did not meet our lending criteria.", st["p"])]
        review_line = ("A person reviewed this decision." if human_reviewed else
                       "This decision was produced by an automated system. You may ask for a person to review it.")
        out += [Spacer(1, 6), Paragraph("You may ask us to review this decision, and you may reapply when your "
                                        "circumstances change. " + review_line, st["p"])]
    else:
        out.append(Paragraph("We are pleased to tell you that your application has been approved"
                             + (" subject to the conditions below." if outcome == "Approve with conditions" else "."), st["p"]))
        if terms:
            out += [Spacer(1, 6), Paragraph(_latin(terms), st["p"])]
        out += [Spacer(1, 6), Paragraph("Final terms are set out in your loan agreement.", st["p"])]
    out += [Spacer(1, 18), Paragraph("Yours sincerely,", st["p"]), Paragraph(_latin(bank_name) + " - Credit Department", st["p"])]
    _doc(buf).build(out)
    return buf.getvalue()
