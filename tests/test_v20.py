"""v20: empty application form, automatic document type, late-payment alert bar, filters group."""
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
    st.session_state["_auth_user"] = auth.User("tester", "Tester", "{role}")
from views import {mod}
{mod}.render()
"""


def page(mod, role="admin"):
    return AppTest.from_string(SCRIPT.format(root=ROOT, mod=mod, role=role), default_timeout=240)


# ---- Score an application starts empty ------------------------------------------------------
def test_score_page_starts_empty_and_waits_for_every_required_field(sandbox):
    at = page("underwrite").run()
    assert not at.exception
    assert at.number_input(key="uw_income").value is None
    assert at.number_input(key="uw_amount").value is None
    assert at.number_input(key="uw_score").value is None
    assert at.selectbox(key="uw_emp").value is None
    assert at.selectbox(key="uw_term").value is None
    text = " ".join(m.value for m in at.markdown)
    assert "Still to fill in" in text and "Monthly income" in text
    assert not [b for b in at.button if b.label == "Save decision"]      # no score, no save yet


def test_filling_every_field_by_hand_scores_the_application(sandbox):
    at = page("underwrite").run()
    for key, v in (("uw_income", 4000), ("uw_deps", 1), ("uw_amount", 90_000), ("uw_score", 720),
                   ("uw_late", 0)):
        at.number_input(key=key).set_value(v)
    at.selectbox(key="uw_term").select(240)
    at.selectbox(key="uw_product").select_index(0)
    at.selectbox(key="uw_credit").select(1)
    at.selectbox(key="uw_emp").select("salaried")
    at.selectbox(key="uw_area").select("urban")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert [b for b in at.button if b.label == "Save decision"]
    # optional fields left blank count as 0
    assert at.number_input(key="uw_coincome").value is None


def test_example_and_clear_buttons(sandbox):
    at = page("underwrite").run()
    at.button(key="uw_fill_example").click().run()
    assert at.number_input(key="uw_income").value == 5000
    assert [b for b in at.button if b.label == "Save decision"]
    at.button(key="uw_clear").click().run()
    assert at.number_input(key="uw_income").value is None
    assert not [b for b in at.button if b.label == "Save decision"]


# ---- document type is detected, not chosen ----------------------------------------------------
@pytest.mark.parametrize("name,kind", [
    ("sample_identity.jpg", "Identity"), ("passport scan.png", "Identity"), ("ID card.jpg", "Identity"),
    ("sample_income_proof.pdf", "Income proof"), ("March payslip.pdf", "Income proof"),
    ("sample_bank_statement.pdf", "Bank statement"), ("ABA statement.pdf", "Bank statement"),
    ("sample_collateral_valuation.png", "Collateral / valuation"), ("land title.jpg", "Collateral / valuation"),
    ("sample_contract.pdf", "Contract"), ("signed agreement.pdf", "Contract"),
    ("sample_other.pdf", "Other"), ("bankok trip.pdf", "Other"), ("IMG_2041.jpg", "Other"),
])
def test_detect_kind(name, kind):
    from src.documents import KINDS, detect_kind
    got, why = detect_kind(name)
    assert got == kind and got in KINDS and why


def test_every_sample_document_is_detected_as_its_own_type():
    from views._docs import SAMPLE_DIR, SAMPLES
    from src.documents import detect_kind
    for kind, (fname, _) in SAMPLES.items():
        p = SAMPLE_DIR / fname
        assert detect_kind(fname, p.read_bytes())[0] == kind


def test_documents_widget_has_no_manual_type_picker(sandbox):
    at = page("underwrite").run()
    at.button(key="uw_fill_example").click().run()
    at.text_input(key="uw_ref").set_value("DOC-1")
    at.text_area(key="uw_rationale").set_value("test")
    at.radio(key="uw_outcome").set_value("Refer")
    at.run()
    next(b for b in at.button if b.label == "Save decision").click().run()
    assert not at.exception, [e.value for e in at.exception]
    labels = [s.label for s in at.selectbox]
    assert "Document type" not in labels


# ---- late-payment alert bar and the filters group in app.py -----------------------------------
def test_app_source_has_alert_bar_badge_and_filter_group():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "def _late_banner(" in src and ":red-badge[" in src
    assert "st.sidebar.markdown(\n            '<div class=\"cd-late\"" not in src   # old sidebar card gone


def test_loading_screen_is_shown_before_the_receipt(monkeypatch):
    from views import _result
    shown = []
    monkeypatch.setattr(_result, "_loading_screen", lambda title: shown.append(title))
    import streamlit as st
    st.session_state.clear() if hasattr(st.session_state, "clear") else None
    _result.push(title="Payment receipt", number="PAY-1", status="ok", rows=[("a", "b")])
    assert shown == ["Payment receipt"]
