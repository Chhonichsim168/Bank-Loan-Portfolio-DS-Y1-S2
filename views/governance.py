"""Data and governance — lineage, definitions, and the limits of this system."""

from __future__ import annotations

import html as _html

import pandas as pd
import streamlit as st

from src import ui
from src.data_pipeline import to_local, today_local
from src.data_pipeline import (
    ASSUMED_ANNUAL_INTEREST_RATE, LTI_HIGH_THRESHOLD, MAX_CREDIT_SCORE,
    MAX_LATE_PAYMENTS_12M, MIN_CREDIT_SCORE, RISK_DTI_HIGH, RISK_DTI_MID,
    RISK_HIGH_MIN, RISK_LATE_ANY_AT, RISK_LATE_SEVERE_AT, RISK_MAX_POINTS,
    RISK_MEDIUM_MIN, RISK_SCORE_BAD_BELOW, RISK_SCORE_WEAK_BELOW,
)
from src import fairness, monitoring, policy_store, registry, workflow
from src.security import esc, to_safe_csv
from src.state import ctx, fingerprint_of, honest_probabilities, load_raw
from src import auth, audit

DICTIONARY = pd.DataFrame([
    ("application_date", "Source (optional)",
     "Day the application was received, YYYY-MM-DD or DD/MM/YYYY. Not in the future, not before 2000. Used for "
     "period filters, trends and out-of-time validation - never a model input"),
    ("applicant_income", "Source", "Gross monthly income of the primary applicant, USD"),
    ("coapplicant_income", "Source", "Gross monthly income of the co-applicant, 0 if none"),
    ("loan_amount", "Source", "Requested principal, USD"),
    ("loan_term_months", "Source", "Requested repayment term, 12 to 480 months"),
    ("credit_history", "Source", "1 = history on file, 0 = none or adverse"),
    ("dependents", "Source", "Number of financial dependents, 0 to 10"),
    ("employment_status", "Source", "salaried, self_employed or unemployed"),
    ("property_area", "Source", "urban, semiurban or rural"),
    ("credit_score", "Source",
     f"Numeric credit score, {MIN_CREDIT_SCORE} to {MAX_CREDIT_SCORE}. Higher is better"),
    ("late_payments_12m", "Source",
     f"Count of late payments in the last 12 months, 0 to {MAX_LATE_PAYMENTS_12M}. "
     "A count only: no severity, amount or recency"),
    ("approved", "Source", "Outcome. 1 = approved, 0 = declined. The model target"),
    ("total_income", "Derived", "applicant_income + coapplicant_income"),
    ("estimated_emi", "Derived",
     f"Amortising monthly instalment at an assumed {ASSUMED_ANNUAL_INTEREST_RATE:.1%} p.a."),
    ("debt_to_income_ratio", "Derived", "estimated_emi / total_income"),
    ("loan_to_income_ratio", "Derived", "loan_amount / monthly total_income"),
    ("loan_to_annual_income", "Derived",
     "loan_amount / (total_income x 12). The affordability measure policy is written against"),
    ("credit_score_band", "Derived",
     "Credit score banded 0 to 4: below 580, 580-669, 670-739, 740-799, 800 and above"),
    ("late_payment_rate", "Derived", "late_payments_12m / 12, capped at 1"),
    ("credit_payment_stress", "Derived",
     f"(({MAX_CREDIT_SCORE} - credit_score) / 550) + late_payment_rate. "
     "Combines score shortfall and late-payment frequency in one number"),
    ("loan_burden_x_credit", "Derived",
     f"loan_to_annual_income x (({MAX_CREDIT_SCORE} - credit_score) / 550). "
     "A large loan on a weak score counts for more than either alone"),
    ("income_per_dependent", "Derived", "total_income / (dependents + 1)"),
    ("income_bracket", "Derived", "Low / Medium / High tertile of total_income"),
    ("loan_size_category", "Derived", "Small / Medium / Large / Jumbo band of loan_amount"),
    ("household_size", "Derived", "dependents + applicant, plus co-applicant if present"),
    ("risk_level", "Derived", "Low / Medium / High from the additive rule on the Risk scoring rule tab"),
    ("application_month", "Derived", "YYYY-MM of application_date"),
    ("application_quarter", "Derived", "YYYY-Qn of application_date"),
    ("application_year", "Derived", "Calendar year of application_date"),
    ("application_weekday", "Derived", "Day of the week the application was received"),
    ("credit_score_imputed", "Derived", "True if the credit score was missing and filled in; excluded from training"),
    ("late_payments_12m_imputed", "Derived", "True if the late-payment count was missing and filled in; excluded from training"),
    ("credit_history_imputed", "Derived", "True if the credit-history flag was missing and filled in; excluded from training"),
], columns=["Field", "Origin", "Definition"])

N_SOURCE = int((DICTIONARY["Origin"] == "Source").sum())
N_INPUTS = N_SOURCE - 1          # every source field except the approval outcome
SOURCE_COLUMNS = DICTIONARY.loc[DICTIONARY["Origin"] == "Source", "Field"].tolist()


def render() -> None:
    c = ctx()

    ui.page_header(
        "Data and governance",
        "Where the numbers come from, how each derived field is defined, and what this "
        "system does not know.",
        eyebrow="Governance",
    )

    tab_lineage, tab_dict, tab_risk, tab_source, tab_fair, tab_mon, tab_log, tab_bak = st.tabs(
        ["Lineage", "Field definitions", "Risk scoring rule", "Data source", "Fairness screen",
         "Monitoring", "Activity log", "Backup and restore"]
    )
    with tab_lineage:
        _lineage(c)
    with tab_dict:
        _dictionary()
    with tab_risk:
        _risk_rule(c)
    with tab_source:
        _source(c)
    with tab_fair:
        _fairness(c)
    with tab_mon:
        _monitoring(c)
    with tab_log:
        _activity_log()
    with tab_bak:
        _backup()


# -----------------------------------------------------------------------------------------
def _lineage(c) -> None:
    r = c.report
    ui.section("From file to book", "Every row that entered, and every row that did not.")

    cols = st.columns(4, gap="small")
    with cols[0]:
        ui.kpi("Rows received", f"{r.rows_in:,}", foot=c.source_name)
    with cols[1]:
        ui.kpi("Duplicates removed", f"{r.duplicates_dropped:,}",
               foot=f"{r.duplicates_found:,} found")
    with cols[2]:
        ui.kpi("Failed validation", f"{r.invalid_rows_dropped:,}",
               foot="dropped before analysis")
    with cols[3]:
        retained = r.rows_out / r.rows_in if r.rows_in else 0
        ui.kpi("Rows in the book", f"{r.rows_out:,}",
               delta=f"{retained * 100:.1f}% retained",
               delta_dir=ui.delta_dir(retained - 0.95))

    st.markdown("")
    left, right = st.columns([1, 1], gap="large")

    with left:
        ui.section("Validation rules")
        checks = pd.DataFrame([
            ("Applicant income within 0 and 200,000", "applicant_income_out_of_range"),
            ("Co-applicant income not negative", "coapplicant_income_negative"),
            ("Loan amount within 0 and 5,000,000", "loan_amount_out_of_range"),
            ("Term within 12 and 480 months", "loan_term_out_of_range"),
            ("Dependents within 0 and 10", "dependents_out_of_range"),
            ("Credit history is 0 or 1", "credit_history_invalid"),
            (f"Credit score within {MIN_CREDIT_SCORE} and {MAX_CREDIT_SCORE}",
             "credit_score_out_of_range"),
            (f"Late payments (12m) within 0 and {MAX_LATE_PAYMENTS_12M}",
             "late_payments_12m_out_of_range"),
            ("Employment status in the allowed set", "employment_status_invalid"),
            ("Property area in the allowed set", "property_area_invalid"),
            ("Approval outcome is 0 or 1", "approved_invalid"),
        ], columns=["Rule", "_key"])
        checks["Violations"] = checks["_key"].map(
            lambda k: r.invalid_rows_flagged.get(k, 0)
        )
        checks["Result"] = checks["Violations"].map(lambda v: "Pass" if v == 0 else "Fail")
        ui.table(checks[["Rule", "Violations", "Result"]], hide_index=True)

    with right:
        ui.section("Missing values on arrival")
        missing = pd.Series(r.missing_before, name="Missing")
        if missing.sum() == 0:
            ui.note(
                "This extract arrived complete. The imputation logic still runs on every "
                "load — numeric fields to the median, categorical to the mode, rows missing "
                "the outcome dropped — so a future extract with gaps is handled the same way "
                "without a code change. The median is used rather than the mean because "
                "income and loan amounts are right-skewed and the mean would drag every "
                "filled value upward.",
                title="Nothing missing, logic still applies",
            )
        else:
            ui.table(missing.to_frame(), hide_index=False)

        ui.section("Audit trail", "What the pipeline changed on this load, and why.")
        if r.columns_added:
            chips = " ".join(ui.tag(col, ui.BRAND) for col in r.columns_added)
            st.markdown(
                f'<div style="margin-bottom:0.5rem;">{chips}</div>',
                unsafe_allow_html=True,
            )
        if r.notes:
            items = "".join(f"<li>{_html.escape(n)}</li>" for n in r.notes)
            st.markdown(f'<ul class="cd-audit-list">{items}</ul>', unsafe_allow_html=True)
        else:
            ui.note("No notes were logged for this load.")


# -----------------------------------------------------------------------------------------
def _dictionary() -> None:
    ui.section(
        "Field definitions",
        f"{N_SOURCE} source fields ({N_INPUTS} application inputs plus the approval outcome); "
        f"the other {len(DICTIONARY) - N_SOURCE} are derived on load.",
    )
    ui.table(
        DICTIONARY.style.map(
            lambda v: f"color:{ui.BRAND};font-weight:600" if v == "Derived" else "",
            subset=["Origin"],
        ), hide_index=True, height=640,
    )
    st.download_button(
        "Download data dictionary (CSV)",
        to_safe_csv(DICTIONARY),
        file_name="credit_desk_data_dictionary.csv", mime="text/csv",
    )


# -----------------------------------------------------------------------------------------
def _risk_rule(c) -> None:
    ui.section(
        "The risk tier rule",
        f"Additive, scored out of {RISK_MAX_POINTS} points, and entirely inspectable. No tier in "
        "this system comes from a model — a tier an officer cannot justify out loud is not usable.",
    )

    rule = pd.DataFrame([
        ("Credit history is missing or adverse", "credit_history", "+2"),
        (f"Credit score below {RISK_SCORE_BAD_BELOW}", "credit_score", "+2"),
        (f"Credit score {RISK_SCORE_BAD_BELOW} to {RISK_SCORE_WEAK_BELOW - 1}",
         "credit_score", "+1"),
        (f"{RISK_LATE_SEVERE_AT} or more late payments in the last 12 months",
         "late_payments_12m", "+2"),
        (f"{RISK_LATE_ANY_AT} to {RISK_LATE_SEVERE_AT - 1} late payments in the last 12 months",
         "late_payments_12m", "+1"),
        (f"Debt-to-income above {RISK_DTI_HIGH:.0%}", "debt_to_income_ratio", "+2"),
        (f"Debt-to-income between {RISK_DTI_MID:.0%} and {RISK_DTI_HIGH:.0%}",
         "debt_to_income_ratio", "+1"),
        ("Applicant is not currently employed", "employment_status", "+1"),
        (f"Loan above {LTI_HIGH_THRESHOLD}x annual household income",
         "loan_to_annual_income", "+1"),
    ], columns=["Condition", "Field", "Points"])
    tiers = pd.DataFrame([
        (f"{RISK_HIGH_MIN} or more", "High"),
        (f"{RISK_MEDIUM_MIN} to {RISK_HIGH_MIN - 1}", "Medium"),
        (f"0 to {RISK_MEDIUM_MIN - 1}", "Low"),
    ], columns=["Score", "Tier"])

    a, b = st.columns([1.6, 1], gap="large")
    with a:
        ui.table(rule, hide_index=True)
    with b:
        ui.table(tiers, hide_index=True)
        st.caption(
            f"Within each field only the highest band applies. Maximum score: {RISK_MAX_POINTS}."
        )

    dist = (
        c.book.groupby("risk_level", observed=True)
        .agg(applications=("approved", "count"), approval_rate=("approved", "mean"))
        .reindex(["Low", "Medium", "High"]).dropna()
    )
    dist["share"] = dist["applications"] / len(c.book) * 100
    table = pd.DataFrame({
        "Tier": dist.index,
        "Applications": dist["applications"].astype(int),
        "Share of book": dist["share"],
        "Approval rate": dist["approval_rate"] * 100,
    })
    ui.table(
        ui.style_table(table, pct_cols=["Share of book", "Approval rate"]), hide_index=True,
    )

    ui.note(
        "The affordability component is measured against <b>annual</b> income. Income in "
        "this dataset is recorded monthly, so a loan-to-income ratio computed on the raw "
        "column runs around 18x and any threshold set on it in the single digits fires for "
        "almost the whole book — a constant dressed as a rule. Deriving "
        "<code>loan_to_annual_income</code> explicitly and testing against "
        f"{LTI_HIGH_THRESHOLD}x is what makes the tiers separate.",
        title="Why this rule uses annual income", tone="warn",
    )

    overlap = ""
    book = c.book
    if {"credit_history", "credit_score", "late_payments_12m"} <= set(book.columns):
        grp = book.groupby("credit_history")[["credit_score", "late_payments_12m"]].mean()
        if {0, 1} <= set(grp.index):
            overlap = (
                f"Applicants with history on file average a score of {grp.loc[1, 'credit_score']:.0f} "
                f"and {grp.loc[1, 'late_payments_12m']:.1f} late payments; those without average "
                f"{grp.loc[0, 'credit_score']:.0f} and {grp.loc[0, 'late_payments_12m']:.1f}. "
            )
    ui.note(
        "Credit history, credit score and late payments move together in this dataset, so they "
        "are not three independent pieces of evidence. " + overlap +
        f"An applicant with no history, a score below {RISK_SCORE_BAD_BELOW} and "
        f"{RISK_LATE_SEVERE_AT} or more late payments collects 6 points from credit behaviour "
        f"alone — already the {RISK_HIGH_MIN}-point High threshold before income, debt or "
        "employment are looked at. That is deliberate, because a thin or damaged file is the "
        "strongest warning in the data, but it means credit behaviour can outvote everything "
        "else on the form.",
        title="Credit signals reinforce each other",
    )


# -----------------------------------------------------------------------------------------
# -----------------------------------------------------------------------------------------
def _source(c) -> None:
    ui.section("Load a different book",
               f"Point the app at another extract with the same {N_SOURCE} source columns "
               f"({N_INPUTS} application fields plus the approval outcome).")

    user = auth.current_user()
    if user.role != "admin":
        ui.note(
            "Loading a new portfolio extract is restricted to Administrators. Signed in as "
            f"<b>{user.role_label}</b> — you can view the current source below.",
            title="Read-only for this role", tone="warn",
        )
    else:
        up = st.file_uploader("Portfolio extract", type=["csv"], label_visibility="collapsed")
        if up is not None:
            _load_extract(up, user)
        if st.button("Revert to the bundled sample extract"):
            policy_store.use_default_source(user.username, user.role)
            st.rerun()

    st.markdown("")
    ui.section("Current source")
    a, b, d = st.columns(3, gap="small")
    with a:
        ui.kpi("File", c.source_name)
    with b:
        ui.kpi("Applications", f"{len(c.book):,}")
    with d:
        ui.kpi("Fields", f"{c.book.shape[1]}", foot=f"{N_SOURCE} source, the rest derived")

    with st.expander("First rows, as received"):
        ui.table(load_raw(policy_store.active_data_source().path).head(20))

    st.download_button(
        "Download the cleaned book (CSV)",
        to_safe_csv(c.book),
        file_name="credit_desk_clean_book.csv", mime="text/csv",
    )


# -----------------------------------------------------------------------------------------
def _activity_log() -> None:
    ui.section(
        "Activity log",
        "Every sign-in, score, policy change and data-source swap, in the order it "
        "happened. Persisted to disk — it survives a restart and every session ending.",
    )

    ok, n, bad = audit.verify_chain()
    if ok:
        ui.note(f"Hash chain verified: {n:,} records, none altered or removed. Newest hash "
                f"<code>{audit.head_hash()[:24]}...</code> - copy it to a system the database administrator "
                "does not control, on a schedule, to make tampering with the whole chain detectable.",
                title="Audit log integrity", tone="info")
    else:
        ui.note(f"The audit chain is BROKEN at record {bad} after {n:,} valid records. A record was edited "
                "or removed. Treat as a security incident.", title="Audit log integrity", tone="stop")

    events = audit.fetch_events(limit=20000)
    if events.empty:
        ui.note("No activity has been recorded yet in this deployment.")
        return
    day = pd.to_datetime(to_local(events["ts"], "%Y-%m-%d"), errors="coerce")
    lo, hi = day.min().date(), max(day.max().date(), today_local().date())
    a, b = st.columns([1, 1.4], gap="medium")
    with a:
        rng = st.date_input("Between", value=(max(lo, hi - pd.Timedelta(days=30).to_pytimedelta()), hi),
                            min_value=lo, max_value=hi, key="gov_log_range", format="DD/MM/YYYY")
    with b:
        who = st.multiselect("Users", sorted(events["username"].unique()), key="gov_log_users",
                             placeholder="All users")
    if isinstance(rng, (list, tuple)) and len(rng) == 2:
        keep = (day >= pd.Timestamp(rng[0])) & (day <= pd.Timestamp(rng[1]))
        events, day = events[keep.values], day[keep.values]
    if who:
        sel = events["username"].isin(who)
        events, day = events[sel.values], day[sel.values]
    if events.empty:
        st.caption("No activity in that range.")
        return
    per_day = day.dt.date.value_counts().sort_index()
    if len(per_day) > 1:
        st.caption("Events per day")
        st.bar_chart(per_day, height=150)

    ACTION_LABELS = {
        "login": "Signed in", "logout": "Signed out",
        "score_application": "Scored an application", "score_file": "Scored a file",
        "change_policy": "Changed policy", "change_data_source": "Changed data source",
        "login_failed": "Failed sign-in", "login_blocked": "Blocked sign-in", "mfa_failed": "Wrong MFA code",
        "session_timeout": "Session timed out", "password_changed": "Changed password",
        "password_reset": "Password reset", "user_created": "User created", "user_updated": "User changed",
        "mfa_enrolled": "MFA enrolled", "policy_proposed": "Policy proposed", "policy_approved": "Policy approved",
        "policy_rejected": "Policy rejected", "decision_saved": "Decision saved",
        "decision_approved": "Second approval: approved", "decision_rejected": "Second approval: rejected",
        "decision_returned": "Second approval: returned", "bootstrap_admin": "First-run admin created",
    }
    display = pd.DataFrame({
        "When (Phnom Penh)": to_local(events["ts"]).values,
        "User": events["username"],
        "Role": events["role"].map(auth.ROLE_LABELS).fillna(events["role"]),
        "Action": events["action"].map(ACTION_LABELS).fillna(events["action"]),
        "Detail": events["detail"],
    })
    ui.table(display, hide_index=True, height=460)
    st.download_button("Download the activity log (CSV)", to_safe_csv(display), file_name="credit_desk_audit.csv",
                       mime="text/csv")


# -----------------------------------------------------------------------------------------
def _load_extract(up, user) -> None:
    """Validate an uploaded extract in a private, auto-deleted temp folder, then store it under a
    hash-derived name and make it the shared source for every session."""
    import tempfile
    from pathlib import Path

    from src.data_pipeline import run_pipeline

    content = up.getvalue()
    if len(content) > 50 * 1024 * 1024:
        ui.note("Extracts are limited to 50 MB.", title="File too large", tone="stop")
        return
    try:
        with tempfile.TemporaryDirectory(prefix="creditdesk_") as tmpdir:
            tmp = Path(tmpdir) / "extract.csv"
            tmp.write_bytes(content)
            header = pd.read_csv(tmp, nrows=0).columns
            absent = [col for col in SOURCE_COLUMNS if col not in header]
            if absent:
                raise ValueError("missing column(s) " + ", ".join(absent) + f". The extract needs all "
                                 f"{N_SOURCE} source columns, including credit_score and late_payments_12m.")
            test, rep = run_pipeline(str(tmp), drop_invalid=True)
        if len(test) < 500:
            raise ValueError(f"only {len(test)} usable rows after cleaning; at least 500 are needed to train a model.")
        if test["approved"].nunique() < 2:
            raise ValueError("the approval outcome has only one value; a model cannot be trained.")
        policy_store.register_data_source(content, up.name, user.username, len(test), role=user.role)
        st.success(f"Loaded {len(test):,} applications from {up.name} for every user. "
                   "A new model is trained on first use.")
        st.rerun()
    except audit.AuditError as exc:
        ui.note(f"Not loaded - the audit log could not record it: {esc(str(exc))}", title="Load refused", tone="stop")
    except Exception as exc:
        ui.note(f"That file could not be processed: {esc(str(exc))}", title="Load failed", tone="stop")


def _fairness(c) -> None:
    ui.section("Disparate-impact screen",
               "Approval rate by group and the adverse impact ratio (each group's rate divided by the "
               "highest group's). Below 0.80 is the common four-fifths screening flag.")
    if not fairness.has_protected_attributes(c.book):
        ui.note("This extract has <b>no protected attributes</b> (sex, age, ethnicity, religion, marital "
                "status), so direct testing is impossible. Below, the model inputs most likely to act as "
                "proxies are screened instead. Add the attributes to a future extract (held separately from "
                "the model inputs) to test them directly.", title="Limit of this test", tone="warn")
    book = c.book
    for label, outcome in (("Historical approvals", "approved"),):
        t = fairness.screen(book, outcome)
        st.markdown(f"**{label}**")
        ui.table(t.style.format({"approval_rate": "{:.1%}", "ratio_to_highest": "{:.2f}"}), hide_index=True, height=300)
    proba = honest_probabilities(book, fingerprint_of(book))
    model_ok = pd.Series((proba >= c.cutoff).astype(int), index=book.index)
    st.markdown(f"**Model approvals at the {c.cutoff:.0%} cut-off** (out-of-fold)")
    t2 = fairness.screen(book, model_ok)
    ui.table(t2.style.format({"approval_rate": "{:.1%}", "ratio_to_highest": "{:.2f}"}), hide_index=True, height=300)
    flagged = t2[t2["flag"] == "Below 0.80"]
    if len(flagged):
        ui.note("Groups below 0.80: " + ", ".join(f"{r.dimension} / {r.group}" for r in flagged.itertuples())
                + ". A flag is a prompt to investigate (is a legitimate credit factor driving it?), not a legal finding.",
                title="Review needed", tone="warn")
    if "application_year" in book.columns and book["application_year"].nunique() > 1:
        st.markdown("**Ratio to the highest group, year by year** (model approvals, out-of-fold)")
        st.caption("A ratio that keeps falling across years is a pattern, not noise - even if one year alone "
                   "stays above 0.80.")
        ui.table(fairness_by_year(book, model_ok).style.format("{:.2f}", na_rep="-")
                 .map(lambda v: "color:#A32C2C;font-weight:600" if isinstance(v, float) and v < 0.8 else ""),
                 hide_index=False)


def fairness_by_year(book: pd.DataFrame, outcome: pd.Series) -> pd.DataFrame:
    """Adverse impact ratio for every group, calculated separately for each application year."""
    cols = {}
    for year, idx in book.groupby("application_year").groups.items():
        part = book.loc[idx]
        t = fairness.screen(part, outcome.loc[idx])
        cols[str(year)] = t.set_index(["dimension", "group"])["ratio_to_highest"]
    return pd.DataFrame(cols)


def _quarter_drift(c, profile_from) -> None:
    """Has the applicant mix changed? The latest quarter in the book against everything before it."""
    book = c.book
    if "application_quarter" not in book.columns or book["application_quarter"].nunique() < 3:
        return
    quarters = sorted(book["application_quarter"].unique())
    pick = st.selectbox("Quarter to compare with everything before it", quarters[1:][::-1], key="gov_drift_q")
    before = book[book["application_quarter"] < pick]
    now = book[book["application_quarter"] == pick]
    proba = honest_probabilities(book, fingerprint_of(book))
    pb = proba[(book["application_quarter"] < pick).values]
    pn = proba[(book["application_quarter"] == pick).values]
    ui.section(f"Applicant mix: {pick} against earlier quarters",
               f"{len(now):,} applications in {pick} compared with {len(before):,} received before it. "
               "This uses the book itself, so it works before any live decisions are saved.")
    table = profile_from.drift_table(profile_from.reference_profile(before, pb), now, pn)
    ui.table(table.style.format({"PSI": "{:.3f}"}), hide_index=True, height=300)


def _monitoring(c) -> None:
    ui.section("Model monitoring",
               "Is the population being scored still like the one the model learned from, and do the scores "
               "match what happened? PSI under 0.10 is stable, 0.10-0.25 watch, above 0.25 shifted.")
    recent = workflow.inputs_frame(5000)
    profile = monitoring.reference_profile(c.book, c.model.oof_proba if len(c.model.oof_proba) == len(c.book) else None)
    if len(recent) < 30:
        ui.note(f"Only {len(recent)} saved decisions so far. Drift is measured on saved decisions "
                "(the applications actually scored); it needs at least 30 to be meaningful and 200 to trigger a "
                "retraining recommendation.", title="Not enough live volume yet")
    else:
        from src import decisioning as dec
        enriched = dec.enrich_frame(recent[dec.APPLICATION_FIELDS])
        table = monitoring.drift_table(profile, enriched, recent["probability"].values)
        ui.table(table.style.format({"PSI": "{:.3f}"}), hide_index=True, height=320)
        go, msg = monitoring.retrain_recommended(table, n_rows=len(recent))
        ui.note(msg, title="Retraining trigger", tone="warn" if go else "info")

    _quarter_drift(c, profile_from=monitoring)

    ui.section("Back-test against real outcomes")
    st.caption("Upload a CSV with columns `application_id` and `repaid` (1 = repaid well, 0 = defaulted or "
               "severely delinquent). It is matched to saved decisions and compared with the scores.")
    up = st.file_uploader("Outcomes file", type=["csv"], key="bt_up", label_visibility="collapsed")
    use_book = st.checkbox("Use outcomes from the Loan book instead", key="bt_book",
                           help="Loans created from a scored application and seasoned for 6+ months (or already bad).")
    if up is not None or use_book:
        try:
            if use_book:
                from src import loanbook
                out = loanbook.outcomes()
            else:
                out = pd.read_csv(up)
            dec_df = workflow.decisions(5000)[["application_id", "probability"]]
            m = dec_df.merge(out[["application_id", "repaid"]], on="application_id")
            res = monitoring.backtest(m["probability"], m["repaid"])
            cols = st.columns(4)
            for col, (k, v) in zip(cols, (("Matched", f"{res['n']:,}"), ("AUC", f"{res['auc']:.3f}"),
                                          ("KS", f"{res['ks']:.3f}"), ("Brier", f"{res['brier']:.3f}"))):
                with col:
                    ui.kpi(k, v)
            ui.table(res["table"].style.format({"mean_score": "{:.1%}", "observed_rate": "{:.1%}"}), hide_index=True)
        except Exception as exc:
            ui.note(str(exc), title="Back-test not possible", tone="stop")

    ui.section("Model registry", "Every trained model, saved with a hash so a past score can be reproduced.")
    reg = registry.list_models()
    if reg.empty:
        st.caption("No model has been saved yet.")
    else:
        ui.table(reg, hide_index=True, height=200)


def _backup() -> None:
    from src import deps
    if not deps.has("cryptography"):
        ui.note(str(deps.MissingLibrary("cryptography")), title="Backup and restore unavailable", tone="warn")
        return
    from src import backup
    user = auth.current_user()
    if user.role != "admin":
        ui.note("Only an Administrator can create or restore backups.", title="Administrators only")
        return
    ui.section("Encrypted backup",
               "One encrypted file with the audit database, users, models, uploads and documents. It stays on "
               "your computer; keep the passphrase safe - it cannot be recovered.")
    pw = st.text_input("Passphrase (12+ characters)", type="password", key="bak_pw")
    if st.button("Create backup", key="bak_go"):
        try:
            st.session_state["bak_blob"] = backup.create(pw, user.username, user.role)
            st.success("Backup created. Download it below.")
        except (ValueError, audit.AuditError) as exc:
            st.error(str(exc))
    if "bak_blob" in st.session_state:
        st.download_button("Download backup", st.session_state["bak_blob"], file_name="credit_desk_backup.cdbk",
                           mime="application/octet-stream")
    ui.section("Restore", "Replaces current data with the backup. The audit chain of the backup is verified first.")
    f = st.file_uploader("Backup file", type=["cdbk"], key="bak_up")
    rp = st.text_input("Backup passphrase", type="password", key="bak_rpw")
    if f is not None and rp:
        try:
            info = backup.inspect(f.getvalue(), rp)
            st.json(info)
            if st.checkbox("I understand this replaces current data", key="bak_ok") and st.button("Restore now", key="bak_restore"):
                backup.restore(f.getvalue(), rp, user.username, user.role)
                st.success("Restored. Please sign in again.")
        except Exception as exc:
            st.error(str(exc))
