"""Loan book, economics, documents, reports, backup, challenger."""
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent


def _loan(lb, **kw):
    base = dict(username="o", role="officer", customer_ref="C1", product="Personal", principal=12000.0,
                annual_rate=0.12, term_months=12, disbursed_on=date.today() - timedelta(days=200),
                first_due_on=date.today() - timedelta(days=170), collateral_value=0.0, band="Review", area="north")
    base.update(kw)
    return lb.create_loan(**base)


def test_emi_and_pricing(sandbox):
    from src import policy_store, risk_economics as econ
    assert econ.emi(12000, 0.0, 12) == pytest.approx(1000)
    assert econ.emi(12000, 0.12, 12) == pytest.approx(1066.19, abs=0.01)
    s = policy_store.Settings()
    assert econ.suggested_rate("Decline", s) is None
    assert econ.suggested_rate("Refer", s) > econ.suggested_rate("Fast-track", s)
    secured = econ.expected_loss(10000, 20000, "Review", s)
    unsecured = econ.expected_loss(10000, 0, "Review", s)
    assert secured["el"] < unsecured["el"] and secured["lgd"] >= econ.LGD_FLOOR


def test_settings_roundtrip(sandbox):
    from src import policy_store
    s = policy_store.Settings(base_rate=0.1, max_total_dti=0.4)
    assert policy_store.Settings.from_json(s.to_json()) == s
    assert s.policy().max_total_dti == 0.4


def test_loan_dpd_and_payments(sandbox):
    from src import loanbook as lb
    lid = _loan(lb)
    loan = lb.get_loan(lid)
    ev = lb.events_for(lid)
    s = lb.snapshot(loan, ev, date.today())
    assert s["dpd"] > 90 and s["stage"] == 3
    pay = lb.schedule(loan, ev)["installment"].iloc[:6].sum()
    lb.add_event(lid, username="o", role="officer", kind="payment", event_date=date.today(), amount=float(pay))
    s2 = lb.snapshot(loan, lb.events_for(lid), date.today())
    assert s2["dpd"] < s["dpd"] and s2["outstanding"] < loan["principal"]


def test_roles_and_validation(sandbox):
    from src import loanbook as lb
    lid = _loan(lb)
    with pytest.raises(PermissionError):
        lb.add_event(lid, username="o", role="officer", kind="writeoff", event_date=date.today(), detail="x")
    with pytest.raises(ValueError):
        lb.add_event(lid, username="o", role="officer", kind="payment", event_date=date.today(), amount=0)
    with pytest.raises(ValueError):
        _loan(lb, principal=-1)
    lb.add_event(lid, username="r", role="risk", kind="writeoff", event_date=date.today(), detail="uncollectable")
    assert lb.snapshot(lb.get_loan(lid), lb.events_for(lid), date.today())["status"] == "Written off"
    with pytest.raises(ValueError):
        lb.add_event(lid, username="o", role="officer", kind="note", event_date=date.today(), detail="late")


def test_loan_tables_append_only(sandbox):
    import sqlite3
    from src import loanbook as lb
    lid = _loan(lb)
    conn = lb._conn()
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM loans WHERE loan_id=?", (lid,))
    conn.close()


def test_portfolio_reports_and_alerts(sandbox):
    from src import loanbook as lb, policy_store, reports
    _loan(lb); _loan(lb, customer_ref="C2", area="south", disbursed_on=date.today() - timedelta(days=20),
                    first_due_on=date.today() + timedelta(days=10))
    book = lb.portfolio(date.today())
    s = policy_store.Settings()
    summ = lb.portfolio_summary(book, s)
    assert summ["loans"] == 2 and summ["provision"] > 0
    assert lb.portfolio_summary(book, s, 2.0, 0.2)["provision"] > summ["provision"]
    assert any("NPL" in m for _, m in lb.alerts(book, s))
    x = reports.portfolio_workbook(summ, book, lb.vintage_table(), lb.roll_rates(), lb.alerts(book, s), pd.DataFrame(), date.today())
    assert x[:2] == b"PK"


def test_documents(sandbox):
    from src import documents as d
    pdf = b"%PDF-1.4 test"
    i = d.attach("APP-1", pdf, "id.pdf", "Identity", "o", "officer")
    data, _, mime = d.read(i)
    assert data == pdf and mime == "application/pdf"
    with pytest.raises(ValueError):
        d.attach("APP-1", b"MZ not a pdf", "evil.pdf", "Other", "o", "officer")
    with pytest.raises(ValueError):
        d.attach("APP-1", pdf, "x.exe", "Other", "o", "officer")


def test_backup_roundtrip(sandbox):
    from src import audit, backup
    audit.log_event("u", "admin", "x", "before")
    blob = backup.create("a-long-passphrase-123", "u", "admin")
    assert b"before" not in blob
    with pytest.raises(Exception):
        backup.inspect(blob, "wrong-passphrase-123")
    with pytest.raises(ValueError):
        backup.create("short", "u", "admin")
    assert backup.inspect(blob, "a-long-passphrase-123")


def test_decision_pdf(sandbox):
    from src import reports
    b = reports.customer_letter_pdf(outcome="Decline", customer_ref="C1", reasons=["Debt burden is high"])
    assert b[:4] == b"%PDF"


def test_loan_book_page_with_data(sandbox):
    from datetime import date, timedelta
    from src import loanbook as lb
    from tests.test_pages import page
    _loan(lb); _loan(lb, customer_ref="C2", area="south")
    at = page("loan_book").run()
    assert not at.exception
    assert any("Active loans" in m.value for m in at.markdown)
