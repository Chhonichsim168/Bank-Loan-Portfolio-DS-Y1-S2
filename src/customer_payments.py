"""Customer-reported payments become ledger entries only after staff confirmation."""
import math
import secrets
from datetime import date
from src import customer_portal as portal, audit

SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_payment_reports (
 report_id TEXT PRIMARY KEY, username TEXT NOT NULL, loan_id TEXT NOT NULL REFERENCES loans(loan_id),
 amount REAL NOT NULL CHECK(amount>0), payment_date TEXT NOT NULL, reference TEXT NOT NULL,
 submitted_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Confirmed','Rejected')),
 reviewed_by TEXT NOT NULL DEFAULT '', reviewed_at TEXT NOT NULL DEFAULT '', review_note TEXT NOT NULL DEFAULT '',
 event_id INTEGER UNIQUE REFERENCES loan_events(id), UNIQUE(loan_id,reference)
);
"""

def initialize():
    conn = portal.connect()
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()

def reports():
    import pandas as pd
    user = portal.require_role("customer", *portal.STAFF)
    initialize()
    conn = portal.connect()
    try:
        where, params = (" WHERE username=?", (user.username,)) if user.role == "customer" else ("", ())
        return pd.read_sql_query("SELECT * FROM customer_payment_reports" + where + " ORDER BY submitted_at DESC", conn, params=params)
    finally:
        conn.close()

def submit(loan_id, amount, payment_date, reference):
    user = portal.require_role("customer")
    loan, snap, _, _ = portal.loan_details(loan_id)
    if snap["status"] != "Active":
        raise ValueError("Only active loans can receive payment reports.")
    amount = float(amount)
    if not math.isfinite(amount) or amount <= 0 or amount > 1_000_000_000 or abs(amount-round(amount,2)) > .000001:
        raise ValueError("Enter a positive payment amount with at most two decimal places.")
    from src.data_pipeline import today_local
    paid_on = date.fromisoformat(str(payment_date))
    if not date.fromisoformat(loan["disbursed_on"]) <= paid_on <= today_local().date():
        raise ValueError("Payment date must be between disbursement and today.")
    reference = str(reference).strip()
    if not reference or len(reference)>120:
        raise ValueError("Enter the transfer or receipt reference (up to 120 characters).")
    initialize()
    rid = "PMT-" + secrets.token_hex(5).upper()
    with portal.transaction("customer_payment_reported", rid) as conn:
        if conn.execute("SELECT 1 FROM customer_payment_reports WHERE loan_id=? AND reference=?", (loan_id,reference)).fetchone():
            raise ValueError("This payment reference was already submitted for this loan.")
        conn.execute("INSERT INTO customer_payment_reports (report_id,username,loan_id,amount,payment_date,reference,submitted_at) VALUES (?,?,?,?,?,?,?)",
                     (rid,user.username,loan_id,amount,paid_on.isoformat(),reference,audit._now()))
    return rid

def review(report_id, confirm, note):
    user = portal.require_role(*portal.STAFF)
    note = str(note).strip()
    if not note or len(note)>1000:
        raise ValueError("Enter verification or rejection notes (up to 1,000 characters).")
    initialize()
    with portal.transaction("customer_payment_reviewed", report_id) as conn:
        cur = conn.execute("SELECT * FROM customer_payment_reports WHERE report_id=?", (report_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Payment report not found.")
        report = dict(zip([col[0] for col in cur.description], row))
        if report["status"] != "Pending":
            raise ValueError("This payment report was already reviewed.")
        if report["username"] == user.username:
            raise PermissionError("You cannot confirm your own payment report.")
        event_id = None
        if confirm:
            from src import loanbook
            import pandas as pd
            cur = conn.execute("SELECT * FROM loans WHERE loan_id=?", (report["loan_id"],))
            row = cur.fetchone()
            loan = dict(zip([col[0] for col in cur.description],row))
            events = pd.read_sql_query("SELECT * FROM loan_events WHERE loan_id=? ORDER BY id",conn,params=(report["loan_id"],))
            from src.data_pipeline import today_local
            if loanbook.snapshot(loan,events,today_local().date())["status"] != "Active":
                raise ValueError("This loan is no longer active. Review the report with the loan team.")
            event_id = conn.execute("INSERT INTO loan_events (loan_id,ts,username,role,kind,event_date,amount,detail,payload) VALUES (?,?,?,?,?,?,?,?,?)",
                (report["loan_id"],audit._now(),user.username,user.role,"payment",report["payment_date"],report["amount"],
                 "Verified payment report " + report_id + " / " + report["reference"],"{}")).lastrowid
        conn.execute("UPDATE customer_payment_reports SET status=?,reviewed_by=?,reviewed_at=?,review_note=?,event_id=? WHERE report_id=?",
            ("Confirmed" if confirm else "Rejected",user.username,audit._now(),note,event_id,report_id))
    from src import notify
    notify.payment_report_reviewed(report["username"], report_id, bool(confirm), report["amount"], note)
