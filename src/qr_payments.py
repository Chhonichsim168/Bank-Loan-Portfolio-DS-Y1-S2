"""
qr_payments.py
==============
Every real KHQR the portal shows is remembered here, so a payment is never lost when the customer
closes the page before Credit Desk saw it: open QRs are checked again with Bakong the next time the
customer opens the portal, and whenever a staff member opens a page (throttled).

``record()`` is the ONE place a KHQR payment is written to the Loan book: it refuses doubles (the
QR's md5 is in the event detail), marks the QR as paid and emails the customer a confirmation.
"""
from __future__ import annotations

import time

from src import audit, loanbook

SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_qr_payments (
    md5 TEXT PRIMARY KEY, ref TEXT NOT NULL, username TEXT NOT NULL, loan_id TEXT NOT NULL,
    amount REAL NOT NULL, charge REAL NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','paid','expired','reported')),
    event_id INTEGER, bakong_hash TEXT NOT NULL DEFAULT '', checked_at TEXT NOT NULL DEFAULT ''
);
"""
RECHECK_DAYS = 3               # Bakong keeps the record; after 3 days an open QR is treated as unused
RECHECK_GAP_SECONDS = 120      # the token allows 100 checks a day - never check one QR more often
_last_check: dict[str, float] = {}
_last_staff_round = [0.0]


def _conn():
    conn = loanbook._conn()
    conn.executescript(SCHEMA)
    return conn


def register(username: str, state: dict) -> None:
    if not state.get("md5"):
        return
    conn = _conn()
    try:
        conn.execute("INSERT OR IGNORE INTO customer_qr_payments (md5,ref,username,loan_id,amount,charge,kind,created_at) "
                     "VALUES (?,?,?,?,?,?,?,?)", (state["md5"], state["ref"], username, state["loan"],
                                                  float(state["amount"]), float(state["charge"]), state["kind"],
                                                  audit._now()))
        conn.commit()
    finally:
        conn.close()


def mark(md5: str, status: str) -> None:
    conn = _conn()
    try:
        conn.execute("UPDATE customer_qr_payments SET status=? WHERE md5=? AND status='open'", (status, md5))
        conn.commit()
    finally:
        conn.close()


def record(username: str, loan_id: str, amount: float, kind: str, ref: str, md5: str = "",
           bakong: dict | None = None) -> int | None:
    """Write the payment once. Returns the new event id, or None if it was already recorded."""
    from src import notify
    from src.data_pipeline import today_local
    key = md5 or ref
    ev = loanbook.events_for(loan_id)
    if len(ev) and ev["detail"].astype(str).str.contains(key, regex=False).any():
        if md5:
            mark(md5, "paid")
        return None
    how = (f"Bakong hash {str(bakong.get('hash', ''))[:16]} from {bakong.get('fromAccountId', '?')} "
           f"({bakong.get('amount', '')} {bakong.get('currency', '')})" if bakong else "demo, no money moved")
    snap = loanbook.snapshot(loanbook.get_loan(loan_id), ev, today_local().date())
    if snap["status"] != "Active":
        kind = "payment"                     # closed meanwhile: keep the money on record, staff will refund
    eid = loanbook.add_event(loan_id, username=username, role="customer", kind=kind, event_date=today_local().date(),
                             amount=float(amount), detail=f"KHQR {ref} {key} - paid online by the customer - {how}")
    audit.log_event(username, "customer", "customer_payment", f"{loan_id}: ${float(amount):,.2f} via KHQR {ref} ({how})",
                    strict=False)
    if md5:
        conn = _conn()
        try:
            conn.execute("UPDATE customer_qr_payments SET status='paid', event_id=?, bakong_hash=? WHERE md5=?",
                         (int(eid), str((bakong or {}).get("hash", "")), md5))
            conn.commit()
        finally:
            conn.close()
    notify.payment_received(username, loan_id, amount, ref, int(eid))
    return int(eid)


def open_qrs(username: str | None = None):
    import pandas as pd
    conn = _conn()
    try:
        where, params = ("AND username=?", (username,)) if username else ("", ())
        return pd.read_sql_query(f"SELECT * FROM customer_qr_payments WHERE status='open' {where} ORDER BY created_at",
                                 conn, params=params)
    finally:
        conn.close()


def event_for(md5: str) -> int | None:
    conn = _conn()
    try:
        row = conn.execute("SELECT event_id FROM customer_qr_payments WHERE md5=?", (md5,)).fetchone()
        return int(row[0]) if row and row[0] is not None else None
    finally:
        conn.close()


def recheck(username: str | None = None, limit: int = 5, skip: tuple = ()) -> list[dict]:
    """Ask Bakong again about QRs that were shown but never confirmed. Returns the payments recorded."""
    from src import khqr
    if not khqr.can_check():
        return []
    import pandas as pd
    found, now = [], time.time()
    rows = open_qrs(username)
    for r in rows.itertuples():
        if r.md5 in skip:
            continue
        created = pd.Timestamp(r.created_at)
        created = created.tz_localize("UTC") if created.tzinfo is None else created
        age_days = (pd.Timestamp.now(tz="UTC") - created).total_seconds() / 86400
        if age_days > RECHECK_DAYS:
            mark(r.md5, "expired")
            continue
        if now - _last_check.get(r.md5, 0) < RECHECK_GAP_SECONDS or len(found) + 1 > limit:
            continue
        _last_check[r.md5] = now
        status, data = khqr.check(r.md5)
        if status == "error":
            break                                   # no internet / token problem: try again later
        if status == "paid":
            eid = record(r.username, r.loan_id, r.amount, r.kind, r.ref, r.md5, data)
            if eid:
                found.append({"loan": r.loan_id, "amount": r.amount, "ref": r.ref, "event": eid, "user": r.username})
    return found


def staff_round() -> list[dict]:
    """From a staff page: at most every 2 minutes per server, re-check everyone's open QRs."""
    if time.time() - _last_staff_round[0] < RECHECK_GAP_SECONDS:
        return []
    _last_staff_round[0] = time.time()
    try:
        return recheck(None, limit=10)
    except Exception:
        return []
