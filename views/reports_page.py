"""Reports - one page to download everything Credit Desk knows, for any period, as Excel and/or PDF."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from src import audit, auth, report_center as rc, ui
from src.data_pipeline import today_local

PERIODS = ["Today", "This month", "Last month", "This quarter", "This year", "Everything", "Choose dates"]


def period_dates(choice: str, today: date) -> tuple[date, date]:
    if choice == "Today":
        return today, today
    if choice == "This month":
        return today.replace(day=1), today
    if choice == "Last month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if choice == "This quarter":
        return date(today.year, 3 * ((today.month - 1) // 3) + 1, 1), today
    if choice == "This year":
        return date(today.year, 1, 1), today
    return date(2000, 1, 1), today                      # Everything


def render() -> None:
    user = auth.current_user()
    ui.page_header(
        "Reports",
        "Download one report with everything in the system for the period you choose: loans, customers, payments "
        "(KHQR and staff), late customers, upcoming payments, loan requests with four-eyes approvals, scored "
        "applications, risk analysis, support and the audit log. Excel has every row; the PDF is a short "
        "management summary with charts.",
        eyebrow="Portfolio")
    today = today_local().date()

    c1, c2 = st.columns([1, 2])
    choice = c1.selectbox("Period", PERIODS, index=1, key="rep_period")
    if choice == "Choose dates":
        picked = c2.date_input("From - to", value=(today.replace(day=1), today), max_value=today,
                               format="DD/MM/YYYY", key="rep_dates")
        start, end = (picked if isinstance(picked, (tuple, list)) and len(picked) == 2 else (today, today))
    else:
        start, end = period_dates(choice, today)
        c2.markdown(f"<div style='padding-top:2rem'>📅 <b>{start:%d/%m/%Y}</b> → <b>{end:%d/%m/%Y}</b></div>",
                    unsafe_allow_html=True)

    allowed = rc.allowed_sections(user.role)
    st.markdown("**What to include**")
    all_on = st.checkbox("Select all", value=True, key="rep_all")
    cols = st.columns(2)
    chosen = []
    for i, s in enumerate(allowed):
        title, _, hint = rc.SECTIONS[s].partition(" - ")
        if cols[i % 2].checkbox(title, value=all_on, help=hint, key=f"rep_sec_{s}_{all_on}"):
            chosen.append(s)
    if len(allowed) < len(rc.SECTIONS):
        st.caption("🔒 Customer accounts and the audit log are only for the Risk Manager and the Administrator.")

    fmt = st.radio("Format", ["Excel + PDF", "Excel only", "PDF only"], horizontal=True, key="rep_fmt")
    if st.button("📊 Build the report", type="primary", disabled=not chosen, key="rep_build"):
        with st.spinner("Collecting every record and building the files…"):
            data = rc.collect(start, end, chosen, user.role)
            meta = rc.meta_for(start, end, chosen, user)
            files = {}
            if fmt != "PDF only":
                files["xlsx"] = rc.excel(data, meta)
            if fmt != "Excel only":
                try:
                    files["pdf"] = rc.pdf(data, meta)
                except Exception as exc:                      # e.g. reportlab / matplotlib missing
                    st.warning(f"The PDF could not be built ({exc}). The Excel file has everything.")
        st.session_state["rep_result"] = {"files": files, "summary": data.get("_summary"),
                                          "counts": {k: len(v) for k, v in data.items()
                                                     if not k.startswith("_") and hasattr(v, "__len__")},
                                          "name": f"credit_desk_report_{start:%Y%m%d}_{end:%Y%m%d}"}
        audit.log_event(user.username, user.role, "report_export",
                        f"Full report {start:%Y-%m-%d}..{end:%Y-%m-%d}: {', '.join(chosen)} ({fmt})", strict=False)

    res = st.session_state.get("rep_result")
    if not res:
        return
    st.success("✅ The report is ready.")
    d1, d2 = st.columns(2)
    if "xlsx" in res["files"]:
        d1.download_button("⬇️ Download Excel (every sheet)", res["files"]["xlsx"], f"{res['name']}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True, key="rep_dl_xlsx")
    if "pdf" in res["files"]:
        d2.download_button("⬇️ Download PDF (summary)", res["files"]["pdf"], f"{res['name']}.pdf", "application/pdf",
                           use_container_width=True, key="rep_dl_pdf")
    if res.get("summary"):
        with st.expander("Key numbers in this report", expanded=True):
            st.table({"Measure": list(res["summary"]), "Value": [str(v) for v in res["summary"].values()]})
    st.caption("Rows per sheet: " + " · ".join(f"{rc.SHEET_NAMES.get(k, k)} {n}" for k, n in res["counts"].items()))
