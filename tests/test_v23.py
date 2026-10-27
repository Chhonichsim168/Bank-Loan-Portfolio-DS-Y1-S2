"""v23: the applications live in SQLite; add / remove records; charts follow the database."""
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "loan_data.csv"

NEW = {"application_date": "2026-10-01", "applicant_income": 4000, "coapplicant_income": 0, "loan_amount": 90000,
       "loan_term_months": 240, "credit_history": 1, "dependents": 1, "employment_status": "salaried",
       "property_area": "urban", "credit_score": 720, "late_payments_12m": 0, "approved": 1}


def test_import_keeps_every_value_exactly(sandbox):
    from src import app_store
    pd.testing.assert_frame_equal(app_store.load_frame(), pd.read_csv(CSV))


def test_pipeline_and_model_identical_to_the_csv(sandbox):
    from src import app_store
    from src.data_pipeline import run_pipeline
    from src.risk_model import model_version
    a, ra = run_pipeline(CSV)
    b, rb = run_pipeline(app_store.load_frame())
    pd.testing.assert_frame_equal(a, b)
    assert model_version(a) == model_version(b)              # the same model, the same AUC
    assert (ra.rows_in, ra.rows_out) == (rb.rows_in, rb.rows_out) == (2000, 2000)


def test_add_then_remove_returns_to_the_original_data(sandbox):
    from src import app_store, audit
    v0 = app_store.version()
    rid = app_store.add(dict(NEW), "officer", "officer")
    assert rid == 2001 and app_store.count() == 2001 and app_store.version() != v0
    v1 = app_store.version()
    assert app_store.delete([rid], "risk", "risk", "test") == 1
    assert app_store.count() == 2000 and app_store.version() != v1
    pd.testing.assert_frame_equal(app_store.load_frame(), pd.read_csv(CSV))
    actions = set(audit.fetch_events(limit=50)["action"])
    assert {"data_row_added", "data_rows_deleted"} <= actions
    gone = app_store.deleted()
    assert len(gone) == 1 and gone.iloc[0]["reason"] == "test"


def test_only_risk_or_admin_can_remove_and_a_reason_is_required(sandbox):
    from src import app_store
    with pytest.raises(PermissionError):
        app_store.delete([1], "officer", "officer", "x")
    with pytest.raises(ValueError):
        app_store.delete([1], "risk", "risk", "  ")
    assert app_store.count() == 2000


def test_remove_refused_below_the_training_minimum(sandbox):
    from src import app_store
    ids = app_store.load_frame(with_ids=True)["id"].tolist()
    with pytest.raises(ValueError, match="at least"):
        app_store.delete(ids[:1600], "admin", "admin", "too many")
    assert app_store.count() == 2000


@pytest.mark.parametrize("field,value", [("credit_score", 100), ("employment_status", "astronaut"),
                                         ("loan_amount", None), ("approved", 5), ("application_date", "soon")])
def test_bad_records_are_refused(sandbox, field, value):
    from src import app_store
    rec = dict(NEW)
    rec[field] = value
    with pytest.raises(ValueError):
        app_store.add(rec, "officer", "officer")
    assert app_store.count() == 2000


def test_charts_follow_the_database(sandbox):
    """ctx() - which every chart reads - sees an added record without restarting anything."""
    import streamlit as st  # noqa: F401
    from src import app_store, state
    book, _ = state.load_book(app_store.version())
    app_store.add(dict(NEW), "officer", "officer")
    book2, _ = state.load_book(app_store.version())
    assert len(book2) == len(book) + 1
    assert state.fingerprint_of(book2) != state.fingerprint_of(book)


def test_new_data_source_replaces_the_table(sandbox):
    from src import app_store, policy_store
    app_store.add(dict(NEW), "officer", "officer")
    raw = pd.read_csv(CSV).head(800)
    policy_store.register_data_source(raw.to_csv(index=False).encode(), "small.csv", "admin", len(raw))
    assert app_store.count() == 800 and app_store.source_name() == "small.csv"
    policy_store.use_default_source("admin")
    assert app_store.count() == 2000


SCRIPT = """
import sys
sys.path.insert(0, r"{root}")
import streamlit as st
from src import auth, state, ui
ui.inject_theme(); state.init()
st.session_state["_auth_user"] = auth.User("{role}", "{role}", "{role}")
from views import appdata, _result
_result.render_pending()
appdata.render()
"""


@pytest.mark.parametrize("role", ["officer", "risk", "admin"])
def test_page_renders_for_every_role(sandbox, role):
    at = AppTest.from_string(SCRIPT.format(root=ROOT, role=role), default_timeout=240).run()
    assert not at.exception, [e.value for e in at.exception]
    labels = [b.label for b in at.button]
    assert any(l.startswith("Remove") for l in labels) == (role in ("risk", "admin"))
    assert any(t.label == "Add a record" for t in at.tabs)


def test_page_menu_lists_application_data():
    assert '("Application data", "appdata", appdata.render)' in (ROOT / "app.py").read_text(encoding="utf-8")


def test_menu_button_only_for_a_signed_in_user():
    """v24: the sign-in page shows no sidebar and no Menu button (before sign-in and after Sign out)."""
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    gate = src.index("auth.render_login()")
    assert src.index("_hide_menu_when_signed_out()") < gate
    assert src.index("\n_inject_sidebar_toggle()") > gate          # injected only after the sign-in gate
    assert "getElementById('cd-sidebar-toggle')" in src and "b.remove()" in src
