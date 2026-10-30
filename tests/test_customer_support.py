from datetime import timedelta

import pytest

from src import audit, auth, customer_portal as portal, customer_support as support
from src.data_pipeline import today_local


@pytest.fixture
def actors(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "DB_PATH", tmp_path / "support.db")
    monkeypatch.setattr(audit, "FALLBACK_PATH", tmp_path / "fallback.jsonl")
    actor = [auth.User("alice", "Alice", "customer")]
    monkeypatch.setattr(auth, "current_user", lambda: actor[0])
    portal.save_profile("Alice", "012345678", "", "Phnom Penh")
    return actor


def test_cancellation_is_owned_and_blocks_stale_review(actors):
    rid = portal.submit_request(1000, 12, "Personal", "Study")
    actors[0] = auth.User("bob", "Bob", "customer")
    with pytest.raises(PermissionError):
        portal.cancel_request(rid)
    actors[0] = auth.User("alice", "Alice", "customer")
    portal.cancel_request(rid)
    assert portal.requests().iloc[0].status == "Cancelled"
    assert portal.requests().iloc[0].cancelled_at
    assert any(n["title"] == "Loan request cancelled" for n in portal.my_notifications())
    with pytest.raises(ValueError):
        portal.cancel_request(rid)
    actors[0] = auth.User("employee", "Employee", "officer")
    with pytest.raises(ValueError):
        portal.review(rid, "Approved", "Stale review", 1000, .12, 12)
    with pytest.raises(ValueError):
        portal.issue_loan(rid, today_local().date(), today_local().date()+timedelta(days=30))
    assert portal.requests().iloc[0].status == "Cancelled"
    with pytest.raises(PermissionError):
        portal.cancel_request(rid)


def test_reviewed_request_cannot_be_cancelled(actors):
    rid = portal.submit_request(1000, 12, "Personal", "Study")
    actors[0] = auth.User("employee", "Employee", "officer")
    portal.review(rid, "Declined", "Insufficient information")
    actors[0] = auth.User("alice", "Alice", "customer")
    with pytest.raises(ValueError):
        portal.cancel_request(rid)


def test_support_is_private_persistent_and_notifies_on_staff_reply(actors):
    tid = support.create_ticket("Payment question", "Can I pay early?")
    assert support.tickets().iloc[0].status == "Open"
    actors[0] = auth.User("bob", "Bob", "customer")
    assert support.tickets().empty
    with pytest.raises(PermissionError):
        support.messages(tid)
    with pytest.raises(PermissionError):
        support.reply(tid, "Unrelated customer")
    assert support.reply_notifications() == []
    actors[0] = auth.User("employee", "Employee", "officer")
    assert len(support.tickets()) == 1
    support.reply(tid, "Yes, contact the loan team to arrange it.")
    support.set_status(tid, "Resolved")
    actors[0] = auth.User("alice", "Alice", "customer")
    assert len(support.messages(tid)) == 2
    assert support.tickets().iloc[0].status == "Resolved"
    notices = [n for n in portal.my_notifications() if n["id"].startswith("support:")]
    assert len(notices) == 1 and notices[0]["unread"]
    portal.mark_notifications_read([notices[0]["id"]])
    assert not [n for n in portal.my_notifications() if n["id"].startswith("support:")][0]["unread"]
    with pytest.raises(PermissionError):
        support.set_status(tid, "Resolved")
    support.reply(tid, "Thank you, I have another question.")
    assert support.tickets().iloc[0].status == "Open"
    assert audit.verify_chain()[0]


def test_support_rejects_invalid_input_and_rolls_back(actors, monkeypatch):
    with pytest.raises(ValueError):
        support.create_ticket("", "Message")
    with pytest.raises(ValueError):
        support.create_ticket("Question", " ")
    with pytest.raises(PermissionError):
        support.create_ticket("Question", "Message", loan_id="someone-elses-loan")
    def fail(*args, **kwargs):
        raise audit.AuditError("Audit unavailable")
    monkeypatch.setattr(audit, "append", fail)
    with pytest.raises(audit.AuditError):
        support.create_ticket("Question", "Message")
    assert support.tickets().empty
