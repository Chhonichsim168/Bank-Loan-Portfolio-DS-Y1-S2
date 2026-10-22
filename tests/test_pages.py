"""Render every page headlessly (Streamlit AppTest) and exercise the decision flow end to end."""
import pytest
from streamlit.testing.v1 import AppTest

from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

SCRIPT = """
import sys
sys.path.insert(0, r"{root}")
import streamlit as st
from src import auth, state, ui
ui.inject_theme()
state.init()
if "_auth_user" not in st.session_state:
    st.session_state["_auth_user"] = auth.User("tester", "Tester", "{role}")
from views import {mod}
{mod}.render()
"""

PAGES = ["overview", "segments", "drivers", "underwrite", "batch", "policy", "queue",
         "model", "governance", "users", "account", "loan_book"]


def page(mod, role="admin"):
    return AppTest.from_string(SCRIPT.format(root=ROOT, mod=mod, role=role), default_timeout=240)


def text_of(at):
    return " ".join([m.value for m in at.markdown] + [e.value for e in at.error] + [s.value for s in at.success])


@pytest.mark.parametrize("mod", PAGES)
def test_page_renders_without_error(sandbox, mod):
    if mod == "users":
        from src import auth
        auth.ensure_bootstrap()
    at = page(mod).run()
    assert not at.exception, [e.value for e in at.exception]


def test_policy_breach_is_enforced_on_the_single_application_page(sandbox):
    """The reviewed bug: this page ignored hard policy. An unemployed applicant with no credit
    history must be routed to Decline whatever the model score."""
    at = page("underwrite").run()
    at.button(key="uw_fill_example").click().run()       # every field starts empty
    at.selectbox(key="uw_emp").select("unemployed")
    at.selectbox(key="uw_credit").select(0)
    at.run()
    assert not at.exception
    t = text_of(at)
    assert "breaches hard policy" in t
    assert "Prepare a decline" in t


def test_decision_is_saved_to_the_database_and_pending_when_it_must_be(sandbox):
    from src import workflow
    at = page("underwrite").run()
    at.button(key="uw_fill_example").click().run()       # every field starts empty
    at.selectbox(key="uw_emp").select("unemployed")      # policy breach -> approving it is an exception
    at.selectbox(key="uw_credit").select(0)
    at.run()
    at.text_input(key="uw_ref").set_value("CASE-001")
    at.radio(key="uw_outcome").set_value("Approve")
    at.text_area(key="uw_rationale").set_value("Documented guarantor and collateral outside the model.")
    for k in ("identity", "income", "bureau", "liabilities"):
        at.checkbox(key=f"uw_chk_{k}").check()
    at.run()
    save = next(b for b in at.button if b.label == "Save decision")
    save.click().run()
    assert not at.exception, [e.value for e in at.exception]
    df = workflow.decisions()
    assert len(df) == 1
    row = df.iloc[0]
    assert row["application_id"].startswith("APP-") and row["customer_ref"] == "CASE-001"
    assert row["username"] == "tester" and row["status"] == "Pending second approval"
