"""Customer-owned profiles, requests and explicit employee-controlled loan links.

No loan is claimed by matching a name or a customer-supplied reference. Every
customer query is scoped to the authenticated account, before data leaves SQL.
"""
from __future__ import annotations

import math
import json
import secrets
import io
from contextlib import contextmanager

import pandas as pd

from src import audit, auth, loanbook, customer_undo
from src.data_pipeline import today_local

STAFF = {"admin", "risk", "officer"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_application_drafts (
    username TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_request_estimates (
    request_id TEXT PRIMARY KEY REFERENCES customer_requests(request_id),
    rate_percent REAL NOT NULL, interest_method TEXT NOT NULL,
    total_interest REAL NOT NULL, total_repayment REAL NOT NULL,
    monthly_payment REAL NOT NULL, final_payment REAL NOT NULL, saved_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_profiles (
    username TEXT PRIMARY KEY, full_name TEXT NOT NULL, phone TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '', location TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_requests (
    request_id TEXT PRIMARY KEY, username TEXT NOT NULL, amount REAL NOT NULL CHECK(amount > 0),
    term_months INTEGER NOT NULL CHECK(term_months > 0), product TEXT NOT NULL,
    purpose TEXT NOT NULL, submitted_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending review' CHECK(status IN ('Pending review','Approved','Declined')),
    decision_at TEXT NOT NULL DEFAULT '', reviewed_by TEXT NOT NULL DEFAULT '',
    explanation TEXT NOT NULL DEFAULT '', approved_amount REAL, approved_rate REAL,
    approved_term INTEGER
);
CREATE INDEX IF NOT EXISTS customer_requests_owner ON customer_requests(username);
CREATE TABLE IF NOT EXISTS customer_request_cancellations (
    request_id TEXT PRIMARY KEY REFERENCES customer_requests(request_id),
    cancelled_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_loan_links (
    loan_id TEXT PRIMARY KEY REFERENCES loans(loan_id), username TEXT NOT NULL,
    request_id TEXT UNIQUE REFERENCES customer_requests(request_id),
    linked_by TEXT NOT NULL, linked_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS customer_loans_owner ON customer_loan_links(username);
CREATE TABLE IF NOT EXISTS customer_notifications_read (
    username TEXT NOT NULL, notification_id TEXT NOT NULL, read_at TEXT NOT NULL,
    PRIMARY KEY(username, notification_id)
);
CREATE TABLE IF NOT EXISTS customer_photos (
    username TEXT PRIMARY KEY, image BLOB NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_request_second_approvals (
    request_id TEXT PRIMARY KEY REFERENCES customer_requests(request_id),
    approver TEXT NOT NULL, approver_role TEXT NOT NULL, note TEXT NOT NULL, approved_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS customer_links_no_update BEFORE UPDATE ON customer_loan_links
BEGIN SELECT RAISE(ABORT, 'customer loan ownership is immutable'); END;
CREATE TRIGGER IF NOT EXISTS customer_links_no_delete BEFORE DELETE ON customer_loan_links
BEGIN SELECT RAISE(ABORT, 'customer loan ownership is immutable'); END;
"""


def require_role(*roles):
    user = auth.current_user()
    if user is None or user.role not in roles:
        raise PermissionError("You do not have permission for this action.")
    return user


def connect():
    conn = loanbook._conn()
    conn.executescript(SCHEMA)
    conn.executescript(customer_undo.SCHEMA)
    return conn


@contextmanager
def transaction(action, detail):
    user = auth.current_user()
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        audit.append(conn, user.username, user.role, action, detail)
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def profile():
    user = require_role("customer", *STAFF)
    conn = connect()
    try:
        cur = conn.execute("SELECT * FROM customer_profiles WHERE username=?", (user.username,))
        row = cur.fetchone()
        return dict(zip([c[0] for c in cur.description], row)) if row else {}
    finally:
        conn.close()


def save_profile(full_name, phone, email, location, photo=None):
    user = require_role("customer", *STAFF)
    fields = [str(v).strip() for v in (full_name, phone, email, location)]
    missing = [label for label, value in zip(("Full name", "Phone number", "Email", "Location / address"), fields)
               if not value and label != "Email"]
    if missing:
        raise ValueError("Complete these required fields: " + ", ".join(missing) + ".")
    if any(len(v) > 300 for v in fields):
        raise ValueError("Keep each field within 300 characters.")
    if fields[2] and ("@" not in fields[2] or "." not in fields[2].split("@")[-1]):
        raise ValueError("Enter a valid email address or leave it empty.")
    image = prepare_photo(photo) if photo is not None else None
    with transaction("customer_profile_saved", user.username) as conn:
        before = customer_undo.profile_state(conn,user.username)
        conn.execute("INSERT INTO customer_profiles VALUES (?,?,?,?,?,?) "
                     "ON CONFLICT(username) DO UPDATE SET full_name=excluded.full_name, "
                     "phone=excluded.phone,email=excluded.email,location=excluded.location, "
                     "updated_at=excluded.updated_at", (user.username, *fields, audit._now()))
        if image is not None:
            conn.execute("INSERT INTO customer_photos VALUES (?,?,?) ON CONFLICT(username) "
                         "DO UPDATE SET image=excluded.image,updated_at=excluded.updated_at",
                         (user.username, image, audit._now()))

        customer_undo.record(conn,user.username,"profile","Profile edit",before,customer_undo.profile_state(conn,user.username))


def prepare_photo(data):
    """Decode and resize real images; discard original metadata and file names."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    if not data or len(data) > 5 * 1024 * 1024:
        raise ValueError("Choose a JPG, PNG or WebP image up to 5 MB.")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Choose a JPG, PNG or WebP image.")
            if source.width * source.height > 16_000_000:
                raise ValueError("Choose a photo with no more than 16 million pixels.")
            source.load()
            image = ImageOps.fit(ImageOps.exif_transpose(source).convert("RGB"), (512, 512))
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=88)
            return out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("This image could not be opened. Choose a valid JPG, PNG or WebP photo.") from exc


def save_photo(data):
    user = require_role("customer", *STAFF)
    image = prepare_photo(data)
    with transaction("customer_photo_saved", user.username) as conn:
        before=customer_undo.profile_state(conn,user.username)
        conn.execute("INSERT INTO customer_photos VALUES (?,?,?) ON CONFLICT(username) "
                     "DO UPDATE SET image=excluded.image,updated_at=excluded.updated_at",
                     (user.username, image, audit._now()))
        customer_undo.record(conn,user.username,"profile","Profile edit",before,customer_undo.profile_state(conn,user.username))


def profile_photo():
    user = require_role("customer", *STAFF)
    conn = connect()
    try:
        row = conn.execute("SELECT image FROM customer_photos WHERE username=?", (user.username,)).fetchone()
        return bytes(row[0]) if row else None
    finally:
        conn.close()


def estimate_terms(amount, term, rate_percent):
    from decimal import Decimal, ROUND_HALF_UP
    amount, rate_percent = float(amount), float(rate_percent)
    if not math.isfinite(amount) or not 0 < amount <= 1_000_000_000:
        raise ValueError("Enter a valid loan amount.")
    if int(term) != term or not 1 <= term <= 360:
        raise ValueError("Choose a term between 1 and 360 months.")
    if not math.isfinite(rate_percent) or not 0 <= rate_percent <= 100:
        raise ValueError("Choose an estimated rate between 0% and 100%.")
    cents = lambda n: n.quantize(Decimal(".01"),rounding=ROUND_HALF_UP)
    principal = cents(Decimal(str(amount)))
    interest = cents(principal * Decimal(str(rate_percent)) / 100)
    total = principal + interest
    monthly = cents(total / int(term))
    final = total - monthly * (int(term)-1)
    return dict(rate_percent=rate_percent,interest_method="flat_total",total_interest=float(interest),
                total_repayment=float(total),monthly_payment=float(monthly),final_payment=float(final))


def application_draft():
    user = require_role("customer")
    conn = connect()
    try:
        row = conn.execute("SELECT payload,updated_at FROM customer_application_drafts WHERE username=?",(user.username,)).fetchone()
        return dict(json.loads(row[0]),updated_at=row[1]) if row else None
    finally:
        conn.close()


def save_application_draft(amount, term, rate, product, purpose):
    user = require_role("customer")
    estimate_terms(amount,term,rate)
    if product not in loanbook.PRODUCTS or len(str(purpose))>2000:
        raise ValueError("Choose a loan product and keep the purpose within 2,000 characters.")
    payload = json.dumps(dict(amount=float(amount),term=int(term),rate=float(rate),product=product,purpose=str(purpose)))
    with transaction("application_draft_saved", user.username) as conn:
        before = customer_undo.draft_state(conn,user.username)
        if before and before[1] == payload:
            return
        conn.execute("INSERT INTO customer_application_drafts VALUES (?,?,?) ON CONFLICT(username) "
                     "DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",(user.username,payload,audit._now()))
        customer_undo.record(conn,user.username,"draft","Application draft",before,customer_undo.draft_state(conn,user.username))


def discard_application_draft():
    user = require_role("customer")
    with transaction("application_draft_discarded",user.username) as conn:
        before = customer_undo.draft_state(conn,user.username)
        conn.execute("DELETE FROM customer_application_drafts WHERE username=?",(user.username,))
        customer_undo.record(conn,user.username,"draft","Discarded draft",before,None)


def saved_request_estimate(request_id):
    user = require_role("customer", *STAFF)
    conn = connect()
    try:
        row = conn.execute("SELECT username FROM customer_requests WHERE request_id=?",(request_id,)).fetchone()
        if not row or (user.role == "customer" and row[0] != user.username):
            raise PermissionError("This request is not available to your account.")
        cur = conn.execute("SELECT * FROM customer_request_estimates WHERE request_id=?",(request_id,))
        row = cur.fetchone()
        return dict(zip([col[0] for col in cur.description],row)) if row else None
    finally:
        conn.close()


def submit_request(amount, term_months, product, purpose, estimated_rate=None):
    user = require_role("customer")
    if not profile():
        raise ValueError("Save your profile before requesting a loan.")
    amount = float(amount)
    if not math.isfinite(amount) or not 0 < amount <= 1_000_000_000:
        raise ValueError("Enter a valid loan amount between 0 and 1 billion.")
    if int(term_months) != term_months or not 1 <= term_months <= 360:
        raise ValueError("Choose a term between 1 and 360 months.")
    if product not in loanbook.PRODUCTS or not str(purpose).strip() or len(purpose) > 2000:
        raise ValueError("Choose a product and enter a purpose within 2,000 characters.")
    estimate = estimate_terms(amount,term_months,estimated_rate) if estimated_rate is not None else None
    rid = "CR-" + secrets.token_hex(6).upper()
    with transaction("customer_request_submitted", rid) as conn:
        previous_draft = customer_undo.draft_state(conn,user.username)
        conn.execute("INSERT INTO customer_requests "
                     "(request_id,username,amount,term_months,product,purpose,submitted_at) VALUES (?,?,?,?,?,?,?)",
                     (rid, user.username, amount, int(term_months), product, purpose.strip(), audit._now()))
        if estimate is not None:
            conn.execute("INSERT INTO customer_request_estimates VALUES (?,?,?,?,?,?,?,?)",
                (rid,estimate["rate_percent"],estimate["interest_method"],estimate["total_interest"],
                 estimate["total_repayment"],estimate["monthly_payment"],estimate["final_payment"],audit._now()))
        conn.execute("DELETE FROM customer_application_drafts WHERE username=?",(user.username,))
        customer_undo.record(conn,user.username,"request_submit","Submitted request",previous_draft,{"request":rid},rid)
    return rid


def requests():
    user = require_role("customer", *STAFF)
    conn = connect()
    try:
        where, params = ("WHERE r.username=?", (user.username,)) if user.role == "customer" else ("", ())
        result = pd.read_sql_query(
            "SELECT r.*, p.full_name,p.phone,p.email,p.location,l.loan_id,c.cancelled_at, "
            "s.approver AS second_approver, s.approved_at AS second_approved_at FROM customer_requests r "
            "LEFT JOIN customer_request_second_approvals s ON s.request_id=r.request_id "
            "LEFT JOIN customer_profiles p ON p.username=r.username "
            "LEFT JOIN customer_loan_links l ON l.request_id=r.request_id "
            "LEFT JOIN customer_request_cancellations c ON c.request_id=r.request_id "
            + where + " ORDER BY r.submitted_at DESC,r.request_id", conn, params=params)
        result.loc[result["cancelled_at"].notna(), "status"] = "Cancelled"
        return result
    finally:
        conn.close()


def cancel_request(request_id):
    user = require_role("customer")
    with transaction("customer_request_cancelled", request_id) as conn:
        row = conn.execute("SELECT status FROM customer_requests WHERE request_id=? AND username=?",
                           (request_id, user.username)).fetchone()
        if not row:
            raise PermissionError("This request is not available to your account.")
        if row[0] != "Pending review":
            raise ValueError("Only a request awaiting employee review can be cancelled.")
        if conn.execute("SELECT 1 FROM customer_request_cancellations WHERE request_id=?", (request_id,)).fetchone():
            raise ValueError("This request has already been cancelled.")
        conn.execute("INSERT INTO customer_request_cancellations VALUES (?,?)", (request_id, audit._now()))
        stamp = conn.execute("SELECT cancelled_at FROM customer_request_cancellations WHERE request_id=?",(request_id,)).fetchone()[0]
        customer_undo.record(conn,user.username,"request_cancel","Cancelled request",None,stamp,request_id)


def review(request_id, decision, explanation, amount=None, annual_rate=None, term=None):
    user = require_role(*STAFF)
    explanation = explanation.strip()
    if decision not in {"Approved", "Declined"} or not explanation or len(explanation) > 2000:
        raise ValueError("Choose Approved or Declined and give an explanation within 2,000 characters.")
    with transaction("customer_request_reviewed", f"{request_id}: {decision}") as conn:
        row = conn.execute("SELECT username,amount FROM customer_requests WHERE request_id=?",
                           (request_id,)).fetchone()
        if not row:
            raise ValueError("Request not found.")
        if row[0] == user.username:
            raise PermissionError("You cannot review your own customer request.")
        if decision == "Approved":
            if amount is None or not math.isfinite(float(amount)) or not 0 < amount <= row[1]:
                raise ValueError("Approved amount must be positive and no greater than requested.")
            if annual_rate is None or not math.isfinite(float(annual_rate)) or not 0 <= annual_rate <= 1:
                raise ValueError("Annual interest must be between 0% and 100%.")
            if term is None or int(term) != term or not 1 <= term <= 360:
                raise ValueError("Approved term must be between 1 and 360 months.")
        else:
            amount = annual_rate = term = None
        changed = conn.execute("UPDATE customer_requests SET status=?,decision_at=?,reviewed_by=?, "
                               "explanation=?,approved_amount=?,approved_rate=?,approved_term=? "
                               "WHERE request_id=? AND status='Pending review' AND NOT EXISTS "
                               "(SELECT 1 FROM customer_request_cancellations c WHERE c.request_id=customer_requests.request_id)",
                               (decision,audit._now(),user.username,explanation,amount,annual_rate,term,request_id))
        if changed.rowcount != 1:
            raise ValueError("This request has already been reviewed or cancelled. Refresh the page.")
    from src import notify
    notify.request_decision(request_id, "approved" if decision == "Approved" else "declined")


SECOND_APPROVER_ROLES = {"risk", "admin"}


def four_eyes_required() -> bool:
    """Off only in single-operator mode (src/mode.py), exactly like the rest of the system."""
    from src.mode import single_operator
    return not single_operator()


def second_approve(request_id, note):
    """Four-eyes rule: an approved customer request needs a second, DIFFERENT employee - a Risk
    Manager or Administrator - before the money can be issued."""
    user = require_role(*SECOND_APPROVER_ROLES)
    note = str(note or "").strip()
    if not note or len(note) > 1000:
        raise ValueError("Add a short note for the second approval (up to 1,000 characters).")
    with transaction("customer_request_second_approval", f"{request_id}: {note[:80]}") as conn:
        row = conn.execute("SELECT status,reviewed_by,username FROM customer_requests WHERE request_id=?",
                           (request_id,)).fetchone()
        if not row:
            raise ValueError("Request not found.")
        if row[0] != "Approved":
            raise ValueError("Only an approved request can receive a second approval.")
        if user.username in (row[1], row[2]) and four_eyes_required():
            raise PermissionError("Four-eyes rule: the second approval must come from a different employee "
                                  "than the first reviewer.")
        if conn.execute("SELECT 1 FROM customer_request_second_approvals WHERE request_id=?", (request_id,)).fetchone():
            raise ValueError("This request already has its second approval.")
        conn.execute("INSERT INTO customer_request_second_approvals VALUES (?,?,?,?,?)",
                     (request_id, user.username, user.role, note, audit._now()))


def issue_loan(request_id, disbursed_on, first_due_on):
    """Insert loan and owner link in one transaction; duplicate issuance is refused."""
    user = require_role(*STAFF)
    if disbursed_on > today_local().date() or first_due_on <= disbursed_on:
        raise ValueError("Use an issue date up to today and a first due date after it.")
    lid = loanbook.new_loan_id()
    with transaction("customer_loan_issued", f"{request_id}: {lid}") as conn:
        cur = conn.execute("SELECT * FROM customer_requests WHERE request_id=?", (request_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError("Request not found.")
        r = dict(zip([c[0] for c in cur.description], row))
        if r["status"] != "Approved":
            raise ValueError("Only an approved request can be issued.")
        if four_eyes_required() and not conn.execute(
                "SELECT 1 FROM customer_request_second_approvals WHERE request_id=?", (request_id,)).fetchone():
            raise ValueError("Four-eyes rule: a Risk Manager or Administrator must give the second approval "
                             "before the loan can be issued.")
        if conn.execute("SELECT 1 FROM customer_loan_links WHERE request_id=?", (request_id,)).fetchone():
            raise ValueError("This request already has an issued loan.")
        p = conn.execute("SELECT full_name,location FROM customer_profiles WHERE username=?",
                         (r["username"],)).fetchone()
        conn.execute("INSERT INTO loans "
                     "(loan_id,customer_ref,product,principal,annual_rate,term_months,disbursed_on,first_due_on,"
                     "collateral_value,band,area,employment,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (lid,p[0],r["product"],r["approved_amount"],r["approved_rate"],r["approved_term"],
                      disbursed_on.isoformat(),first_due_on.isoformat(),0,"Unrated",p[1],"",user.username,audit._now()))
        conn.execute("INSERT INTO customer_loan_links VALUES (?,?,?,?,?)",
                     (lid,r["username"],request_id,user.username,audit._now()))
    from src import notify
    notify.request_decision(request_id, "issued")
    return lid


def customer_accounts():
    require_role(*STAFF)
    return [u for u in auth.list_users() if u["role"] == "customer" and not u["disabled"]]


def unlinked_loans():
    require_role(*STAFF)
    conn = connect()
    try:
        return pd.read_sql_query("SELECT loan_id,customer_ref,principal FROM loans "
                                 "WHERE loan_id NOT IN (SELECT loan_id FROM customer_loan_links)", conn)
    finally:
        conn.close()


def link_existing(loan_id, username):
    user = require_role(*ACCOUNT_CREATOR_ROLES)     # Administrator or Risk Manager only
    if username not in {u["username"] for u in customer_accounts()}:
        raise ValueError("Choose an active customer account.")
    with transaction("customer_loan_linked", f"{loan_id}: {username}") as conn:
        if not conn.execute("SELECT 1 FROM loans WHERE loan_id=?", (loan_id,)).fetchone():
            raise ValueError("Loan not found.")
        if conn.execute("SELECT 1 FROM customer_loan_links WHERE loan_id=?", (loan_id,)).fetchone():
            raise ValueError("This loan is already linked to a customer.")
        conn.execute("INSERT INTO customer_loan_links VALUES (?,?,NULL,?,?)",
                     (loan_id,username,user.username,audit._now()))
    from src import notify
    notify.loans_linked(username, [loan_id])


ACCOUNT_CREATOR_ROLES = {"admin", "risk"}


def create_account_for_loans(loan_ids, full_name, email, phone, location):
    """Existing loans (issued at the branch): an Administrator or Risk Manager opens the customer's
    portal account with the customer's email and links the loans in one step. The customer never
    types a loan ID - they only sign in. If the email already has a customer account, the loans
    are linked to it instead. Returns {username, temp_password (or None), created}."""
    user = require_role(*ACCOUNT_CREATOR_ROLES)
    loan_ids = [str(x) for x in loan_ids]
    full_name, phone, location = str(full_name).strip(), str(phone).strip(), str(location).strip()
    email = auth.normalize_email(email)
    if not loan_ids:
        raise ValueError("Choose at least one loan.")
    if not full_name or not phone or not location:
        raise ValueError("Enter the customer's full name, phone number and address.")
    if not auth.valid_email(email):
        raise ValueError("Enter the customer's email address, for example name@gmail.com.")
    free = set(unlinked_loans()["loan_id"])
    taken = [lid for lid in loan_ids if lid not in free]
    if taken:
        raise ValueError(f"Already linked or not found: {', '.join(taken)}.")
    username = auth.find_username_by_email(email)
    temp, created = None, False
    if username:
        rec = auth._read_users()[username]
        if rec["role"] != "customer":
            raise ValueError("That email belongs to an employee account. Use the customer's own email.")
        if not rec.get("email_verified"):
            auth.set_email(username, email, verified=True, actor=user.username)
    else:
        username = auth._free_username(auth._read_users(), email)
        temp = auth.generate_temp_password()
        auth.create_user(username, full_name, "customer", temp, must_change=True, actor=user.username,
                         email=email, email_verified=True)
        created = True
    with transaction("customer_account_for_loans", f"{username}: {', '.join(loan_ids)}") as conn:
        conn.execute("INSERT OR IGNORE INTO customer_profiles VALUES (?,?,?,?,?,?)",
                     (username, full_name, phone, email, location, audit._now()))
        for lid in loan_ids:
            if conn.execute("SELECT 1 FROM customer_loan_links WHERE loan_id=?", (lid,)).fetchone():
                raise ValueError(f"{lid} was linked by someone else just now. Refresh the page.")
            conn.execute("INSERT INTO customer_loan_links VALUES (?,?,NULL,?,?)",
                         (lid, username, user.username, audit._now()))
    return {"username": username, "temp_password": temp, "created": created, "email": email}


def links_by_user():
    """{username: [loan_id, ...]} for every customer account (staff only)."""
    require_role(*STAFF)
    conn = connect()
    try:
        out = {}
        for lid, username in conn.execute("SELECT loan_id, username FROM customer_loan_links ORDER BY linked_at"):
            out.setdefault(username, []).append(lid)
        return out
    finally:
        conn.close()


def resend_sign_in(username):
    """New one-time password (or Google-only instructions) emailed again. Admin / Risk Manager."""
    user = require_role(*ACCOUNT_CREATOR_ROLES)
    rec = auth._read_users().get(username)
    if not rec or rec["role"] != "customer":
        raise ValueError("Choose a customer account.")
    if not rec.get("email"):
        raise ValueError("This customer has no email address. Add it first.")
    temp = None
    if rec.get("hash"):
        temp = auth.generate_temp_password()
        auth.set_password(username, temp, must_change=True, actor=user.username, action="password_reset")
    info = {"username": username, "email": rec["email"], "temp_password": temp, "created": False}
    return info, send_account_invitation(info, rec.get("display_name", username))


def send_account_invitation(info, full_name):
    """Email the customer how to sign in. Returns an error message, or None when sent."""
    from src import mailer
    if not mailer.configured():
        return "Email sending is not set up, so give the customer the details shown on screen."
    lines = [f"Hello {full_name},", "",
             "Your bank has opened a Credit Desk account for you so you can follow your loan online:",
             "your balance, your payment schedule, receipts, and paying by KHQR.", "",
             f"Sign in with your email: {info['email']}"]
    if info.get("temp_password"):
        lines += [f"One-time password: {info['temp_password']}  (you choose your own at the first sign-in)"]
    lines += ["Or press 'Continue with Google' with this Gmail address - no password needed.", "",
              "Never share your password. The bank will never ask for it."]
    text = "\n".join(lines)
    html = "<br>".join(__import__("html").escape(x) for x in lines)
    try:
        mailer.send(info["email"], "Your Credit Desk account is ready", text,
                    f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:15px;line-height:1.55;color:#1B2430">{html}</div>')
    except RuntimeError as exc:
        return str(exc)
    return None


def my_loans():
    user = require_role("customer")
    conn = connect()
    try:
        return pd.read_sql_query("SELECT l.* FROM loans l JOIN customer_loan_links c ON c.loan_id=l.loan_id "
                                 "WHERE c.username=? ORDER BY l.disbursed_on DESC", conn, params=(user.username,))
    finally:
        conn.close()


def loan_details(loan_id):
    user = require_role("customer")
    owned = my_loans()
    if owned.empty or loan_id not in set(owned["loan_id"]):
        raise PermissionError("This loan is not available to your account.")
    loan = owned[owned["loan_id"] == loan_id].iloc[0].to_dict()
    events = loanbook.events_for(loan_id)
    events = events[events["event_date"] <= today_local().date().isoformat()]
    sched = loanbook.schedule(loan, events)
    snap = loanbook.snapshot(loan, events, today_local().date())
    # Apply payments to each instalment's interest, then principal, including partial payments.
    paid = float(snap["paid"])
    available, principal_paid = paid, 0.0
    paid_each = []
    for row in sched.itertuples():
        allocated = min(available, float(row.installment))
        paid_each.append(allocated)
        principal_paid += max(0.0, allocated - float(row.interest))
        available = max(0.0, available - allocated)
    sched["paid"] = paid_each
    sched["paid"] = sched["paid"].round(2)
    sched["amount_due"] = (sched["installment"] - sched["paid"]).clip(lower=0).round(2)
    sched["payment_status"] = ["Paid" if r.amount_due < .005 else
                               "Overdue" if r.due_date < today_local().date() else "Upcoming"
                               for r in sched.itertuples()]
    unpaid = sched[sched["amount_due"] >= .005]
    snap["arrears"] = round(float(sched.loc[sched["due_date"] <= today_local().date(), "amount_due"].sum()), 2) if snap["status"] == "Active" else 0.0
    snap["principal_balance"] = round(max(0.0, float(loan["principal"]) - principal_paid), 2)
    snap["next_due"] = unpaid["due_date"].iloc[0] if len(unpaid) and snap["status"] == "Active" else None
    snap["next_amount"] = float(unpaid["amount_due"].iloc[0]) if snap["next_due"] else 0.0
    # Customer output deliberately excludes internal notes, risk bands and employee usernames.
    payments = events[events["kind"].isin(["payment", "settle"])][["id","event_date","amount"]].copy()
    payments = payment_breakdown(sched, payments.sort_values("event_date", kind="stable"))
    snap["principal_paid"] = float(payments["principal_paid"].sum())
    snap["interest_paid"] = float(payments["interest_paid"].sum())
    snap["unallocated_paid"] = float(payments["unallocated"].sum())
    return loan, snap, sched, payments


def payment_breakdown(schedule, payments):
    """Allocate payments oldest instalment first, interest before principal.

    Difference cumulative rounded totals so displayed cents reconcile across rows.
    Any amount beyond the full schedule is a separate unapplied credit.
    """
    out = payments.copy()
    principal_parts, interest_parts, credits = [], [], []
    total, previous_principal, previous_credit = 0.0, 0.0, 0.0
    scheduled_total = float(schedule["installment"].sum())
    for p in payments.itertuples():
        total += float(p.amount)
        available, principal = total, 0.0
        for r in schedule.itertuples():
            allocated = min(available, float(r.installment))
            principal += max(0.0, allocated - float(r.interest))
            available = max(0.0, available - allocated)
        cumulative_principal = round(principal, 2)
        cumulative_credit = round(max(0.0, total - scheduled_total), 2)
        principal_part = round(cumulative_principal - previous_principal, 2)
        credit = round(cumulative_credit - previous_credit, 2)
        principal_parts.append(principal_part)
        credits.append(credit)
        interest_parts.append(round(float(p.amount) - principal_part - credit, 2))
        previous_principal, previous_credit = cumulative_principal, cumulative_credit
    out["principal_paid"] = principal_parts
    out["interest_paid"] = interest_parts
    out["unallocated"] = credits
    return out


def payment_receipt(loan_id, payment_id):
    """Generate one private PDF from the stored payment, never customer-entered totals."""
    from src import reports
    from src.data_pipeline import to_local
    user = require_role("customer")
    loan, _, _, payments = loan_details(loan_id)  # ownership enforced before looking up an event
    selected = payments[payments["id"] == payment_id]
    if selected.empty:
        raise ValueError("Payment not found for this loan.")
    p = selected.iloc[0]
    number = f"PAY-{int(p['id']):08d}"
    name = profile().get("full_name", user.display_name)
    return reports.receipt_pdf(title="Payment receipt", number=number,
        issued=to_local(audit._now()), status="Payment recorded", signatures=(),
        rows=[("Customer", name), ("Loan reference", loan_id), ("Receipt reference", number),
              ("Payment date", pd.Timestamp(p["event_date"]).strftime("%d/%m/%Y")),
              ("Payment amount", f"${p['amount']:,.2f}"),
              ("Principal repaid", f"${p['principal_paid']:,.2f}"),
              ("Interest paid", f"${p['interest_paid']:,.2f}"),
              ("Unapplied credit", f"${p['unallocated']:,.2f}"), ("Currency", "USD")],
        note="This receipt confirms a payment in the loan records. It does not initiate a transfer. "
             "The allocation shown uses the current repayment schedule. Keep it for your records.")


def loan_statement(loan_id):
    """Current statement for an owned loan, including every recorded payment."""
    from src import reports
    from src.data_pipeline import to_local
    user = require_role("customer")
    loan, snap, schedule, payments = loan_details(loan_id)
    money = lambda value: f"${float(value):,.2f}"
    history = pd.DataFrame([{
        "Payment date": to_local(p.event_date, "%d/%m/%Y"),
        "Amount (USD)": money(p.amount), "Principal": money(p.principal_paid),
        "Interest": money(p.interest_paid), "Credit": money(p.unallocated),
    } for p in payments.itertuples()])
    today = today_local().date()
    return reports.receipt_pdf(title="Loan statement", number=f"ST-{loan_id}-{today:%Y%m%d}",
        issued=f"As of {today:%d/%m/%Y}", status=snap["status"], signatures=(),
        rows=[("Customer", profile().get("full_name", user.display_name)), ("Loan reference", loan_id),
              ("Loan product", loan["product"]), ("Disbursed on", to_local(loan["disbursed_on"], "%d/%m/%Y")),
              ("Original loan amount", money(loan["principal"])),
              ("Repayment term", f"{loan['term_months']} months"),
              ("Interest", f"{loan['annual_rate']:.2%} " + ("total over the loan term (flat)"
                 if loan.get("interest_method") == "flat_total" else "annual (reducing balance)")),
                ("Scheduled total interest", money(schedule["interest"].sum())),
                ("Scheduled total repayment", money(schedule["installment"].sum())),
                ("Total paid", money(snap["paid"])), ("Principal repaid", money(snap["principal_paid"])),
              ("Interest paid", money(snap["interest_paid"])),
              ("Remaining principal", money(snap["principal_balance"])),
              ("Installments paid", f"{int((schedule['payment_status'] == 'Paid').sum())} of {len(schedule)}"),
              ("Next payment", f"{money(snap['next_amount'])} due {snap['next_due']:%d/%m/%Y}"
               if snap["next_due"] else "No upcoming payment"),
              ("Overdue amount", money(snap["arrears"]))], table=history,
        table_title="Payment history", note="Amounts are in USD. Remaining principal excludes future interest. "
        "This statement is based on recorded transactions and the current repayment schedule; it is not a payoff quote.")


def repayment_schedule_pdf(loan_id):
    """Account-scoped schedule export using the same calculations as the portal."""
    from src import reports
    user = require_role("customer")
    loan, snap, schedule, _ = loan_details(loan_id)
    money = lambda amount: f"${float(amount):,.2f}"
    table = pd.DataFrame({"No.":schedule["no"],
        "Due date":schedule["due_date"].map(lambda day: day.strftime("%d/%m/%Y")),
        "Principal":schedule["principal"].map(money), "Interest":schedule["interest"].map(money),
        "Payment":schedule["installment"].map(money), "Paid":schedule["paid"].map(money),
        "Remaining":schedule["amount_due"].map(money), "Status":schedule["payment_status"]})
    rate = f"{loan['annual_rate']:.2%} " + ("total flat interest" if loan.get("interest_method") == "flat_total" else "annual reducing-balance interest")
    return reports.receipt_pdf(title="Repayment schedule",number=f"SCH-{loan_id}",
        issued=f"As of {today_local():%d/%m/%Y}",status=snap["status"],signatures=(),
        rows=[("Customer",profile().get("full_name",user.display_name)),("Loan reference",loan_id),
              ("Principal",money(loan["principal"])),("Interest method",rate),
              ("Term",f"{loan['term_months']} months"),
              ("Scheduled interest",money(schedule["interest"].sum())),
              ("Total repayment",money(schedule["installment"].sum()))],
        table=table,table_title="Installment dates and amounts (USD)",
        note="Amounts include scheduled interest. The final installment adjusts for rounding. "
             "Paid and remaining amounts reflect recorded payments as of the date above. "
             "This schedule excludes additional fees or penalties and is not a payoff quote.")


def request_receipt(request_id):
    """Download a confirmation only for the signed-in customer's own request."""
    from src import reports
    from src.data_pipeline import to_local
    user = require_role("customer")
    owned = requests()
    matches = owned[owned["request_id"] == request_id]
    if matches.empty:
        raise PermissionError("This request is not available to your account.")
    request = matches.iloc[0]
    estimate = saved_request_estimate(request_id)
    estimate_rows = [] if estimate is None else [
        ("Reviewed estimated rate", f"{estimate['rate_percent']:.2f}% total flat interest"),
        ("Estimated total interest", f"${estimate['total_interest']:,.2f}"),
        ("Estimated repayment", f"${estimate['total_repayment']:,.2f}"),
        ("Estimated monthly / final", f"${estimate['monthly_payment']:,.2f} / ${estimate['final_payment']:,.2f}")]
    return reports.receipt_pdf(title="Loan request confirmation", number=request_id,
        issued=f"Requested {to_local(request['submitted_at'])}", status=request["status"], signatures=(),
        rows=[("Customer", request["full_name"] or user.display_name),
              ("Request reference", request_id), ("Product", request["product"]),
              ("Amount requested", f"${request['amount']:,.2f}"),
              ("Requested term", f"{int(request['term_months'])} months"),
              ("Purpose", request["purpose"])] + estimate_rows,
        note="This confirms receipt of a loan request, not approval or payment. "
             "Final interest and repayment terms require employee approval. Status is current when downloaded.")


def my_notifications():
    """Build account-scoped updates with stable IDs and persistent read state."""
    user = require_role("customer")
    notices = []
    draft = application_draft()
    if draft:
        import hashlib
        version = hashlib.sha256(json.dumps(draft,sort_keys=True).encode()).hexdigest()[:16]
        notices.append(dict(id=f"draft:{user.username}:{version}",title="Draft saved",
            body=f"${draft['amount']:,.2f} · {int(draft['term'])} months · {draft['rate']:.2f}% estimated interest. Resume your application when ready.",
            ts=draft["updated_at"],tone="success"))
    for r in requests().itertuples():
        notices.append(dict(id=f"request:{r.request_id}", title="Loan request received",
                            body=f"{r.request_id}: your request for ${r.amount:,.2f} was received.",
                            ts=r.submitted_at, tone="info"))
        if r.status in {"Approved", "Declined"}:
            notices.append(dict(id=f"decision:{r.request_id}", title=f"Loan request {r.status.lower()}",
                                body=f"{r.request_id}: {r.explanation}", ts=r.decision_at,
                                tone="success" if r.status == "Approved" else "warning"))
        if r.status == "Cancelled":
            notices.append(dict(id=f"cancelled:{r.request_id}", title="Loan request cancelled",
                                body=f"{r.request_id}: you cancelled this request before review.",
                                ts=r.cancelled_at, tone="info"))
    conn = connect()
    try:
        seen = {r[0] for r in conn.execute("SELECT notification_id FROM customer_notifications_read WHERE username=?",
                                         (user.username,))}
        links = conn.execute("SELECT loan_id,linked_at FROM customer_loan_links WHERE username=?",
                             (user.username,)).fetchall()
    finally:
        conn.close()
    for lid, linked_at in links:
        loan, snap, _, _ = loan_details(lid)
        notices.append(dict(id=f"loan:{lid}", title="Loan record available",
                            body=f"{lid}: your ${loan['principal']:,.2f} loan is available in My loans & payments.",
                            ts=linked_at, tone="success"))
        due = snap["next_due"]
        if snap["status"] == "Active" and due:
            days_left = (due - today_local().date()).days
            overdue = days_left < 0
            stage = "late" if overdue else "today" if days_left == 0 else "tomorrow" if days_left == 1 else "3-days" if days_left <= 3 else "7-days" if days_left <= 7 else "next"
            notices.append(dict(id=f"due:{lid}:{due}:{stage}",
                                title="Payment overdue" if overdue else "Payment due today" if days_left == 0 else "Payment due tomorrow" if days_left == 1 else "Upcoming payment reminder" if days_left <= 7 else "Next payment",
                                body=f"{lid}: ${snap['next_amount']:,.2f} due {due:%d/%m/%Y}.",
                                ts=today_local().date().isoformat(), tone="error" if overdue else "info"))
    from src import customer_support, customer_documents
    notices.extend(customer_support.reply_notifications())
    notices.extend(customer_documents.review_notifications())
    for n in notices:
        n["unread"] = n["id"] not in seen
    return sorted(notices, key=lambda n: (n["id"].startswith("draft:"), n["ts"], n["id"]), reverse=True)


def mark_notifications_read(notification_ids):
    user = require_role("customer")
    # Never mark notifications generated after this page's snapshot was opened.
    allowed = {n["id"] for n in my_notifications()}
    ids = set(notification_ids) & allowed
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany("INSERT OR IGNORE INTO customer_notifications_read VALUES (?,?,?)",
                         [(user.username, nid, audit._now()) for nid in ids])
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
