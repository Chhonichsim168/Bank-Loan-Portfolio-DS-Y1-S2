"""v16: sample data, sample documents, auto sign-out toggle, missing-library safety."""
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def model():
    from src.data_pipeline import run_pipeline
    from src.risk_model import train_model
    df, _ = run_pipeline(str(ROOT / "data" / "loan_data.csv"))
    return train_model(df)


def _ctx(model):
    from src import policy_store
    s = policy_store.Settings()
    return SimpleNamespace(model=model, policy=s.policy(), cutoff=s.cutoff, settings=s, policy_version=0,
                           model_version=model.model_version)


@pytest.fixture()
def seeded(sandbox, model, monkeypatch):
    from src import sample_data
    monkeypatch.setenv("CREDIT_DESK_SAMPLE_DATA", "1")
    res = sample_data.seed_if_empty(lambda: _ctx(model))
    return res


# ---- sample data ------------------------------------------------------------------------
def test_sample_decisions_cover_every_queue_status(seeded):
    from src import loanbook, workflow
    d = workflow.add_timing(workflow.decisions())
    assert d["customer_ref"].str.startswith("SAMPLE-").all()
    statuses = set(d["status"])
    assert {"Pending second approval", "Final", "Final (approved by reviewer)", "Rejected by reviewer",
            "Returned to officer"} <= statuses
    pend = d[d["status"] == "Pending second approval"]
    assert len(pend) >= 4 and pend["over_sla"].sum() >= 2
    assert any("override" in r for r in pend["review_reasons"])
    assert len(loanbook.eligible_decisions()) >= 2                       # something to pick in "Add a loan"
    assert (d["customer_ref"] == "SAMPLE-C101").sum() == 2               # a repeat applicant


def test_sample_loans_cover_expired_and_active_states(seeded):
    from src import loanbook
    book = loanbook.portfolio()
    today = pd.Timestamp.today().date()
    assert set(book["status"]) == {"Active", "Closed", "Written off"}
    assert {"1-29", "30-59", "60-89", "90+", "Current"} <= set(book["bucket"])
    matured = book[pd.to_datetime(book["maturity_date"]).dt.date < today]
    assert len(matured) >= 3 and "Active" in set(matured["status"]) and "Closed" in set(matured["status"])
    assert (book["remaining_instalments"] > 0).sum() >= 10                 # loans not yet expired
    ev = loanbook.all_events()
    assert {"payment", "note", "promise", "restructure", "writeoff", "settle"} <= set(ev["kind"])
    due = loanbook.upcoming_dues(book, today, 7)
    assert (due["days_until_due"].between(0, 7)).any()
    out = loanbook.outcomes()
    assert len(out) >= 6 and set(out["repaid"]) == {0, 1}                  # evidence for observed default


def test_sample_data_loads_only_once(seeded, model):
    from src import loanbook, sample_data
    n = len(loanbook.list_loans())
    sample_data.marker_path().unlink()
    assert sample_data.seed_if_empty(lambda: _ctx(model)) is None         # SAMPLE- records already there
    assert len(loanbook.list_loans()) == n


def test_sample_data_switch_off(sandbox, monkeypatch):
    from src import sample_data
    monkeypatch.setenv("CREDIT_DESK_SAMPLE_DATA", "0")
    assert sample_data.seed_if_empty(lambda: (_ for _ in ()).throw(AssertionError("must not load"))) is None


SCRIPT = """
import sys
sys.path.insert(0, r"{root}")
import streamlit as st
from src import auth, state, ui
ui.inject_theme(); state.init()
st.session_state["_auth_user"] = auth.User("{user}", "Tester", "{role}")
from views import {mod}
{mod}.render()
"""


@pytest.mark.parametrize("mod,role,user", [("queue", "risk", "risk"), ("queue", "officer", "officer"),
                                            ("loan_book", "admin", "admin"), ("governance", "admin", "admin"),
                                            ("overview", "admin", "admin")])
def test_pages_render_with_sample_data(seeded, mod, role, user):
    at = AppTest.from_string(SCRIPT.format(root=ROOT, mod=mod, role=role, user=user), default_timeout=300).run()
    assert not at.exception, [e.value for e in at.exception]


# ---- sample documents ---------------------------------------------------------------------
def test_sample_document_for_every_type_attaches(sandbox):
    from src import documents
    from views._docs import SAMPLE_DIR, SAMPLES
    assert set(SAMPLES) == set(documents.KINDS)
    assert {f.rsplit(".", 1)[1] for f, _ in SAMPLES.values()} == {"pdf", "png", "jpg"}
    for kind, (fname, _) in SAMPLES.items():
        documents.attach("CASE-1", (SAMPLE_DIR / fname).read_bytes(), fname, kind, "tester", "admin")
    assert len(documents.for_case("CASE-1")) == len(SAMPLES)


# ---- auto sign-out ------------------------------------------------------------------------
def test_auto_sign_out_is_off_by_default_and_can_be_switched(sandbox, monkeypatch):
    from src import auth
    monkeypatch.delenv("CREDIT_DESK_AUTO_LOGOUT", raising=False)
    monkeypatch.setenv("CREDIT_DESK_DEMO_USERS", "1")
    auth.ensure_bootstrap()
    assert auth.auto_logout_enabled("officer") is False
    auth.set_auto_logout("officer", True)
    assert auth.auto_logout_enabled("officer") is True
    auth.set_auto_logout("officer", False)
    assert auth.auto_logout_enabled("officer") is False


# ---- missing optional libraries never crash a page ----------------------------------------
def test_pages_work_without_optional_libraries():
    """cryptography, reportlab, openpyxl and matplotlib hidden: every page must still open.
    Runs in its own process with its own throw-away data folder."""
    import subprocess
    import sys
    script = ROOT / "tests" / "helpers" / "nolib_pages.py"
    out = subprocess.run([sys.executable, str(script), str(ROOT)], capture_output=True, text=True, timeout=900)
    line = [ln for ln in out.stdout.splitlines() if ln.startswith("FAILED:")]
    assert line and line[-1] == "FAILED:", out.stdout[-2000:] + out.stderr[-2000:]
