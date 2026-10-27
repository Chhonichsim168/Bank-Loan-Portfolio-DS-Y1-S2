"""v21: the portfolio filters are a bar at the top of the pages that use them."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = """
import sys
sys.path.insert(0, r"{root}")
import streamlit as st
from src import auth, state, ui
ui.inject_theme()
state.init()
if "_auth_user" not in st.session_state:
    st.session_state["_auth_user"] = auth.User("tester", "Tester", "admin")
from views import {mod}
{mod}.render()
"""


def page(mod):
    return AppTest.from_string(SCRIPT.format(root=ROOT, mod=mod), default_timeout=240)


def _count(at):
    md = " ".join(m.value for m in at.markdown)
    import re
    m = re.search(r'cd-fb-n">([\d,]+)<', md)
    return int(m.group(1).replace(",", ""))


@pytest.mark.parametrize("mod", ["overview", "segments", "drivers", "policy"])
def test_filter_bar_is_on_every_analysis_page(sandbox, mod):
    at = page(mod).run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.selectbox(key="f_period") and at.multiselect(key="f_area") and at.selectbox(key="f_outcome")
    assert "Showing the whole book" in " ".join(m.value for m in at.markdown)


@pytest.mark.parametrize("mod", ["underwrite", "loan_book", "queue", "batch"])
def test_pages_that_do_not_use_filters_do_not_show_them(sandbox, mod):
    at = page(mod).run()
    assert not at.exception
    assert "f_area" not in [w.key for w in at.multiselect]


def test_filter_chips_and_remove_one(sandbox):
    at = page("overview").run()
    whole = _count(at)
    at.multiselect(key="f_risk").select("High").run()
    at.selectbox(key="f_outcome").select("Approved only").run()
    labels = [b.label for b in at.button]
    assert any(l.startswith("Risk: High") for l in labels) and any(l.startswith("Approved only") for l in labels)
    assert "Clear all" in labels
    narrowed = _count(at)
    assert 0 < narrowed < whole
    next(b for b in at.button if b.label.startswith("Risk: High")).click().run()
    assert at.multiselect(key="f_risk").value == []
    assert at.selectbox(key="f_outcome").value == "Approved only"      # the other filter stays
    next(b for b in at.button if b.label == "Clear all").click().run()
    assert _count(at) == whole


def test_filters_survive_a_page_without_the_bar():
    """state.init writes the values back, so visiting Score an application does not reset them."""
    src = (ROOT / "src" / "state.py").read_text(encoding="utf-8")
    assert 'st.session_state[k] = st.session_state[k]' in src


def test_sidebar_no_longer_draws_filters():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "def filters(" not in src and "st.sidebar.multiselect" not in src
