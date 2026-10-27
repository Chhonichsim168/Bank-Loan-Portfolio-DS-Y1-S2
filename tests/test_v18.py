"""v18: late-payment notifications and the result window (receipt) after important buttons."""
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def model():
    from src.data_pipeline import run_pipeline
    from src.risk_model import train_model
    df, _ = run_pipeline(str(ROOT / "data" / "loan_data.csv"))
    return train_model(df)


@pytest.fixture()
def seeded(sandbox, model, monkeypatch):
    from src import policy_store, sample_data
    monkeypatch.setenv("CREDIT_DESK_SAMPLE_DATA", "1")
    s = policy_store.Settings()
    sample_data.seed_if_empty(lambda: SimpleNamespace(model=model, policy=s.policy(), cutoff=s.cutoff, settings=s,
                                                      policy_version=0, model_version=model.model_version))


def _loan(customer, first_due_days, term=12):
    from src import loanbook
    today = date.today()
    return loanbook.create_loan(username="o", role="officer", customer_ref=customer, product=loanbook.PRODUCTS[0],
                                principal=12_000, annual_rate=0.12, term_months=term,
                                disbursed_on=today - timedelta(days=200), first_due_on=today + timedelta(days=first_due_days),
                                collateral_value=0, band="Review")


# ---- notifications --------------------------------------------------------------------------
def test_overdue_lists_only_late_active_loans_by_severity(sandbox):
    from src import loanbook, notifications
    late95 = _loan("LATE-95", -95)
    late40 = _loan("LATE-40", -40)
    ok = _loan("ON-TIME", 10)
    book = loanbook.portfolio()
    late = notifications.overdue(book)
    assert list(late["loan_id"]) == [late95, late40]                  # most urgent first
    assert list(late["severity"]) == ["Default", "Warning"]
    assert ok not in set(late["loan_id"])
    assert (late["arrears"] > 0).all() and (late["instalments_missed"] >= 2).all()
    s = notifications.summary(late)
    assert s["customers"] == 2 and s["over_30"] == 2 and s["over_90"] == 1


def test_paying_the_arrears_clears_the_notification(sandbox):
    from src import loanbook, notifications
    lid = _loan("PAYS", -40)
    row = notifications.overdue(loanbook.portfolio()).iloc[0]
    eid = loanbook.add_event(lid, username="o", role="officer", kind="payment", event_date=date.today(),
                             amount=float(row["arrears"]) + 1)
    assert isinstance(eid, int) and eid > 0                            # receipt number
    assert notifications.overdue(loanbook.portfolio()).empty


def test_severity_bands():
    from src.notifications import severity
    assert [severity(d)[0] for d in (0, 1, 29, 30, 60, 90, 400)] == \
        ["Overdue today", "Reminder", "Reminder", "Warning", "Serious", "Default", "Default"]


def test_sample_data_has_late_customers(seeded):
    from src import loanbook, notifications
    s = notifications.summary(notifications.overdue(loanbook.portfolio()))
    assert s["loans"] >= 4 and s["over_90"] >= 1


# ---- PDFs -----------------------------------------------------------------------------------
def test_receipt_and_overdue_notice_pdfs():
    import pandas as pd
    from src import reports
    if not reports.HAVE_PDF:
        pytest.skip("reportlab not installed")
    a = reports.receipt_pdf(title="Payment receipt", number="PAY-000001", issued="19/10/2026 14:00",
                            rows=[("Amount received", "1,000.00")], status="Payment received",
                            table=pd.DataFrame({"No.": [1], "Due date": ["2026-11-01"]}), table_title="Schedule")
    b = reports.overdue_notice_pdf(customer_ref="C-1", loan_id="L-1", product="Personal", dpd=95, arrears=2500,
                                   missed=3, oldest_due="2026-07-01", outstanding=9000, pay_by="26/10/2026",
                                   severity="Default")
    assert a.startswith(b"%PDF") and b.startswith(b"%PDF")


# ---- pages ----------------------------------------------------------------------------------
PAGE = """
import sys
sys.path.insert(0, r"{root}")
import streamlit as st
from src import auth, state, ui
ui.inject_theme(); state.init()
st.session_state["_auth_user"] = auth.User("{user}", "{user}", "{role}")
from views import {mod}, _result
_result.render_pending()
{mod}.render()
"""


@pytest.mark.parametrize("role", ["officer", "risk", "admin"])
def test_loan_book_late_tab_renders_for_every_role(seeded, role):
    at = AppTest.from_string(PAGE.format(root=ROOT, mod="loan_book", role=role, user=role), default_timeout=300).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Late payments" in t.label for t in at.tabs)
    assert any("Late payment notifications" in m.value for m in at.markdown)


def test_save_payment_opens_a_receipt(seeded):
    at = AppTest.from_string(PAGE.format(root=ROOT, mod="loan_book", role="officer", user="officer"),
                             default_timeout=300).run()
    assert not at.exception
    late_form_amount = [n for n in at.number_input if n.label == "Amount (payments)"][0]
    late_form_amount.set_value(100.0)
    [b for b in at.button if b.label == "Save record"][0].click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    # the script reruns after saving, so the queued receipt has been opened and consumed
    assert "_cd_result" not in at.session_state
    from src import loanbook
    assert (loanbook.all_events()["username"] == "officer").any()


def test_result_window_renders_every_kind(sandbox):
    script = """
import sys
sys.path.insert(0, r"{root}")
import pandas as pd
import streamlit as st
from src import ui
ui.inject_theme()
from views import _result
_result.push(title="Loan created", number="L-1", status="Loan L-1 created", rows=[("Customer", "C-1")],
             table=pd.DataFrame({{"No.": [1, 2]}}), table_title="Repayment schedule", next_steps=["a", "b"],
             extra_files=[("Extra", b"x", "x.txt", "text/plain")])
_result.render_pending()
st.write("after")
""".format(root=ROOT)
    at = AppTest.from_string(script, default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert "_cd_result" not in at.session_state                     # shown once, then gone


def test_receipt_html_escapes_values():
    from views._result import receipt_html
    html = receipt_html({"title": "t", "number": "1", "issued": "now", "status": "ok", "tone": "good",
                         "rows": [("Customer", "<script>x</script>")]})
    assert "<script>" not in html and "&lt;script&gt;" in html
