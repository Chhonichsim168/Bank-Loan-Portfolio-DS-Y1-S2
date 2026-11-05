"""Exercise ownership, decisions, issuance and rollback in an isolated database."""
from datetime import timedelta

import pytest
import pandas as pd

from src import audit, auth, customer_portal as portal, loanbook
from src.data_pipeline import today_local


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "DB_PATH", tmp_path / "portal.db")
    monkeypatch.setattr(audit, "FALLBACK_PATH", tmp_path / "fallback.jsonl")
    monkeypatch.setattr(auth, "USERS_FILE", tmp_path / "users.json")
    actor = [auth.User("alice", "Alice", "customer")]
    monkeypatch.setattr(auth, "current_user", lambda: actor[0])
    monkeypatch.setattr(portal, "customer_accounts", lambda: [
        {"username":"alice"}, {"username":"bob"}])
    return actor


def apply(actor):
    actor[0] = auth.User("alice", "Alice", "customer")
    portal.save_profile("Alice", "012345678", "", "Phnom Penh")
    return portal.submit_request(1200, 12, "Personal", "Education")


def staff(actor):
    actor[0] = auth.User("employee", "Employee", "officer")


def second(actor, rid):
    """Four-eyes: a different Risk Manager gives the second approval, then the officer continues."""
    actor[0] = auth.User("riskmgr", "Risk Manager", "risk")
    portal.second_approve(rid, "Checked independently")
    actor[0] = auth.User("employee", "Employee", "officer")


def test_request_review_issue_and_owner_privacy(env):
    rid = apply(env)
    assert portal.requests().iloc[0].status == "Pending review"
    assert portal.my_loans().empty
    with pytest.raises(PermissionError):
        portal.review(rid, "Approved", "Approved", 1200, .12, 12)
    staff(env)
    with pytest.raises(ValueError):
        portal.issue_loan(rid, today_local().date(), today_local().date() + timedelta(days=30))
    portal.review(rid, "Approved", "Income reviewed", 1000, .12, 12)
    assert portal.requests().iloc[0].decision_at
    with pytest.raises(ValueError):
        portal.review(rid, "Declined", "Stale review")
    today = today_local().date()
    with pytest.raises(ValueError, match="Four-eyes"):
        portal.issue_loan(rid, today, today + timedelta(days=30))     # one approval is not enough
    with pytest.raises(PermissionError):
        portal.second_approve(rid, "self")                             # an officer cannot second-approve
    env[0] = auth.User("employee", "Employee", "risk")
    with pytest.raises(PermissionError):
        portal.second_approve(rid, "same person")                      # nor can the first reviewer
    second(env, rid)
    with pytest.raises(ValueError):
        second(env, rid)                                               # only once
    lid = portal.issue_loan(rid, today, today + timedelta(days=30))
    assert portal.requests().iloc[0].second_approver == "riskmgr"
    with pytest.raises(ValueError):
        portal.issue_loan(rid, today, today + timedelta(days=30))
    loanbook.add_event(lid, username="employee", role="officer", kind="note",
                       event_date=today, detail="Internal confidential note")
    loanbook.add_event(lid, username="employee", role="officer", kind="payment", event_date=today, amount=50)
    env[0] = auth.User("alice", "Alice", "customer")
    loan, snap, schedule, payments = portal.loan_details(lid)
    assert len(portal.my_loans()) == 1
    assert loan["principal"] == 1000
    assert snap["paid"] == 50
    assert snap["principal_balance"] == pytest.approx(960)
    assert snap["next_amount"] == pytest.approx(schedule.iloc[0].installment - 50)
    assert list(payments.columns) == ["id", "event_date", "amount", "principal_paid", "interest_paid", "unallocated"]
    assert payments.iloc[0].principal_paid == 40
    assert payments.iloc[0].interest_paid == 10
    assert len(payments) == 1
    payment_id = int(payments.iloc[0]["id"])
    assert portal.payment_receipt(lid, payment_id).startswith(b"%PDF-")
    assert portal.loan_statement(lid).startswith(b"%PDF-")
    env[0] = auth.User("bob", "Bob", "customer")
    assert portal.requests().empty
    assert portal.my_loans().empty
    assert portal.profile() == {}
    with pytest.raises(PermissionError):
        portal.loan_details(lid)
    with pytest.raises(PermissionError):
        portal.payment_receipt(lid, payment_id)
    with pytest.raises(PermissionError):
        portal.loan_statement(lid)
    assert audit.verify_chain()[0]


def test_decline_and_validation(env):
    with pytest.raises(ValueError):
        portal.submit_request(100, 12, "Personal", "Study")
    rid = apply(env)
    for amount, term in [(float("nan"),12), (-1,12), (100,0), (100,1.5)]:
        with pytest.raises(ValueError):
            portal.submit_request(amount, term, "Personal", "Study")
    staff(env)
    with pytest.raises(ValueError):
        portal.review(rid, "Approved", "OK", 1300, .12, 12)
    portal.review(rid, "Declined", "Insufficient repayment information")
    today = today_local().date()
    with pytest.raises(ValueError):
        portal.issue_loan(rid, today, today + timedelta(days=30))
    assert loanbook.list_loans().empty


def test_issuance_rolls_back_when_audit_fails(env, monkeypatch):
    rid = apply(env)
    staff(env)
    portal.review(rid, "Approved", "Verified", 1200, 0, 12)
    second(env, rid)
    def fail(*args, **kwargs):
        raise audit.AuditError("Audit unavailable")
    monkeypatch.setattr(audit, "append", fail)
    today = today_local().date()
    with pytest.raises(audit.AuditError):
        portal.issue_loan(rid, today, today + timedelta(days=30))
    assert loanbook.list_loans().empty
    assert portal.requests().iloc[0].loan_id is None


def test_link_existing_is_explicit_and_immutable(env):
    staff(env)
    today = today_local().date()
    lid = loanbook.create_loan(username="employee", role="officer", customer_ref="Alice old account",
        product="Personal", principal=300, annual_rate=0, term_months=3,
        disbursed_on=today, first_due_on=today + timedelta(days=30), collateral_value=0, band="Review")
    with pytest.raises(PermissionError):
        portal.link_existing(lid, "alice")                             # officers cannot link
    env[0] = auth.User("riskmgr", "Risk Manager", "risk")
    portal.link_existing(lid, "alice")
    with pytest.raises(ValueError):
        portal.link_existing(lid, "bob")
    env[0] = auth.User("bob", "Bob", "customer")
    with pytest.raises(PermissionError):
        portal.link_existing(lid, "bob")
    with pytest.raises(PermissionError):
        portal.unlinked_loans()
    env[0] = auth.User("alice", "Alice", "customer")
    assert portal.my_loans().iloc[0].loan_id == lid


def test_customer_navigation_is_allowlisted(monkeypatch):
    monkeypatch.setenv("CREDIT_DESK_REQUIRE_LOGIN", "1")
    assert auth.can_access("customer", "customer")
    assert auth.can_access("customer", "account")
    assert auth.can_access("customer", "profile")
    assert auth.can_access("customer", "notifications")
    assert auth.can_access("customer", "support")
    assert not auth.can_access("customer", "support_staff")
    for slug in ["overview", "loanbook", "requests", "users", "score", "data", "unknown-page"]:
        assert not auth.can_access("customer", slug)
    for role in portal.STAFF:
        assert auth.can_access(role, "requests")
        assert not auth.can_access(role, "customer")
        assert auth.can_access(role, "support_staff")


def test_notification_unread_state_is_persistent_and_private(env):
    rid = apply(env)
    initial = portal.my_notifications()
    assert len(initial) == 1 and initial[0]["unread"]
    portal.mark_notifications_read([initial[0]["id"]])
    assert not portal.my_notifications()[0]["unread"]
    staff(env)
    portal.review(rid, "Approved", "Reviewed", 1200, 0, 12)
    env[0] = auth.User("alice", "Alice", "customer")
    assert sum(n["unread"] for n in portal.my_notifications()) == 1
    env[0] = auth.User("bob", "Bob", "customer")
    assert portal.my_notifications() == []
    portal.mark_notifications_read([f"decision:{rid}"])
    env[0] = auth.User("alice", "Alice", "customer")
    assert sum(n["unread"] for n in portal.my_notifications()) == 1


def test_payment_breakdown_reconciles_partial_and_excess_payments():
    sched = loanbook._annuity(1000, .12, 12, today_local().date())
    payments = pd.DataFrame({"event_date": ["2026-07-30", "2026-08-30", "2026-09-30"],
                             "amount": [5.0, 45.0, 1300.0]})
    result = portal.payment_breakdown(sched, payments)
    assert result.iloc[0].principal_paid == 0
    assert result.iloc[0].interest_paid == 5
    assert result.iloc[1].principal_paid == 40
    assert result.iloc[1].interest_paid == 5
    assert result["principal_paid"].sum() == pytest.approx(1000)
    assert result["interest_paid"].sum() == pytest.approx(round(sched["interest"].sum(), 2))
    assert result["unallocated"].sum() > 0
    for row in result.itertuples():
        assert row.amount == pytest.approx(row.principal_paid + row.interest_paid + row.unallocated)
    zero_interest = loanbook._annuity(1200, 0, 12, today_local().date())
    result = portal.payment_breakdown(zero_interest, pd.DataFrame({"amount": [100., 100.]}))
    assert result["interest_paid"].sum() == 0
    assert result["principal_paid"].sum() == 200


def test_photo_validation_storage_and_privacy(env):
    import io
    from PIL import Image
    image = Image.new("RGB", (200, 300), (10, 100, 80))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    assert portal.profile_photo() is None
    portal.save_photo(buf.getvalue())
    photo = portal.profile_photo()
    with Image.open(io.BytesIO(photo)) as saved:
        assert saved.format == "JPEG" and saved.size == (512, 512)
        assert not saved.getexif()
    env[0] = auth.User("bob", "Bob", "customer")
    assert portal.profile_photo() is None
    for bad in [b"not an image", b"<svg>bad</svg>", b"x" * (5 * 1024 * 1024 + 1)]:
        with pytest.raises(ValueError):
            portal.save_photo(bad)
    env[0] = auth.User("employee", "Employee", "officer")
    with pytest.raises(PermissionError):
        portal.profile_photo()


def test_profile_and_photo_save_together_or_not_at_all(env, monkeypatch):
    import io
    from PIL import Image
    def photo_bytes(color):
        buf = io.BytesIO()
        Image.new("RGB", (100, 100), color).save(buf, format="PNG")
        return buf.getvalue()
    portal.save_profile("Alice", "012345678", "", "Phnom Penh", photo=photo_bytes("green"))
    saved_photo = portal.profile_photo()
    assert saved_photo and portal.profile()["full_name"] == "Alice"
    portal.save_profile("Alice Updated", "012345678", "", "Phnom Penh")
    assert portal.profile_photo() == saved_photo
    with pytest.raises(ValueError):
        portal.save_profile("Invalid change", "012345678", "", "Phnom Penh", photo=b"bad image")
    assert portal.profile()["full_name"] == "Alice Updated"
    def fail(*args, **kwargs):
        raise audit.AuditError("Cannot save audit record")
    monkeypatch.setattr(audit, "append", fail)
    with pytest.raises(audit.AuditError):
        portal.save_profile("Failed change", "012345678", "", "Phnom Penh", photo=photo_bytes("blue"))
    assert portal.profile()["full_name"] == "Alice Updated"
    assert portal.profile_photo() == saved_photo
