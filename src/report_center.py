"""
report_center.py
================
One place to export EVERYTHING the system knows, for a chosen period:

    collect(start, end, sections, role)  -> {section: DataFrame}  (+ "_summary" dict)
    excel(data, meta)                    -> .xlsx bytes, one sheet per section, formatted
    pdf(data, meta)                      -> management summary PDF with charts

Sections (SECTIONS) - an Officer never gets "audit" or "customers" (personal data of all users):
    summary · loans · payments · late · upcoming · requests · decisions · vintage · customers
    support · audit

Every number is read from the same SQLite tables the pages use; nothing is re-typed.
"""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from src import audit, auth, loanbook

SECTIONS = {
    "summary": "Summary - key numbers for the period",
    "loans": "Loans - every loan with the customer's name and contact",
    "payments": "Payments - every payment in the period (KHQR, staff, verified)",
    "late": "Late customers - days late, amount, follow-up, last contact",
    "upcoming": "Upcoming payments - due in the next 30 days",
    "requests": "Customer loan requests - with first and second (four-eyes) approval",
    "decisions": "Scored applications - decisions, routing, policy and model",
    "vintage": "Vintage and roll rates - risk analysis",
    "customers": "Customer accounts - email, sign-in method, linked loans",
    "support": "Customer support and emails sent",
    "audit": "Audit log - every action in the period",
}
RESTRICTED = {"audit", "customers"}           # Risk Manager / Administrator only


def allowed_sections(role: str) -> list[str]:
    return [s for s in SECTIONS if role in ("admin", "risk") or s not in RESTRICTED]


def _conn():
    return loanbook._conn()


def _sql(query: str, params=()) -> pd.DataFrame:
    conn = _conn()
    try:
        return pd.read_sql_query(query, conn, params=params)
    except Exception:                          # a table that does not exist yet = nothing to report
        return pd.DataFrame()
    finally:
        conn.close()


def _in(series: pd.Series, start: date, end: date) -> pd.Series:
    d = pd.to_datetime(series, errors="coerce", utc=True).dt.tz_convert("Asia/Phnom_Penh").dt.date
    return (d >= start) & (d <= end)


def _contacts() -> pd.DataFrame:
    """loan_id -> customer account, name, phone, email (only for loans linked to a portal account)."""
    links = _sql("SELECT l.loan_id, l.username, p.full_name, p.phone, p.email AS profile_email, p.location "
                 "FROM customer_loan_links l LEFT JOIN customer_profiles p ON p.username=l.username")
    if links.empty:
        return pd.DataFrame(columns=["loan_id", "username", "full_name", "phone", "email", "location"])
    users = auth._read_users()
    links["email"] = [users.get(u, {}).get("email") or e or "" for u, e in zip(links["username"], links["profile_email"])]
    return links.drop(columns=["profile_email"])


# =========================================================================================
# COLLECT
# =========================================================================================
def collect(start: date, end: date, sections: list[str], role: str) -> dict:
    from src import notifications, policy_store
    sections = [s for s in sections if s in allowed_sections(role)]
    book = loanbook.portfolio(end)
    contacts = _contacts()
    events = loanbook.all_events()
    out: dict = {}

    if "loans" in sections or "summary" in sections:
        loans = book.copy()
        if len(loans):
            loans = loans.merge(contacts, on="loan_id", how="left")
            keep = ["loan_id", "customer_ref", "full_name", "phone", "email", "location", "username", "product",
                    "principal", "annual_rate", "term_months", "disbursed_on", "first_due_on", "maturity_date",
                    "status", "dpd", "bucket", "stage", "outstanding", "arrears", "paid", "next_due", "next_amount",
                    "remaining_instalments", "band", "area", "employment", "created_by"]
            loans = loans[[c for c in keep if c in loans.columns]]
        out["loans"] = loans

    pays = events[events["kind"].isin(["payment", "settle"])].copy() if len(events) else pd.DataFrame()
    if len(pays):
        pays = pays[pd.to_datetime(pays["event_date"]).dt.date.between(start, end)]
        detail = pays["detail"].astype(str)
        pays["channel"] = ["KHQR online" if r == "customer" else
                           "Verified customer report" if d.startswith("Verified payment report") else
                           "Recorded by staff" for r, d in zip(pays["role"], detail)]
        pays["bakong_hash"] = detail.str.extract(r"Bakong hash (\w+)")[0].fillna("")
        pays = pays.rename(columns={"id": "payment_id", "username": "recorded_by"})
        pays = pays.merge(contacts[["loan_id", "full_name", "username"]], on="loan_id", how="left")
        pays = pays[["payment_id", "event_date", "loan_id", "full_name", "username", "kind", "amount", "channel",
                     "bakong_hash", "recorded_by", "detail"]]
    if "payments" in sections or "summary" in sections:
        out["payments"] = pays if len(pays) else pd.DataFrame(columns=["payment_id", "event_date", "loan_id", "amount"])

    late = notifications.overdue(book, end) if len(book) else pd.DataFrame()
    if len(late):
        try:
            from views.loan_book import follow_up_tags
            tags = follow_up_tags(late)
        except Exception:
            tags = {}
        late = late.copy()
        late["follow_up"] = late["loan_id"].map(tags).fillna("")
        last_note = (events[events["kind"].isin(["note", "promise"])].sort_values("id").groupby("loan_id").last()
                     if len(events) else pd.DataFrame())
        if len(last_note):
            late["last_contact"] = late["loan_id"].map(last_note["event_date"]).fillna("")
            late["last_contact_note"] = late["loan_id"].map(last_note["detail"]).fillna("")
        late = late.merge(contacts[["loan_id", "full_name", "phone", "email"]], on="loan_id", how="left")
    if "late" in sections or "summary" in sections:
        out["late"] = late

    if "upcoming" in sections and len(book):
        up = loanbook.upcoming_dues(book, end, 30)
        out["upcoming"] = up.merge(contacts[["loan_id", "full_name", "phone"]], on="loan_id", how="left") if len(up) else up

    if "requests" in sections or "summary" in sections:
        req = _sql("SELECT r.request_id, r.submitted_at, r.username, p.full_name, p.phone, r.product, r.amount, "
                   "r.term_months, r.purpose, r.status, r.reviewed_by AS first_approver, r.decision_at, "
                   "r.approved_amount, r.approved_rate, r.approved_term, s.approver AS second_approver, "
                   "s.approved_at AS second_approved_at, l.loan_id AS issued_loan, c.cancelled_at "
                   "FROM customer_requests r LEFT JOIN customer_profiles p ON p.username=r.username "
                   "LEFT JOIN customer_request_second_approvals s ON s.request_id=r.request_id "
                   "LEFT JOIN customer_loan_links l ON l.request_id=r.request_id "
                   "LEFT JOIN customer_request_cancellations c ON c.request_id=r.request_id")
        if len(req):
            req.loc[req["cancelled_at"].notna(), "status"] = "Cancelled"
            req = req[_in(req["submitted_at"], start, end)]
        out["requests"] = req

    if "decisions" in sections:
        try:
            from src import workflow
            dec = workflow.decisions(100000)
            out["decisions"] = dec[_in(dec["created_at"], start, end)] if len(dec) else dec
        except Exception:
            out["decisions"] = pd.DataFrame()

    if "vintage" in sections:
        out["vintage"] = loanbook.vintage_table(end)
        out["roll_rates"] = loanbook.roll_rates(end).reset_index()

    if "customers" in sections:
        links = contacts.groupby("username")["loan_id"].apply(lambda s: ", ".join(s)) if len(contacts) else {}
        rows = [{**u, "linked_loans": links.get(u["username"], "") if len(contacts) else ""}
                for u in auth.list_users() if u["role"] == "customer"]
        out["customers"] = pd.DataFrame(rows)

    if "support" in sections:
        t = _sql("SELECT t.ticket_id, t.created_at, t.username, t.subject, t.loan_id, t.status, "
                 "COUNT(m.id) AS messages, MAX(m.sent_at) AS last_message FROM customer_support_tickets t "
                 "LEFT JOIN customer_support_messages m ON m.ticket_id=t.ticket_id GROUP BY t.ticket_id")
        out["support"] = t[_in(t["created_at"], start, end)] if len(t) else t
        e = _sql("SELECT sent_at, username, email, subject, key FROM customer_email_log ORDER BY sent_at")
        out["emails"] = e[_in(e["sent_at"], start, end)] if len(e) else e

    if "audit" in sections:
        a = audit.fetch_events(1_000_000)
        out["audit"] = a[_in(a["ts"], start, end)] if len(a) else a

    if "summary" in sections:
        settings = policy_store.active().settings
        s = loanbook.portfolio_summary(book, settings) if len(book) else {
            "loans": 0, "outstanding": 0.0, "npl_ratio": 0.0, "provision": 0.0, "coverage": 0.0, "stage": {1: 0, 2: 0, 3: 0}}
        p = out.get("payments", pd.DataFrame())
        r = out.get("requests", pd.DataFrame())
        new_loans = book[pd.to_datetime(book["disbursed_on"]).dt.date.between(start, end)] if len(book) else book
        out["_summary"] = {
            "Active loans": s["loans"], "Outstanding principal ($)": round(s["outstanding"], 2),
            "NPL ratio (90+ days)": f"{s['npl_ratio']:.2%}", "Illustrative expected loss ($)": round(s["provision"], 2),
            "Coverage of outstanding": f"{s['coverage']:.2%}",
            "Customers late (now)": int(late["loan_id"].nunique()) if len(late) else 0,
            "Overdue amount (now) ($)": round(float(late["arrears"].sum()), 2) if len(late) else 0.0,
            "New loans issued in period": int(len(new_loans)),
            "Money lent in period ($)": round(float(new_loans["principal"].sum()), 2) if len(new_loans) else 0.0,
            "Payments received in period": int(len(p)),
            "Money received in period ($)": round(float(p["amount"].sum()), 2) if len(p) and "amount" in p else 0.0,
            "...of which KHQR online ($)": round(float(p.loc[p.get("channel", pd.Series(dtype=str)) == "KHQR online",
                                                            "amount"].sum()), 2) if len(p) and "channel" in p else 0.0,
            "Customer requests in period": int(len(r)),
            "...approved / declined / pending": (f"{int((r['status'] == 'Approved').sum())} / "
                                                 f"{int((r['status'] == 'Declined').sum())} / "
                                                 f"{int((r['status'] == 'Pending review').sum())}") if len(r) else "0 / 0 / 0",
            "Stage 1 / 2 / 3 outstanding ($)": " / ".join(f"{s['stage'][k]:,.0f}" for k in (1, 2, 3)),
        }
        try:
            from src import workflow
            d = workflow.decisions(2000)
            pending = 0 if d.empty else int((d["status"] == "Pending second approval").sum())
        except Exception:
            pending = 0
        out["_alerts"] = loanbook.alerts(book, settings, pending) if len(book) else []
        for k in [k for k in ("loans", "payments", "late", "requests") if k not in sections]:
            out.pop(k, None)
    return out


# =========================================================================================
# EXCEL
# =========================================================================================
SHEET_NAMES = {"loans": "Loans", "payments": "Payments", "late": "Late customers", "upcoming": "Upcoming dues",
               "requests": "Customer requests", "decisions": "Decisions", "vintage": "Vintage",
               "roll_rates": "Roll rates", "customers": "Customers", "support": "Support", "emails": "Emails sent",
               "audit": "Audit log"}


def excel(data: dict, meta: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    teal, light = PatternFill("solid", fgColor="0B6B62"), PatternFill("solid", fgColor="E4F1EF")
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Credit Desk - full report"])
    ws["A1"].font = Font(bold=True, size=16, color="0B6B62")
    for k, v in [("Period", f"{meta['start']:%d/%m/%Y} - {meta['end']:%d/%m/%Y}"), ("Prepared by", meta["by"]),
                 ("Generated", meta["generated"]), ("Sections", ", ".join(meta["sections"]))]:
        ws.append([k, v])
    ws.append([])
    if "_summary" in data:
        ws.append(["Key numbers", ""])
        ws.cell(ws.max_row, 1).font = Font(bold=True, color="FFFFFF")
        ws.cell(ws.max_row, 1).fill = teal
        ws.cell(ws.max_row, 2).fill = teal
        for k, v in data["_summary"].items():
            ws.append([k, v])
        ws.append([])
        ws.append(["Alerts", ""])
        ws.cell(ws.max_row, 1).font = Font(bold=True)
        for tone, msg in data.get("_alerts", []) or [("", "none")]:
            ws.append([tone.upper(), msg])
    ws.append([])
    ws.append(["Note", "Expected loss uses assumed default probabilities and LGD - illustrative, not regulatory."])
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 70
    for key, title in SHEET_NAMES.items():
        df = data.get(key)
        if df is None:
            continue
        sh = wb.create_sheet(title[:31])
        df = df.copy()
        for c in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[c]):
                df[c] = df[c].astype(str)
        cols = [str(c) for c in df.columns] or ["(no rows in this period)"]
        sh.append([c.replace("_", " ").capitalize() for c in cols])
        for cell in sh[1]:
            cell.font, cell.fill = Font(bold=True, color="FFFFFF"), teal
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        for i, row in enumerate(df.itertuples(index=False), start=2):
            sh.append([None if (isinstance(v, float) and pd.isna(v)) else (str(v) if not isinstance(v, (int, float, str))
                                                                         else v) for v in row])
            if i % 2 == 0:
                for cell in sh[i]:
                    cell.fill = light
        for j, c in enumerate(cols, start=1):
            width = max([len(c)] + [len(str(v)) for v in df.iloc[:200, j - 1]] if len(df) else [len(c)])
            sh.column_dimensions[get_column_letter(j)].width = min(48, max(10, width + 2))
        sh.freeze_panes = "A2"
        if len(df):
            sh.auto_filter.ref = sh.dimensions
        if not len(df):
            sh.append(["(no rows in this period)"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# =========================================================================================
# PDF (management summary with charts)
# =========================================================================================
def _chart(fig) -> io.BytesIO:
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def pdf(data: dict, meta: dict) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, Spacer
    from src.reports import _doc, _latin, _styles, _table
    st = _styles()
    teal = "#0B6B62"
    out = [Paragraph("Credit Desk - management report", st["h1"]),
           Paragraph(_latin(f"Period {meta['start']:%d/%m/%Y} - {meta['end']:%d/%m/%Y} · prepared by {meta['by']} · "
                            f"{meta['generated']}"), st["small"]), Spacer(1, 6)]
    if "_summary" in data:
        out += [Paragraph("Key numbers", st["h2"]),
                _table([["Measure", "Value"]] + [[k, f"{v:,.2f}" if isinstance(v, float) else str(v)]
                                                  for k, v in data["_summary"].items()], widths=[95 * mm, 75 * mm])]
        al = data.get("_alerts") or []
        if al:
            out += [Paragraph("Alerts", st["h2"])] + [Paragraph(_latin(f"- {t.upper()}: {m}"), st["p"]) for t, m in al]
    p = data.get("payments")
    if p is not None and len(p) and "amount" in p:
        freq, word = ("W", "week") if (meta["end"] - meta["start"]).days <= 120 else ("MS", "month")
        s = p.assign(d=pd.to_datetime(p["event_date"])).groupby(pd.Grouper(key="d", freq=freq))["amount"].sum()
        fig, ax = plt.subplots(figsize=(7.2, 2.6))
        ax.bar(s.index, s.values, width=5 if freq == "W" else 20, color=teal)
        ax.set_title(f"Money received per {word} ($)", fontsize=10, loc="left")
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(labelsize=7)
        out += [Spacer(1, 6), Image(_chart(fig), width=170 * mm, height=60 * mm)]
        if "channel" in p:
            by = p.groupby("channel")["amount"].sum()
            out += [_table([["Channel", "Amount ($)"]] + [[k, f"{v:,.2f}"] for k, v in by.items()],
                           widths=[95 * mm, 75 * mm])]
    loans = data.get("loans")
    if loans is not None and len(loans) and "bucket" in loans:
        act = loans[loans["status"] == "Active"]
        if len(act):
            by = act.groupby("bucket")["outstanding"].sum()
            order = [b for b in ["Current", "1-29", "30-59", "60-89", "90+"] if b in by.index] + \
                    [b for b in by.index if b not in ["Current", "1-29", "30-59", "60-89", "90+"]]
            by = by.reindex(order)
            tone = {"Current": "#16794C", "1-29": "#E9A23B", "30-59": "#D9622B", "60-89": "#B42318", "90+": "#7A1A12"}
            fig, ax = plt.subplots(figsize=(7.2, 2.6))
            ax.barh(by.index.astype(str)[::-1], by.values[::-1], color=[tone.get(b, "#888") for b in by.index[::-1]])
            ax.xaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("${x:,.0f}"))
            ax.set_title("Outstanding by days late ($)", fontsize=10, loc="left")
            ax.spines[["top", "right"]].set_visible(False)
            ax.tick_params(labelsize=7)
            out += [Spacer(1, 6), Image(_chart(fig), width=170 * mm, height=60 * mm)]
    late = data.get("late")
    if late is not None and len(late):
        top = late.sort_values("arrears", ascending=False).head(10)
        out += [Spacer(1, 8), Paragraph("Top 10 late customers", st["h2"]),
                _table([["Loan", "Customer", "Days late", "Overdue $", "Follow-up"]] +
                       [[r.loan_id, str(getattr(r, "full_name", "") or r.customer_ref), str(r.dpd), f"{r.arrears:,.2f}",
                         str(getattr(r, "follow_up", ""))] for r in top.itertuples()],
                       widths=[38 * mm, 45 * mm, 20 * mm, 27 * mm, 40 * mm])]
    req = data.get("requests")
    if req is not None and len(req):
        out += [Paragraph("Customer loan requests", st["h2"]),
                _table([["Status", "Requests", "Amount $"]] +
                       [[k, str(len(g)), f"{g['amount'].sum():,.2f}"] for k, g in req.groupby("status")],
                       widths=[70 * mm, 40 * mm, 60 * mm])]
    out += [Spacer(1, 10), Paragraph(_latin("Full detail (every loan, payment, request and the audit log) is in the "
                                             "Excel version of this report. Expected loss is illustrative."), st["small"])]
    buf = io.BytesIO()
    _doc(buf).build(out)
    return buf.getvalue()


def meta_for(start: date, end: date, sections: list[str], user) -> dict:
    return {"start": start, "end": end, "sections": [SECTIONS[s].split(" - ")[0] for s in sections],
            "by": f"{user.display_name} ({user.role_label})",
            "generated": datetime.now(timezone(timedelta(hours=7))).strftime("%d/%m/%Y %H:%M") + " (Phnom Penh)"}
