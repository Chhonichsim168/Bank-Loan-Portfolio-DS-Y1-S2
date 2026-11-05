"""
sample_customers.py
===================
Two ready-made CUSTOMER accounts for the customer portal demo, each with a real loan in the
Loan book, a payment history and a profile - one who is LATE and one who always pays ON TIME.

    Chhonich Sim  chhonichsim1@gmail.com  username chhonich  password customer123  -> late
    Cich Sim      cichsim@gmail.com       username cichsim   password customer123  -> on time

Both emails are verified, so each person can also press "Continue with Google" with that Gmail,
or use "Forgot password?" to get a code by email. Dates are counted back from TODAY so the late
customer is always about 35 days late whatever day the demo is run.

Runs on every start but only creates what is missing (it looks the accounts up by email), so it
is safe to keep on. Switched off together with the other samples by CREDIT_DESK_SAMPLE_DATA=0.
"""
from __future__ import annotations

import os
from datetime import date

from src import audit, auth, loanbook

PASSWORD = "customer123"
STAFF = ("officer", "officer")

CUSTOMERS = [
    {"email": "chhonichsim1@gmail.com", "username": "chhonich", "name": "Chhonich Sim", "late": True,
     "phone": "012 345 678", "location": "Sen Sok, Phnom Penh", "ref": "CUST-CHHONICH",
     "product": "Personal", "principal": 3000.0, "rate": 0.125, "term": 24, "months_ago": 7,
     "paid": 5, "collateral": 0.0, "area": "urban", "employment": "salaried",
     "request": ("Housing", 6000.0, 36, "Repair the roof of my house before the rainy season.")},
    {"email": "cichsim@gmail.com", "username": "cichsim", "name": "Cich Sim", "late": False,
     "phone": "098 765 432", "location": "Chbar Ampov, Phnom Penh", "ref": "CUST-CICHSIM",
     "product": "Vehicle", "principal": 8000.0, "rate": 0.10, "term": 36, "months_ago": 13,
     "paid": 13, "collateral": 9500.0, "area": "semiurban", "employment": "self_employed",
     "request": None},
]


def enabled() -> bool:
    return os.environ.get("CREDIT_DESK_SAMPLE_DATA", "1").strip().lower() not in {"0", "false", "no", "off"}


def _months_back(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 - n, 12)
    year, month = d.year + y, m + 1
    import calendar
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _ensure_account(c: dict) -> str:
    username = auth.find_username_by_email(c["email"])
    if username:
        return username
    username = c["username"]
    if username in auth._read_users():
        username = auth._free_username(auth._read_users(), c["email"])
    auth.create_user(username, c["name"], "customer", PASSWORD, must_change=False, actor="sample-data",
                     email=c["email"], email_verified=True)
    return username


def _owned_loans(conn, username: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM customer_loan_links WHERE username=?", (username,)).fetchone()[0]


def _ensure_profile(conn, c: dict, username: str) -> None:
    conn.execute("INSERT OR IGNORE INTO customer_profiles VALUES (?,?,?,?,?,?)",
                 (username, c["name"], c["phone"], c["email"], c["location"], audit._now()))


def _ensure_request(conn, c: dict, username: str) -> None:
    if not c["request"] or conn.execute("SELECT 1 FROM customer_requests WHERE username=?", (username,)).fetchone():
        return
    product, amount, term, purpose = c["request"]
    rid = f"REQ-{username.upper()[:6]}-1"
    conn.execute("INSERT OR IGNORE INTO customer_requests (request_id,username,amount,term_months,product,purpose,"
                 "submitted_at) VALUES (?,?,?,?,?,?,?)", (rid, username, amount, term, product, purpose, audit._now()))


def ensure() -> list[str]:
    """Create whatever is missing. Returns the usernames of the sample customers."""
    if not enabled():
        return []
    from src import customer_portal
    from src.data_pipeline import today_local
    auth.ensure_bootstrap()          # staff accounts first, or a fresh install would get none
    today = today_local().date()
    names = []
    for c in CUSTOMERS:
        try:
            username = _ensure_account(c)
            conn = customer_portal.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                _ensure_profile(conn, c, username)
                _ensure_request(conn, c, username)
                conn.execute("COMMIT")
            finally:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                conn.close()
            conn = customer_portal.connect()
            try:
                if not _owned_loans(conn, username):
                    conn.close()
                    conn = None
                    _create_and_link(c, username, today)
            finally:
                if conn is not None:
                    conn.close()
            names.append(username)
        except Exception as exc:                      # samples must never stop the app
            audit.log_event("sample-data", "system", "sample_customer_failed", f"{c['email']}: {exc}", strict=False)
    return names


def _create_and_link(c: dict, username: str, today: date) -> None:
    from src import customer_portal
    conn = customer_portal.connect()
    try:
        # loanbook writes through its own connection; the link row is written after the loan exists.
        disbursed = _months_back(today, c["months_ago"])
        first_due = _months_back(today, c["months_ago"] - 1)
        lid = loanbook.create_loan(username=STAFF[0], role=STAFF[1], customer_ref=c["ref"], product=c["product"],
                                   principal=c["principal"], annual_rate=c["rate"], term_months=c["term"],
                                   disbursed_on=disbursed, first_due_on=first_due,
                                   collateral_value=c["collateral"],
                                   band="Review" if c["late"] else "Low risk", area=c["area"],
                                   employment=c["employment"])
        loan = loanbook.get_loan(lid)
        sched = loanbook.schedule(loan, loanbook.events_for(lid)).reset_index(drop=True)
        for row in sched.head(c["paid"]).itertuples():
            if row.due_date > today:
                break
            paid_on = row.due_date if c["late"] else max(disbursed, date.fromordinal(row.due_date.toordinal() - 2))
            loanbook.add_event(lid, username=STAFF[0], role=STAFF[1], kind="payment", event_date=paid_on,
                               amount=round(float(row.installment), 2), detail="Sample data - KHQR payment")
        if c["late"]:
            loanbook.add_event(lid, username=STAFF[0], role=STAFF[1], kind="note", event_date=today,
                               detail="Sample data - called the customer, no answer.")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO customer_loan_links VALUES (?,?,NULL,?,?)",
                     (lid, username, "sample-data", audit._now()))
        conn.execute("COMMIT")
        audit.log_event("sample-data", "system", "customer_loan_linked", f"{lid}: {username} (sample)", strict=False)
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()
