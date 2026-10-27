"""v22: follow-up tags, Paid button, shared history, new-record dots, no documents on Loan book / queue."""
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_v18 import PAGE, ROOT, _loan, model, seeded  # noqa: F401  (fixtures)


def _page(mod="loan_book", role="officer"):
    return AppTest.from_string(PAGE.format(root=ROOT, mod=mod, role=role, user=role), default_timeout=300)


def test_follow_up_tags_come_from_the_latest_record(sandbox):
    from src import loanbook, notifications
    from views.loan_book import follow_up_tags
    a = _loan("A-NOCALL", -40)
    b = _loan("B-PROMISE", -40)
    c = _loan("C-NOTE", -40)
    today = date.today()
    loanbook.add_event(b, username="o", role="officer", kind="promise", event_date=today, detail="pay on 30th")
    loanbook.add_event(c, username="o", role="officer", kind="note", event_date=today, detail="no answer")
    late = notifications.overdue(loanbook.portfolio(today), today)
    tags = follow_up_tags(late)
    assert tags[a] == "Not contacted yet"
    assert tags[b] == "Promised - not paid yet"
    assert tags[c] == "Contacted - not paid yet"
    # a promise or a note never takes the customer off the list
    assert {a, b, c} <= set(late["loan_id"])


def test_part_payment_is_tagged_and_stays_late(sandbox):
    from src import loanbook, notifications
    from views.loan_book import follow_up_tags
    lid = _loan("D-PART", -40)
    today = date.today()
    loanbook.add_event(lid, username="o", role="officer", kind="payment", event_date=today, amount=10)
    late = notifications.overdue(loanbook.portfolio(today), today)
    assert lid in set(late["loan_id"])
    assert follow_up_tags(late)[lid] == "Part-paid - still overdue"


def test_paid_records_the_overdue_amount_and_removes_the_customer(sandbox):
    from src import auth, loanbook, notifications
    lid = _loan("E-PAID", -40)
    today = date.today()
    owed = round(float(loanbook.snapshot(loanbook.get_loan(lid), loanbook.events_for(lid), today)["arrears"]), 2)
    assert owed > 0
    user = auth.User("officer", "Officer", "officer")
    loanbook.add_event(lid, username=user.username, role=user.role, kind="payment", event_date=today, amount=owed,
                       detail="Paid - overdue amount received in full")
    late = notifications.overdue(loanbook.portfolio(today), today)
    assert lid not in set(late["loan_id"])


def test_paid_button_is_shown_in_the_late_tab_history(seeded):
    at = _page().run()
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(m.value for m in at.markdown)
    assert "History of" in text
    labels = [b.label for b in at.button]
    assert any(l.startswith("Confirm:") for l in labels)       # inside the Paid pop-over


def test_new_record_counts_after_baseline(sandbox):
    from src import loanbook
    import time
    lid = _loan("G-NEW", -40)
    loanbook.unseen_loans("u2")
    time.sleep(1.1)                                            # timestamps are to the second
    loanbook.add_event(lid, username="o", role="officer", kind="promise", event_date=date.today(), detail="x")
    assert loanbook.unseen_loans("u2") == {lid: 1}
    loanbook.mark_seen("u2", lid)
    assert loanbook.unseen_loans("u2") == {}
    assert loanbook.unseen_loans("someone_else") == {}         # per user


def test_supporting_documents_removed_from_loan_book_and_queue():
    for f in ("loan_book.py", "queue.py"):
        src = (ROOT / "views" / f).read_text(encoding="utf-8")
        assert "render_documents" not in src
    assert "render_documents(" in (ROOT / "views" / "underwrite.py").read_text(encoding="utf-8")
