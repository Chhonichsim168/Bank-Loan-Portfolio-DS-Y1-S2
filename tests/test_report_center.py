"""Reports page (src/report_center.py + views/reports_page.py): one export with everything, role-limited."""
import io
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def seeded(sandbox, monkeypatch):
    monkeypatch.setenv("CREDIT_DESK_SAMPLE_DATA", "1")
    monkeypatch.delenv("CREDIT_DESK_STRONG_PASSWORDS", raising=False)
    from src import sample_customers
    sample_customers.ensure()
    return sandbox


def test_collect_excel_pdf_admin(seeded):
    from src import report_center as rc
    data = rc.collect(date(2000, 1, 1), date.today(), list(rc.SECTIONS), "admin")
    assert {"loans", "payments", "late", "requests", "customers", "audit", "_summary"} <= set(data)
    loans = data["loans"]
    chh = loans[loans["username"] == "chhonich"]
    assert len(chh) == 1 and chh.iloc[0]["email"] == "chhonichsim1@gmail.com"     # contact joined to the loan
    assert "chhonich" in set(data["late"].get("full_name", []).index) or len(data["late"]) >= 1
    assert data["requests"]["status"].eq("Pending review").any()
    meta = rc.meta_for(date(2000, 1, 1), date.today(), list(rc.SECTIONS),
                       SimpleNamespace(display_name="Admin", role_label="Administrator"))
    wb = load_workbook(io.BytesIO(rc.excel(data, meta)))
    assert {"Summary", "Loans", "Payments", "Late customers", "Customer requests", "Customers", "Audit log"} <= set(wb.sheetnames)
    assert wb["Loans"].max_row == len(loans) + 1
    assert rc.pdf(data, meta)[:4] == b"%PDF"


def test_officer_never_gets_audit_or_customer_accounts(seeded):
    from src import report_center as rc
    assert "audit" not in rc.allowed_sections("officer") and "customers" not in rc.allowed_sections("officer")
    data = rc.collect(date(2000, 1, 1), date.today(), list(rc.SECTIONS), "officer")
    assert "audit" not in data and "customers" not in data


def test_period_filters_payments(seeded):
    from src import report_center as rc
    data = rc.collect(date(2000, 1, 1), date(2000, 1, 31), ["payments"], "admin")
    assert len(data["payments"]) == 0


def test_period_choices():
    from views.reports_page import period_dates
    d = date(2026, 5, 20)
    assert period_dates("This month", d) == (date(2026, 5, 1), d)
    assert period_dates("Last month", d) == (date(2026, 4, 1), date(2026, 4, 30))
    assert period_dates("This quarter", d) == (date(2026, 4, 1), d)


PAGE = """
import sys
sys.path.insert(0, r"{root}")
import streamlit as st
from src import auth, state, ui
ui.inject_theme(); state.init()
st.session_state["_auth_user"] = auth._public("{who}", auth._read_users()["{who}"])
from views import reports_page
reports_page.render()
"""


@pytest.mark.parametrize("who", ["boss", "clerk"])
def test_reports_page_builds(seeded, who):
    from src import auth
    auth.create_user(who, who.title(), "admin" if who == "boss" else "officer", auth.generate_temp_password(),
                     must_change=False)
    at = AppTest.from_string(PAGE.format(root=ROOT, who=who), default_timeout=180).run()
    assert not at.exception, [e.value for e in at.exception]
    labels = [c.label for c in at.checkbox]
    assert ("Audit log" in labels) == (who == "boss")
    at.button(key="rep_build").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("report is ready" in s.value for s in at.success)
    assert not auth.can_access("customer", "reports") and auth.can_access("officer", "reports")


def test_app_menu_lists_reports():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '("Reports", "reports", reports_page.render)' in src
