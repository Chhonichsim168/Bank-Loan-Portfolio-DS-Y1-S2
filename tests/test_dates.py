"""Date features: application dates in the data, the shared Period filter, and every page that
shows date information (trends, waiting times, due dates, version timelines, stability)."""
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src import state
from src.data_pipeline import (DATE_COL, has_dates, run_pipeline, today_local, to_local,
                               validate_applications)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "loan_data.csv"


@pytest.fixture(scope="module")
def book():
    df, _ = run_pipeline(str(DATA))
    return df


# ---- data ------------------------------------------------------------------------------
def test_dataset_carries_valid_application_dates(book):
    assert has_dates(book)
    assert book[DATE_COL].notna().all()
    assert book[DATE_COL].max() <= today_local()
    assert book["application_month"].nunique() >= 24          # more than two years of history
    assert {"application_quarter", "application_year", "application_weekday"} <= set(book.columns)


def test_date_is_never_a_model_input():
    from src.risk_model import CATEGORICAL_FEATURES, NUMERIC_FEATURES
    assert not any("application" in c for c in NUMERIC_FEATURES + CATEGORICAL_FEATURES)


def test_bad_dates_are_rejected_by_the_pipeline(tmp_path):
    raw = pd.read_csv(DATA).head(6)
    raw.loc[0, DATE_COL] = "not a date"
    raw.loc[1, DATE_COL] = (today_local() + pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    raw.loc[2, DATE_COL] = "1990-05-01"
    p = tmp_path / "x.csv"
    raw.to_csv(p, index=False)
    df, rep = run_pipeline(str(p))
    assert len(df) == 3
    assert rep.invalid_rows_flagged["application_date_invalid"] == 1
    assert rep.invalid_rows_flagged["application_date_in_future"] == 1
    assert rep.invalid_rows_flagged["application_date_too_old"] == 1


def test_extract_without_dates_still_loads(tmp_path):
    raw = pd.read_csv(DATA).drop(columns=[DATE_COL])
    p = tmp_path / "nodate.csv"
    raw.to_csv(p, index=False)
    df, _ = run_pipeline(str(p))
    assert not has_dates(df) and len(df) == len(raw)
    assert state.period_bounds(df, "Last 3 months") is None


def test_batch_file_date_column_is_optional_and_checked():
    raw = pd.read_csv(ROOT / "data" / "application_sample_100.csv").head(4)
    raw[DATE_COL] = raw[DATE_COL].astype(object)
    raw.loc[1, DATE_COL] = "2099-01-01"
    raw.loc[2, DATE_COL] = "yesterday"
    valid, issues = validate_applications(raw)
    assert len(valid) == 2
    assert set(issues["problem"]) == {"in the future", "not a date (use YYYY-MM-DD or DD/MM/YYYY)"}
    valid2, issues2 = validate_applications(raw.drop(columns=[DATE_COL]))
    assert issues2.empty and (valid2[DATE_COL] == today_local()).all()


# ---- period filter ---------------------------------------------------------------------
@pytest.mark.parametrize("preset", [p for p in state.PERIODS if p not in ("All time", "Custom range")])
def test_every_preset_gives_a_nonempty_window_and_a_previous_one(book, preset):
    b = state.period_bounds(book, preset)
    assert b is not None and b[0] <= b[1]
    view = state.in_period(book, b)
    assert len(view) > 0
    assert view[DATE_COL].between(b[0], b[1]).all()
    pb = state.previous_bounds(b)
    assert pb[1] < b[0]


def test_latest_month_compares_with_the_month_before(book):
    b = state.period_bounds(book, "Latest month")
    assert (b[0], b[1]) == (pd.Timestamp("2026-09-01"), pd.Timestamp("2026-09-30"))
    assert state.previous_bounds(b) == (pd.Timestamp("2026-08-01"), pd.Timestamp("2026-08-31"))
    q = state.previous_bounds(state.period_bounds(book, "Last 3 months"))
    assert q == (pd.Timestamp("2026-04-01"), pd.Timestamp("2026-06-30"))


def test_custom_range(book):
    b = state.period_bounds(book, "Custom range", (date(2025, 1, 1), date(2025, 3, 31)))
    v = state.in_period(book, b)
    assert v["application_quarter"].unique().tolist() == ["2025-Q1"]


def test_local_time_is_phnom_penh():
    assert to_local("2026-10-16T20:30:00+00:00") == "17/10/2026 03:30"   # UTC+7 crosses midnight


# ---- helpers behind the pages ----------------------------------------------------------
def test_monthly_trend_and_driver_stability(book):
    from views.drivers import driver_stability
    from views.overview import monthly_trend
    t = monthly_trend(book)
    assert t["applications"].sum() == len(book) and t["application_month"].is_monotonic_increasing
    s = driver_stability(book)
    assert {"2024", "2025", "2026"} <= set(s.columns)


def test_model_performance_by_quarter(book):
    from src.risk_model import train_model
    from views.model import performance_by_period
    m = train_model(book)
    assert m.oot_auc is not None and 0.6 < m.oot_auc < 1     # out-of-time validation now runs
    t = performance_by_period(book.reset_index(drop=True), m.oof_proba)
    assert t["applications"].sum() == len(book) and t["auc"].notna().all()


def test_policy_version_timeline():
    from views.policy import version_timeline
    hist = [
        {"id": 4, "ts": "2026-10-10T02:00:00+00:00", "username": "risk2", "role": "risk", "kind": "approve", "ref_id": 3, "reason": ""},
        {"id": 3, "ts": "2026-10-09T02:00:00+00:00", "username": "a", "role": "admin", "kind": "propose", "ref_id": None, "reason": "tighten DTI"},
        {"id": 2, "ts": "2026-09-01T02:00:00+00:00", "username": "risk", "role": "risk", "kind": "approve", "ref_id": 1, "reason": ""},
        {"id": 1, "ts": "2026-08-31T02:00:00+00:00", "username": "a", "role": "admin", "kind": "propose", "ref_id": None, "reason": "first"},
    ]
    t = version_timeline(hist)
    assert list(t["Version"]) == [3, 1]
    assert t.loc[0, "In force until"] == "(current)"
    assert t.loc[1, "Days in force"] == 39 and t.loc[0, "Reason"] == "tighten DTI"


def test_queue_timing_and_customer_history(sandbox):
    from src import workflow
    rec = dict(role="officer", outcome="Refer", loan_amount=50_000.0, probability=0.5, score_low=0.4,
               score_high=0.6, routing="Refer", cutoff=0.5, policy_version=0, model_version="m",
               policy_pass=True, breaches=[], reasons=[], rationale="x", checklist={}, authority_limit=250_000.0)
    received = (today_local() - pd.Timedelta(days=4)).strftime("%Y-%m-%d")
    workflow.save_decision(username="o1", customer_ref="CUST-9", inputs={"application_date": received}, **rec)
    t = workflow.add_timing(workflow.decisions())
    row = t.iloc[0]
    assert row["received"] == received and int(row["days_to_decide"]) == 4
    assert row["status"] == "Pending second approval" and int(row["days_waiting"]) == 0 and not row["over_sla"]
    h = workflow.customer_history("cust-9")                    # case-insensitive match
    assert len(h) == 1 and h.iloc[0]["application_date"] == received


def test_loan_book_due_soon_and_maturity(sandbox):
    from src import loanbook
    today = today_local().date()
    loanbook.create_loan(username="o", role="officer", customer_ref="L1", product=loanbook.PRODUCTS[0],
                         principal=12_000, annual_rate=0.12, term_months=12,
                         disbursed_on=today - timedelta(days=60), first_due_on=today - timedelta(days=30),
                         collateral_value=0, band="Review")          # one instalment already missed
    loanbook.create_loan(username="o", role="officer", customer_ref="L2", product=loanbook.PRODUCTS[0],
                         principal=12_000, annual_rate=0.12, term_months=24,
                         disbursed_on=today - timedelta(days=20), first_due_on=today + timedelta(days=5),
                         collateral_value=0, band="Fast-track")
    book = loanbook.portfolio(today)
    due = loanbook.upcoming_dues(book, today, 7)
    assert list(due["customer_ref"]) == ["L1", "L2"]                  # arrears first
    l2 = book[book["customer_ref"] == "L2"].iloc[0]
    assert l2["remaining_instalments"] == 24 and l2["maturity_date"] > today


# ---- every page, under every period ----------------------------------------------------
SCRIPT = """
import sys
sys.path.insert(0, r"{root}")
import streamlit as st
from src import auth, state, ui
ui.inject_theme()
state.init()
st.session_state["f_period"] = "{period}"
if "_auth_user" not in st.session_state:
    st.session_state["_auth_user"] = auth.User("tester", "Tester", "admin")
from views import {mod}
{mod}.render()
"""


@pytest.mark.parametrize("period", ["Latest month", "Last 12 months", "Previous calendar year"])
@pytest.mark.parametrize("mod", ["overview", "segments", "drivers", "policy", "model", "governance"])
def test_analysis_pages_render_for_each_period(sandbox, mod, period):
    at = AppTest.from_string(SCRIPT.format(root=ROOT, mod=mod, period=period), default_timeout=300).run()
    assert not at.exception, [e.value for e in at.exception]


def test_overview_shows_trend_and_compares_with_previous_period(sandbox):
    at = AppTest.from_string(SCRIPT.format(root=ROOT, mod="overview", period="Last 3 months"),
                             default_timeout=300).run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Monthly trend" in text and "previous period" in text


def test_pages_with_dates_render_with_records(sandbox):
    """Queue, loan book and users with real dated records in them."""
    from src import auth, loanbook, workflow
    auth.ensure_bootstrap()
    workflow.save_decision(username="o1", role="officer", customer_ref="C-1", outcome="Refer", loan_amount=1e4,
                           probability=0.5, score_low=0.4, score_high=0.6, routing="Refer", cutoff=0.5,
                           policy_version=0, model_version="m", policy_pass=True, breaches=[],
                           inputs={"application_date": today_local().strftime("%Y-%m-%d")}, reasons=[],
                           rationale="x", checklist={}, authority_limit=2.5e5)
    today = today_local().date()
    loanbook.create_loan(username="o", role="officer", customer_ref="L1", product=loanbook.PRODUCTS[0],
                         principal=5_000, annual_rate=0.1, term_months=6, disbursed_on=today - timedelta(days=40),
                         first_due_on=today - timedelta(days=10), collateral_value=0, band="Review")
    for mod in ("queue", "loan_book", "users", "underwrite", "batch"):
        at = AppTest.from_string(SCRIPT.format(root=ROOT, mod=mod, period="All time"), default_timeout=300).run()
        assert not at.exception, (mod, [e.value for e in at.exception])
