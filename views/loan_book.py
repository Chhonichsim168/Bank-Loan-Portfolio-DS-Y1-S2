"""Loan book - disbursed loans, repayments, arrears, stress tests, limits and exports.
Everything is stored and computed on this computer."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from src import audit, auth, loanbook, policy_store, reports, risk_economics as econ, ui, workflow
from src.data_pipeline import today_local
from src.deps import MissingLibrary
from src.security import to_safe_csv
from views._docs import render_documents


def _book(asof: date) -> pd.DataFrame:
    return loanbook.portfolio(asof)


def render() -> None:
    user = auth.current_user()
    settings = policy_store.active().settings
    ui.page_header(
        "Loan book",
        "Loans after approval: repayment schedule, payments, days past due, stages, collections notes, "
        "restructures and write-offs. All figures are calculated on this computer from the saved records.",
        eyebrow="Portfolio")

    today = today_local().date()          # Phnom Penh date, not the server's
    asof = st.date_input("Report as of", value=today, max_value=today, key="lb_asof", format="DD/MM/YYYY")
    book = _book(asof)

    tabs = st.tabs(["Overview", "Loans", "Add a loan", "Stress and limits", "Reports"])
    with tabs[0]:
        _overview(book, settings, asof)
    with tabs[1]:
        _loans(book, user, asof)
    with tabs[2]:
        _add(user, settings)
    with tabs[3]:
        _stress(book, settings)
    with tabs[4]:
        _reports(book, settings, asof)


def _pending_reviews() -> int:
    d = workflow.decisions(2000)
    return 0 if d.empty else int((d["status"] == "Pending second approval").sum())


def _overview(book: pd.DataFrame, settings, asof: date) -> None:
    if book.empty:
        ui.note("No loans yet. Add one in the Add a loan tab, starting from an approved decision.",
                title="Loan book is empty")
        return
    s = loanbook.portfolio_summary(book, settings)
    c = st.columns(4, gap="small")
    with c[0]:
        ui.kpi("Active loans", f"{s['loans']:,}")
    with c[1]:
        ui.kpi("Outstanding", ui.money(s["outstanding"]))
    with c[2]:
        ui.kpi("NPL ratio (90+ days)", f"{s['npl_ratio']:.1%}", foot=f"limit {settings.max_npl_ratio:.1%}")
    with c[3]:
        ui.kpi("Illustrative expected loss", ui.money(s["provision"]), foot=f"{s['coverage']:.1%} of outstanding")

    for tone, msg in loanbook.alerts(book, settings, _pending_reviews()):
        ui.note(msg, title="Limit alert", tone="warn" if tone == "warn" else "stop")

    _upcoming(book, asof)

    act = book[book["status"] == "Active"]
    a, b = st.columns(2, gap="medium")
    with a:
        ui.section("Outstanding by delinquency bucket")
        by = act.groupby("bucket")["outstanding"].sum().reindex(loanbook.BUCKETS).fillna(0).reset_index()
        ui.chart(px.bar(by, x="bucket", y="outstanding"), 300)
    with b:
        ui.section("Outstanding by stage")
        st_df = pd.DataFrame({"stage": ["Stage 1", "Stage 2", "Stage 3"],
                              "outstanding": [s["stage"][1], s["stage"][2], s["stage"][3]]})
        ui.chart(px.bar(st_df, x="stage", y="outstanding"), 300)

    ui.section("Vintage - share of each month's loans that were ever late",
               "Compares groups of loans by the month they were disbursed.")
    v = loanbook.vintage_table(asof)
    ui.table(v.style.format({"principal": "{:,.0f}", "ever_30plus": "{:.1%}", "ever_90plus": "{:.1%}"}) if len(v) else v,
             hide_index=True)
    ui.section("Roll rates - where last month's buckets are now")
    ui.table(loanbook.roll_rates(asof).style.format("{:.0%}"))

    obs = econ.observed_default_rates(loanbook.outcomes(asof))
    ui.section("Assumed vs observed default rate",
               "Your assumed default probabilities next to what actually happened to seasoned loans.")
    if obs.empty:
        st.caption("Not enough seasoned loans from scored applications yet.")
    else:
        obs["assumed"] = [econ.band_pd(b, settings) for b in obs["band"]]
        ui.table(obs.style.format({"observed_default_rate": "{:.1%}", "assumed": "{:.1%}"}), hide_index=True)


def _upcoming(book: pd.DataFrame, asof: date) -> None:
    ui.section("Payments due soon",
               "Loans already in arrears first, then instalments falling due - a call list for collections.")
    window = ui.choice("Window", ["7 days", "14 days", "30 days"], default="7 days", key="lb_due_window")
    days = int(window.split()[0])
    due = loanbook.upcoming_dues(book, asof, days)
    act = book[book["status"] == "Active"]
    c = st.columns(3, gap="small")
    with c[0]:
        ui.kpi("In arrears now", f"{int((act['arrears'] > 0.005).sum()):,}",
               foot=ui.money(float(act["arrears"].sum())) + " overdue")
    with c[1]:
        n = due[due["arrears"] <= 0.005]
        ui.kpi(f"Due in next {days} days", f"{len(n):,}", foot=ui.money(float(n["next_amount"].sum())) + " expected")
    with c[2]:
        mat = act[pd.to_datetime(act["maturity_date"]) <= pd.Timestamp(asof) + pd.DateOffset(months=3)]
        ui.kpi("Maturing within 3 months", f"{len(mat):,}", foot=ui.money(float(mat["outstanding"].sum())) + " outstanding")
    if due.empty:
        st.caption(f"Nothing due in the next {days} days and no loans in arrears.")
    else:
        ui.table(due.style.format({"next_amount": "{:,.2f}", "arrears": "{:,.2f}", "days_until_due": "{:.0f}"},
                                  na_rep="-"), hide_index=True)


def _loans(book: pd.DataFrame, user, asof: date) -> None:
    if book.empty:
        st.caption("No loans yet.")
        return
    view = book[["loan_id", "customer_ref", "product", "principal", "outstanding", "status", "dpd", "bucket",
                 "stage", "arrears", "disbursed_on", "next_due", "next_amount", "maturity_date",
                 "months_on_book", "remaining_instalments"]]
    ui.table(view, hide_index=True)
    lid = st.selectbox("Open a loan", book["loan_id"].tolist(), key="lb_open")
    loan = loanbook.get_loan(lid)
    ev = loanbook.events_for(lid)
    snap = loanbook.snapshot(loan, ev, asof)
    c = st.columns(4, gap="small")
    with c[0]:
        ui.kpi("Outstanding", ui.money(snap["outstanding"]))
    with c[1]:
        ui.kpi("Days past due", str(snap["dpd"]), foot=snap["bucket"])
    with c[2]:
        ui.kpi("Arrears", ui.money(snap["arrears"]))
    with c[3]:
        ui.kpi("Status", snap["status"], foot=f"Stage {snap['stage']}")

    with st.expander("Repayment schedule"):
        ui.table(loanbook.schedule(loan, ev), hide_index=True)
    ui.section("History")
    if ev.empty:
        st.caption("No payments or notes yet.")
    else:
        ui.table(ev[["event_date", "kind", "amount", "username", "detail"]], hide_index=True)

    if snap["status"] == "Active":
        _event_forms(loan, user)
    render_documents(lid, key=f"lb_docs_{lid}")


def _event_forms(loan: dict, user) -> None:
    lid = loan["loan_id"]
    kinds = ["payment", "note", "promise", "settle"] + (["restructure", "writeoff"] if user.role in loanbook.RISK_ROLES else [])
    with st.form(f"lb_ev_{lid}", clear_on_submit=True, border=True):
        kind = st.selectbox("Record", kinds)
        when = st.date_input("Date", value=date.today(), max_value=date.today() + timedelta(days=365))
        amount = st.number_input("Amount (payments)", 0.0, 1e12, 0.0, step=100.0)
        note = st.text_area("Note (required for notes, promises, restructures, write-offs)")
        st.caption("Restructure only: new term, new rate and first due date.")
        r1, r2, r3 = st.columns(3)
        nt = r1.number_input("New term (months)", 1, 480, 12)
        nr = r2.number_input("New rate % p.a.", 0.0, 60.0, 8.5, step=0.1)
        fd = r3.date_input("New first due", value=date.today() + timedelta(days=30))
        go = st.form_submit_button("Save record", type="primary")
    if go:
        payload = {"new_term_months": int(nt), "new_annual_rate": nr / 100, "first_due_on": fd} if kind == "restructure" else None
        try:
            loanbook.add_event(lid, username=user.username, role=user.role, kind=kind, event_date=when,
                               amount=amount, detail=note, payload=payload)
            st.success("Saved.")
            st.rerun()
        except (ValueError, PermissionError, audit.AuditError) as exc:
            st.error(str(exc))


def _add(user, settings) -> None:
    elig = loanbook.eligible_decisions()
    ui.section("Create a loan", "Choose an approved, final decision to copy its details, or enter a loan without one.")
    src = None
    if len(elig):
        labels = ["(no linked application)"] + [f"{r.application_id} - {r.customer_ref} - {r.loan_amount:,.0f}" for r in elig.itertuples()]
        pick = st.selectbox("Approved decision", labels, key="lb_pick")
        if pick != labels[0]:
            src = elig.iloc[labels.index(pick) - 1]
    with st.form("lb_new", border=True):
        ref = st.text_input("Customer reference", value="" if src is None else str(src["customer_ref"]))
        prod = st.selectbox("Product", loanbook.PRODUCTS)
        c = st.columns(3)
        principal = c[0].number_input("Principal", 1.0, 1e12, float(src["loan_amount"]) if src is not None else 10000.0, step=500.0)
        rate = c[1].number_input("Rate % p.a.", 0.0, 60.0, round(settings.base_rate * 100, 2), step=0.1)
        term = c[2].number_input("Term (months)", 1, 480, 36)
        d = st.columns(3)
        disb = d[0].date_input("Disbursed on", value=date.today(), max_value=date.today())
        first = d[1].date_input("First due", value=date.today() + timedelta(days=30))
        coll = d[2].number_input("Collateral value", 0.0, 1e12, 0.0, step=500.0)
        e = st.columns(3)
        band = e[0].selectbox("Routing band", econ.BANDS, index=econ.BANDS.index(src["routing"]) if src is not None and src["routing"] in econ.BANDS else 0)
        area = e[1].text_input("Area / province")
        emp = e[2].text_input("Employment")
        go = st.form_submit_button("Create loan", type="primary")
    if go:
        try:
            lid = loanbook.create_loan(username=user.username, role=user.role, customer_ref=ref, product=prod,
                                       principal=principal, annual_rate=rate / 100, term_months=int(term),
                                       disbursed_on=disb, first_due_on=first, collateral_value=coll, band=band,
                                       application_id=None if src is None else str(src["application_id"]),
                                       area=area.strip().lower(), employment=emp.strip())
            st.success(f"Created {lid}.")
            st.rerun()
        except (ValueError, audit.AuditError) as exc:
            st.error(str(exc))


def _stress(book: pd.DataFrame, settings) -> None:
    ui.section("Stress test", "What happens to expected loss if defaults rise and collateral loses value. "
                              "Scenarios are yours to choose; they are not forecasts.")
    if book.empty:
        st.caption("No loans yet.")
        return
    a, b = st.columns(2)
    mult = a.slider("Default probability multiplier", 1.0, 5.0, 2.0, 0.25)
    shock = b.slider("Extra collateral haircut", 0, 50, 20, 5) / 100
    base = loanbook.portfolio_summary(book, settings)
    stressed = loanbook.portfolio_summary(book, settings, mult, shock)
    ui.table(pd.DataFrame({"Measure": ["Expected loss", "Coverage of outstanding"],
                           "Base": [f"{base['provision']:,.0f}", f"{base['coverage']:.2%}"],
                           "Stressed": [f"{stressed['provision']:,.0f}", f"{stressed['coverage']:.2%}"]}), hide_index=True)
    conc = loanbook.concentration(book)
    ui.section("Concentration")
    c1, c2 = st.columns(2)
    c1.dataframe(conc["by_area"].rename("share").map("{:.1%}".format))
    c2.dataframe(conc["by_product"].rename("share").map("{:.1%}".format))
    st.caption(f"Limits are set on the Policy page. Largest single loan: {conc['largest_share']:.1%} of the book.")


def _reports(book: pd.DataFrame, settings, asof: date) -> None:
    if book.empty:
        st.caption("Nothing to export yet.")
        return
    s = loanbook.portfolio_summary(book, settings)
    al = loanbook.alerts(book, settings, _pending_reviews())
    if reports.HAVE_XLSX:
        xlsx = reports.portfolio_workbook(s, book, loanbook.vintage_table(asof), loanbook.roll_rates(asof), al,
                                          workflow.decisions(5000), asof)
        st.download_button("Download Excel report", xlsx, file_name=f"loan_book_{asof}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        ui.note(str(MissingLibrary("openpyxl")), title="Excel report unavailable", tone="warn")
    st.download_button("Download loans (CSV)", to_safe_csv(book), file_name=f"loans_{asof}.csv", mime="text/csv")
