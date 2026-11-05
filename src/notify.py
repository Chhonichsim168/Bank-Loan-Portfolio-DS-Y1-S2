"""
notify.py
=========
Emails to customers (only when an email sender is set up in .streamlit/secrets.toml, see mailer.py):

* payment received (with the new balance)          * loan request approved / declined / money issued
* payment due in the next 3 days (once per due date) * payment overdue (at most once a week)
* a loan was linked to the account                  * a reported payment was confirmed or rejected

Every email has a key in the ``customer_email_log`` table, so the same message is never sent twice.
Nothing here can break a page: every function swallows its own errors and returns True/False.
"""
from __future__ import annotations

import html
import time

from src import audit, auth, loanbook

SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_email_log (
    key TEXT PRIMARY KEY, username TEXT NOT NULL, email TEXT NOT NULL, subject TEXT NOT NULL, sent_at TEXT NOT NULL
);
"""
_last_daily = [0.0]
DAILY_EVERY_SECONDS = 30 * 60


def _conn():
    conn = loanbook._conn()
    conn.executescript(SCHEMA)
    return conn


def email_of(username: str) -> str:
    info = auth.account_email(username)
    if info["email"]:
        return info["email"]
    conn = _conn()
    try:
        conn.executescript("CREATE TABLE IF NOT EXISTS customer_profiles (username TEXT PRIMARY KEY, full_name TEXT, "
                           "phone TEXT, email TEXT, location TEXT, updated_at TEXT)")
        row = conn.execute("SELECT email FROM customer_profiles WHERE username=?", (username,)).fetchone()
        return auth.normalize_email(row[0]) if row and row[0] else ""
    finally:
        conn.close()


def _name(username: str) -> str:
    return (auth._read_users().get(username) or {}).get("display_name") or username


def send_once(key: str, username: str, subject: str, lines: list[str]) -> bool:
    """Send one email unless ``key`` was sent before. True when sent now."""
    from src import mailer
    try:
        if not mailer.configured():
            return False
        to = email_of(username)
        if not to:
            return False
        conn = _conn()
        try:
            if conn.execute("SELECT 1 FROM customer_email_log WHERE key=?", (key,)).fetchone():
                return False
        finally:
            conn.close()
        body = [f"Hello {_name(username)},", ""] + lines + ["", "Credit Desk", "This is an automatic message."]
        text = "\n".join(body)
        page = "".join(f"<p style='margin:0 0 10px'>{html.escape(x)}</p>" if x else "" for x in body)
        mailer.send(to, subject, text, f"<div style='font-family:Segoe UI,Arial,sans-serif;font-size:15px;"
                                       f"line-height:1.5;color:#1B2430;max-width:520px'>{page}</div>")
        conn = _conn()
        try:
            conn.execute("INSERT OR IGNORE INTO customer_email_log VALUES (?,?,?,?,?)",
                         (key, username, to, subject, audit._now()))
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception as exc:                                  # an email must never break a page
        audit.log_event("system", "system", "email_failed", f"{key}: {exc}"[:300], strict=False)
        return False


def money(x) -> str:
    return f"${float(x):,.2f}"


# ---- events -------------------------------------------------------------------------------
def payment_received(username: str, loan_id: str, amount: float, ref: str, event_id: int | None = None) -> bool:
    from src.data_pipeline import today_local
    loan = loanbook.get_loan(loan_id) or {}
    snap = loanbook.snapshot(loan, loanbook.events_for(loan_id), today_local().date()) if loan else {}
    lines = [f"We received your payment of {money(amount)} for loan {loan_id} (reference {ref}).",
             f"Still overdue: {money(snap.get('arrears', 0))}." if snap.get("arrears", 0) > 0.004 else
             "Your loan is up to date. Thank you!"]
    if snap.get("status") == "Active" and snap.get("next_due"):
        lines.append(f"Next payment: {money(snap['next_amount'])} on {snap['next_due']:%d/%m/%Y}.")
    elif snap.get("status") == "Closed":
        lines.append("Your loan is now fully repaid. Your pay-off letter is in My documents.")
    lines.append("Your PDF receipt is in My documents in the Credit Desk portal.")
    return send_once(f"paid:{loan_id}:{event_id or ref}", username, f"Payment received - {money(amount)}", lines)


def request_decision(request_id: str, stage: str) -> bool:
    """stage: approved | declined | issued"""
    conn = _conn()
    try:
        cur = conn.execute("SELECT * FROM customer_requests WHERE request_id=?", (request_id,))
        row = cur.fetchone()
        if not row:
            return False
        r = dict(zip([c[0] for c in cur.description], row))
        link = conn.execute("SELECT loan_id FROM customer_loan_links WHERE request_id=?", (request_id,)).fetchone()
    finally:
        conn.close()
    if stage == "approved":
        subject = "Your loan request is approved"
        lines = [f"Good news: your request {request_id} is approved for {money(r['approved_amount'] or 0)} "
                 f"over {int(r['approved_term'] or 0)} months.",
                 "A second bank officer makes the final check (four-eyes rule) before the money is issued.",
                 f"Message from the bank: {r['explanation']}"]
    elif stage == "declined":
        subject = "About your loan request"
        lines = [f"We are sorry: your request {request_id} was not approved.", f"Reason: {r['explanation']}",
                 "You can reply in Messages if you have questions."]
    else:
        subject = "Your loan money has been issued"
        lines = [f"The money for request {request_id} has been issued" + (f" as loan {link[0]}." if link else "."),
                 "Your repayment schedule and first due date are in the Credit Desk portal."]
    return send_once(f"req:{request_id}:{stage}", r["username"], subject, lines)


def loans_linked(username: str, loan_ids: list[str]) -> bool:
    return send_once(f"linked:{username}:{','.join(sorted(loan_ids))}", username, "Your loan is now in Credit Desk",
                     [f"Loan {', '.join(loan_ids)} is now linked to your Credit Desk account.",
                      "Sign in to see your balance, schedule and receipts, and to pay by KHQR."])


def payment_report_reviewed(username: str, report_id: str, confirmed: bool, amount: float, note: str) -> bool:
    if confirmed:
        lines = [f"We confirmed your payment of {money(amount)} ({report_id}). It is now on your loan.",
                 "Your receipt is in My documents."]
    else:
        lines = [f"We could not confirm your payment report {report_id} ({money(amount)}).", f"Note: {note}",
                 "Please reply in Messages so we can check it together."]
    return send_once(f"report:{report_id}", username,
                     "Payment confirmed" if confirmed else "We could not confirm your payment", lines)


# ---- reminders ----------------------------------------------------------------------------
def due_reminders() -> int:
    """Due in 0-3 days (once per due date) and overdue (at most once a week). Returns emails sent."""
    from src.data_pipeline import today_local
    today = today_local().date()
    conn = _conn()
    try:
        conn.executescript("CREATE TABLE IF NOT EXISTS customer_loan_links (loan_id TEXT PRIMARY KEY, username TEXT, "
                           "request_id TEXT, linked_by TEXT, linked_at TEXT)")
        links = conn.execute("SELECT loan_id, username FROM customer_loan_links").fetchall()
    finally:
        conn.close()
    sent = 0
    for lid, username in links:
        try:
            loan = loanbook.get_loan(lid)
            snap = loanbook.snapshot(loan, loanbook.events_for(lid), today)
        except Exception:
            continue
        if snap["status"] != "Active":
            continue
        if snap["arrears"] > 0.004:
            week = today.isocalendar()
            sent += send_once(f"late:{lid}:{week[0]}-{week[1]}", username, "Your loan payment is overdue",
                              [f"Loan {lid} has {money(snap['arrears'])} overdue ({snap['dpd']} days late).",
                               "Please pay as soon as you can in the Credit Desk portal (Pay > KHQR).",
                               "Having difficulty? Reply in Messages - the bank can discuss a new date."])
        elif snap["next_due"] is not None and 0 <= (snap["next_due"] - today).days <= 3:
            days = (snap["next_due"] - today).days
            when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
            sent += send_once(f"due:{lid}:{snap['next_due']}", username, f"Reminder: payment due {when}",
                              [f"Your payment of {money(snap['next_amount'])} for loan {lid} is due {when} "
                               f"({snap['next_due']:%d/%m/%Y}).",
                               "Pay in the Credit Desk portal with KHQR - it takes less than a minute."])
    return sent


def run_daily() -> None:
    """Called on page loads; does the reminder round at most every 30 minutes per server."""
    from src import mailer
    if time.time() - _last_daily[0] < DAILY_EVERY_SECONDS or not mailer.configured():
        return
    _last_daily[0] = time.time()
    try:
        due_reminders()
    except Exception as exc:
        audit.log_event("system", "system", "email_failed", f"reminders: {exc}"[:300], strict=False)
