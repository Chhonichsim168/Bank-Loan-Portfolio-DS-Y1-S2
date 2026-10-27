"""
loanbook.py
===========
Credit Desk - the loan book: loans that were actually granted, their repayment schedule,
payments, days-past-due, collections notes, restructuring and write-off.

Why it exists: until now the "portfolio" in this app was a list of approved/declined applications.
With a loan book the bank's own repayment history accumulates on the same computer, which is what
a model needs to be re-trained on *repayment* instead of past approvals (see ``outcomes()``).

Design
------
* ``loans``       - one immutable row per loan (append-only).
* ``loan_events`` - payments, notes, promises-to-pay, restructures, write-offs, settlements
                    (append-only). Everything else - schedule, days past due, balance, stage,
                    status - is **computed from those rows as of any date**, never stored, so a
                    month-end view can be reproduced exactly later.
* Every write is committed in the same transaction as a hash-chained audit entry.

Simplifications, stated plainly: interest is an annuity at a fixed rate (no daily accrual, fees or
penalty interest); a payment is applied to the oldest unpaid instalment first; the outstanding
balance is the scheduled balance after the last fully-covered instalment; there is one currency.
"""

from __future__ import annotations

import json
import secrets
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from src import audit
from src import risk_economics as econ

APPROVING = {"Approve", "Approve with conditions"}
BUCKETS = ["Current", "1-29", "30-59", "60-89", "90+"]
KINDS = ("payment", "note", "promise", "restructure", "writeoff", "settle")
RISK_ONLY = {"restructure", "writeoff"}                   # roles that may do these
RISK_ROLES = {"risk", "admin"}
PRODUCTS = ["Personal", "Housing", "SME (individual)", "Agriculture", "Vehicle"]
TOL = 0.01

_SCHEMA = """
CREATE TABLE IF NOT EXISTS loans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id         TEXT NOT NULL UNIQUE,
    application_id  TEXT UNIQUE,
    customer_ref    TEXT NOT NULL,
    product         TEXT NOT NULL,
    principal       REAL NOT NULL CHECK (principal > 0),
    annual_rate     REAL NOT NULL CHECK (annual_rate >= 0),
    term_months     INTEGER NOT NULL CHECK (term_months > 0),
    disbursed_on    TEXT NOT NULL,
    first_due_on    TEXT NOT NULL,
    collateral_value REAL NOT NULL DEFAULT 0,
    band            TEXT NOT NULL,
    area            TEXT NOT NULL DEFAULT '',
    employment      TEXT NOT NULL DEFAULT '',
    created_by      TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS loans_no_update BEFORE UPDATE ON loans
BEGIN SELECT RAISE(ABORT, 'loans are append-only'); END;
CREATE TRIGGER IF NOT EXISTS loans_no_delete BEFORE DELETE ON loans
BEGIN SELECT RAISE(ABORT, 'loans are append-only'); END;

CREATE TABLE IF NOT EXISTS loan_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id     TEXT NOT NULL REFERENCES loans(loan_id),
    ts          TEXT NOT NULL,
    username    TEXT NOT NULL,
    role        TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('payment','note','promise','restructure','writeoff','settle')),
    event_date  TEXT NOT NULL,
    amount      REAL NOT NULL DEFAULT 0,
    detail      TEXT NOT NULL DEFAULT '',
    payload     TEXT NOT NULL DEFAULT '{}'
);
CREATE TRIGGER IF NOT EXISTS loan_events_no_update BEFORE UPDATE ON loan_events
BEGIN SELECT RAISE(ABORT, 'loan events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS loan_events_no_delete BEFORE DELETE ON loan_events
BEGIN SELECT RAISE(ABORT, 'loan events are append-only'); END;

-- Per-user "last opened" time of each loan, for the "new record" dot on Loan book > Loans.
-- loan_id '*' = the moment the user first opened the Loans tab (older records are not "new").
CREATE TABLE IF NOT EXISTS loan_seen (
    username  TEXT NOT NULL,
    loan_id   TEXT NOT NULL,
    seen_ts   TEXT NOT NULL,
    PRIMARY KEY (username, loan_id)
);
"""


def _conn():
    conn = audit.connect()
    conn.executescript(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _d(x) -> date:
    return x if isinstance(x, date) and not isinstance(x, datetime) else pd.Timestamp(x).date()


def _iso(x) -> str:
    return _d(x).isoformat()


def new_loan_id() -> str:
    return f"LN-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(3).upper()}"


# =========================================================================================
# WRITES
# =========================================================================================
def eligible_decisions() -> pd.DataFrame:
    """Saved decisions that can become loans: an approving outcome that is final (not waiting for,
    rejected by or returned by a second approver) and not yet turned into a loan."""
    from src import workflow
    df = workflow.decisions(5000)
    if df.empty:
        return df
    ok = df["outcome"].isin(APPROVING) & df["status"].isin(["Final", "Final (approved by reviewer)"])
    conn = _conn()
    try:
        used = {r[0] for r in conn.execute("SELECT application_id FROM loans WHERE application_id IS NOT NULL")}
    finally:
        conn.close()
    return df[ok & ~df["application_id"].isin(used)].reset_index(drop=True)


def create_loan(*, username: str, role: str, customer_ref: str, product: str, principal: float,
                annual_rate: float, term_months: int, disbursed_on, first_due_on, collateral_value: float,
                band: str, application_id: str | None = None, area: str = "", employment: str = "") -> str:
    if principal <= 0 or term_months <= 0 or annual_rate < 0:
        raise ValueError("Principal and term must be positive and the rate cannot be negative.")
    if not customer_ref.strip():
        raise ValueError("Enter a customer reference.")
    if product not in PRODUCTS:
        raise ValueError("Unknown product.")
    disb, first = _d(disbursed_on), _d(first_due_on)
    if first <= disb:
        raise ValueError("The first due date must be after the disbursement date.")
    if application_id:
        from src import workflow
        e = eligible_decisions()
        if e.empty or application_id not in set(e["application_id"]):
            raise ValueError("That application is not an approved, final decision (or already has a loan).")
    lid = new_loan_id()
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO loans (loan_id, application_id, customer_ref, product, principal, annual_rate, term_months, "
            "disbursed_on, first_due_on, collateral_value, band, area, employment, created_by, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (lid, application_id or None, customer_ref.strip(), product, float(principal), float(annual_rate),
             int(term_months), disb.isoformat(), first.isoformat(), float(collateral_value), band, area,
             employment, username, _now()))
        audit.append(conn, username, role, "loan_created",
                     f"{lid} - {customer_ref.strip()} - {product} - {principal:,.0f} at {annual_rate:.2%} "
                     f"over {term_months} months" + (f" - from {application_id}" if application_id else ""))
        conn.execute("COMMIT")
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        if isinstance(exc, (ValueError,)):
            raise
        audit._fallback({"ts": _now(), "username": username, "role": role, "action": "loan_create_failed",
                         "detail": customer_ref, "error": str(exc)})
        raise audit.AuditError(f"Loan was NOT created: {exc}") from exc
    finally:
        conn.close()
    return lid


def add_event(loan_id: str, *, username: str, role: str, kind: str, event_date, amount: float = 0.0,
              detail: str = "", payload: dict | None = None) -> int:
    if kind not in KINDS:
        raise ValueError("Unknown event type.")
    if kind in RISK_ONLY and role not in RISK_ROLES:
        raise PermissionError("Only a Risk Manager or Administrator can restructure or write off a loan.")
    if kind in ("payment", "settle") and amount <= 0:
        raise ValueError("A payment must be greater than zero.")
    if kind in ("note", "promise", "writeoff", "restructure") and not detail.strip():
        raise ValueError("Add a note - it is part of the record.")
    if _d(event_date) > date.today() and kind in ("payment", "settle", "writeoff"):
        raise ValueError("A payment or write-off cannot be dated in the future.")
    loan = get_loan(loan_id)
    if loan is None:
        raise ValueError("Unknown loan.")
    ev = events_for(loan_id)
    if not ev.empty and (ev["kind"].isin(["writeoff", "settle"])).any():
        raise ValueError("This loan is already closed or written off.")
    payload = dict(payload or {})
    if kind == "restructure":
        for k in ("new_term_months", "new_annual_rate", "first_due_on"):
            if k not in payload:
                raise ValueError(f"Restructure needs {k}.")
        if _d(payload["first_due_on"]) <= _d(event_date):
            raise ValueError("The first due date of the new schedule must be after the restructure date.")
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "INSERT INTO loan_events (loan_id, ts, username, role, kind, event_date, amount, detail, payload) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (loan_id, _now(), username, role, kind, _iso(event_date), float(amount), detail.strip(),
             json.dumps(payload, default=str)))
        event_id = int(cur.lastrowid)
        audit.append(conn, username, role, f"loan_{kind}",
                     f"{loan_id} - {amount:,.2f} - {detail.strip()[:120]}".strip(" -"))
        conn.execute("COMMIT")
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        audit._fallback({"ts": _now(), "username": username, "role": role, "action": f"loan_{kind}_failed",
                         "detail": loan_id, "error": str(exc)})
        raise audit.AuditError(f"Event was NOT recorded: {exc}") from exc
    finally:
        conn.close()
    return event_id                     # the record number, printed on receipts


# =========================================================================================
# READS
# =========================================================================================
def get_loan(loan_id: str) -> dict | None:
    conn = _conn()
    try:
        cur = conn.execute("SELECT * FROM loans WHERE loan_id = ?", (loan_id,))
        row = cur.fetchone()
        cols = [c[0] for c in cur.description]
    finally:
        conn.close()
    return dict(zip(cols, row)) if row else None


def list_loans() -> pd.DataFrame:
    conn = _conn()
    try:
        return pd.read_sql_query("SELECT * FROM loans ORDER BY id DESC", conn)
    finally:
        conn.close()


def all_events() -> pd.DataFrame:
    conn = _conn()
    try:
        return pd.read_sql_query("SELECT * FROM loan_events ORDER BY id", conn)
    finally:
        conn.close()


# ---- "new record" markers -------------------------------------------------------------------
def unseen_loans(username: str) -> dict[str, int]:
    """{loan_id: number of records saved since this user last opened that loan}. Records saved
    before the user's first visit to the Loans tab never count as new."""
    conn = _conn()
    try:
        conn.execute("INSERT OR IGNORE INTO loan_seen (username, loan_id, seen_ts) VALUES (?, '*', ?)",
                     (username, _now()))
        conn.commit()
        rows = conn.execute(
            "SELECT e.loan_id, COUNT(*) FROM loan_events e "
            "JOIN loan_seen b ON b.username = ? AND b.loan_id = '*' "
            "LEFT JOIN loan_seen s ON s.username = ? AND s.loan_id = e.loan_id "
            "WHERE e.ts > b.seen_ts AND (s.seen_ts IS NULL OR e.ts > s.seen_ts) "
            "GROUP BY e.loan_id", (username, username)).fetchall()
        return {r[0]: int(r[1]) for r in rows}
    finally:
        conn.close()


def mark_seen(username: str, loan_id: str) -> None:
    conn = _conn()
    try:
        conn.execute("INSERT INTO loan_seen (username, loan_id, seen_ts) VALUES (?, ?, ?) "
                     "ON CONFLICT(username, loan_id) DO UPDATE SET seen_ts = excluded.seen_ts",
                     (username, loan_id, _now()))
        conn.commit()
    finally:
        conn.close()


def events_for(loan_id: str) -> pd.DataFrame:
    conn = _conn()
    try:
        return pd.read_sql_query("SELECT * FROM loan_events WHERE loan_id = ? ORDER BY id", conn, params=(loan_id,))
    finally:
        conn.close()


# =========================================================================================
# COMPUTATION (pure: loan dict + events frame + as-of date)
# =========================================================================================
def _annuity(principal: float, rate: float, term: int, first_due: date, start_no: int = 1) -> pd.DataFrame:
    pay = econ.emi(principal, rate, term)
    bal, rows = principal, []
    for i in range(term):
        interest = bal * rate / 12
        princ = pay - interest if i < term - 1 else bal           # last instalment clears rounding
        inst = princ + interest
        bal = max(0.0, bal - princ)
        rows.append({"no": start_no + i, "due_date": (pd.Timestamp(first_due) + pd.DateOffset(months=i)).date(),
                     "installment": inst, "interest": interest, "principal": princ, "balance": bal})
    return pd.DataFrame(rows)


def schedule(loan: dict, events: pd.DataFrame | None = None) -> pd.DataFrame:
    """The repayment schedule in force: the original annuity, with each restructure replacing every
    instalment from its new first-due date onward by a fresh annuity on the scheduled balance."""
    sched = _annuity(loan["principal"], loan["annual_rate"], int(loan["term_months"]), _d(loan["first_due_on"]))
    if events is not None and not events.empty:
        for _, e in events[events["kind"] == "restructure"].iterrows():
            p = json.loads(e["payload"])
            first = _d(p["first_due_on"])
            kept = sched[sched["due_date"] < first]
            bal = float(kept["balance"].iloc[-1]) if len(kept) else float(loan["principal"])
            if bal <= TOL:
                continue
            new = _annuity(bal, float(p["new_annual_rate"]), int(p["new_term_months"]), first, start_no=len(kept) + 1)
            sched = pd.concat([kept, new], ignore_index=True)
    return sched.reset_index(drop=True)


def bucket_of(dpd: int) -> str:
    return "Current" if dpd <= 0 else "1-29" if dpd < 30 else "30-59" if dpd < 60 else "60-89" if dpd < 90 else "90+"


def snapshot(loan: dict, events: pd.DataFrame, asof) -> dict:
    """Everything known about a loan on a given date."""
    asof = _d(asof)
    ev = events[events["event_date"] <= asof.isoformat()] if len(events) else events
    sched = schedule(loan, ev)
    pays = ev[ev["kind"].isin(["payment", "settle"])] if len(ev) else ev
    paid = float(pays["amount"].sum()) if len(pays) else 0.0
    written_off = bool(len(ev) and (ev["kind"] == "writeoff").any())
    settled = bool(len(ev) and (ev["kind"] == "settle").any())
    cum = sched["installment"].cumsum()
    covered = int((cum <= paid + TOL).sum())                            # instalments fully paid (FIFO)
    fully_paid = covered >= len(sched)
    balance = float(loan["principal"]) if covered == 0 else float(sched["balance"].iloc[covered - 1])
    dpd = 0
    if not (written_off or settled or fully_paid):
        due_unpaid = sched.iloc[covered:]
        overdue = due_unpaid[due_unpaid["due_date"] <= asof]
        if len(overdue):
            dpd = (asof - overdue["due_date"].iloc[0]).days
    due_amount = float(sched.loc[sched["due_date"] <= asof, "installment"].sum())
    nxt = sched[sched["due_date"] > asof]
    status = "Written off" if written_off else "Closed" if (settled or fully_paid) else "Active"
    outstanding = 0.0 if status != "Active" else balance
    return {
        "loan_id": loan["loan_id"], "status": status, "dpd": int(dpd), "bucket": bucket_of(dpd),
        "stage": econ.stage_for(dpd, status), "outstanding": outstanding,
        "arrears": max(0.0, due_amount - paid) if status == "Active" else 0.0,
        "paid": paid, "next_due": nxt["due_date"].iloc[0] if len(nxt) else None,
        "next_amount": float(nxt["installment"].iloc[0]) if len(nxt) else 0.0,
        # Date facts: when the loan ends, how long it has run, how much of it is left.
        "maturity_date": sched["due_date"].iloc[-1] if len(sched) else None,
        "months_on_book": max(0, (asof.year - _d(loan["disbursed_on"]).year) * 12
                              + asof.month - _d(loan["disbursed_on"]).month),
        "remaining_instalments": int(len(nxt)) if status == "Active" else 0,
    }


def upcoming_dues(book: pd.DataFrame, asof, days: int = 30) -> pd.DataFrame:
    """Active loans whose next instalment falls within ``days`` of ``asof``, plus any loan already
    in arrears (those are due now). Sorted with the most urgent first - a collections call list."""
    cols = ["loan_id", "customer_ref", "next_due", "days_until_due", "next_amount", "arrears", "dpd", "bucket"]
    if book.empty:
        return pd.DataFrame(columns=cols)
    asof = _d(asof)
    act = book[book["status"] == "Active"].copy()
    act["days_until_due"] = [(_d(d) - asof).days if d is not None and not pd.isna(d) else None
                             for d in act["next_due"]]
    mask = (act["arrears"] > TOL) | act["days_until_due"].between(0, days)
    out = act.loc[mask, cols].copy()
    out["urgency"] = (out["arrears"] > TOL).map({True: 0, False: 1})
    return out.sort_values(["urgency", "dpd", "days_until_due"], ascending=[True, False, True]).drop(columns="urgency")


def portfolio(asof=None) -> pd.DataFrame:
    """One row per loan with its snapshot, joined to the static loan fields."""
    asof = _d(asof or date.today())
    loans, events = list_loans(), all_events()
    if loans.empty:
        return pd.DataFrame()
    rows = []
    for _, l in loans.iterrows():
        ev = events[events["loan_id"] == l["loan_id"]] if len(events) else events
        if l["disbursed_on"] > asof.isoformat():
            continue
        rows.append({**l.to_dict(), **snapshot(l.to_dict(), ev, asof)})
    return pd.DataFrame(rows)


def month_ends(start: date, end: date) -> list[date]:
    out = list(pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="ME").date)
    if not out or out[-1] != end:
        out.append(end)
    return out


def vintage_table(asof=None) -> pd.DataFrame:
    """By month of disbursement: loans, amount, and the share that has EVER been 30+ and 90+ days late."""
    asof = _d(asof or date.today())
    loans, events = list_loans(), all_events()
    rows = []
    for _, l in loans.iterrows():
        if l["disbursed_on"] > asof.isoformat():
            continue
        ev = events[events["loan_id"] == l["loan_id"]] if len(events) else events
        worst = max(snapshot(l.to_dict(), ev, d)["dpd"] for d in month_ends(_d(l["disbursed_on"]), asof))
        wo = bool(len(ev) and (ev["kind"] == "writeoff").any())
        rows.append({"vintage": l["disbursed_on"][:7], "principal": l["principal"], "worst_dpd": worst, "wo": wo})
    if not rows:
        return pd.DataFrame(columns=["vintage", "loans", "principal", "ever_30plus", "ever_90plus"])
    df = pd.DataFrame(rows)
    return (df.groupby("vintage").agg(loans=("principal", "size"), principal=("principal", "sum"),
                                      ever_30plus=("worst_dpd", lambda x: float((x >= 30).mean())),
                                      ever_90plus=("worst_dpd", lambda x: float((x >= 90).mean())))
            .reset_index())


def roll_rates(asof=None) -> pd.DataFrame:
    """Share of loans in each delinquency bucket a month ago that sit in each bucket now."""
    asof = _d(asof or date.today())
    prev = (pd.Timestamp(asof) - pd.DateOffset(months=1)).date()
    loans, events = list_loans(), all_events()
    pairs = []
    for _, l in loans.iterrows():
        if l["disbursed_on"] > prev.isoformat():
            continue
        ev = events[events["loan_id"] == l["loan_id"]] if len(events) else events
        a, b = snapshot(l.to_dict(), ev, prev), snapshot(l.to_dict(), ev, asof)
        if a["status"] == "Active":
            pairs.append((a["bucket"], b["bucket"] if b["status"] == "Active" else "Closed / written off"))
    cols = BUCKETS + ["Closed / written off"]
    if not pairs:
        return pd.DataFrame(0.0, index=BUCKETS, columns=cols)
    t = pd.crosstab(pd.Series([p[0] for p in pairs], name="was"), pd.Series([p[1] for p in pairs], name="now"))
    t = t.reindex(index=BUCKETS, columns=cols, fill_value=0)
    return t.div(t.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)


def portfolio_summary(book: pd.DataFrame, settings, pd_multiplier: float = 1.0, haircut_shock: float = 0.0) -> dict:
    """Headline numbers for the live book (illustrative provisions - see risk_economics)."""
    act = book[book["status"] == "Active"] if len(book) else book
    if act.empty:
        return {"loans": 0, "outstanding": 0.0, "npl_ratio": 0.0, "provision": 0.0, "coverage": 0.0, "stage": {1: 0, 2: 0, 3: 0}}
    prov = [econ.provision_row(r.outstanding, int(r.stage), r.band, r.collateral_value, settings,
                               pd_multiplier, haircut_shock) for r in act.itertuples()]
    out = float(act["outstanding"].sum())
    npl = float(act.loc[act["dpd"] >= econ.STAGE3_DPD, "outstanding"].sum())
    return {"loans": int(len(act)), "outstanding": out, "npl_ratio": npl / out if out else 0.0,
            "provision": float(sum(prov)), "coverage": float(sum(prov)) / out if out else 0.0,
            "stage": {s: float(act.loc[act["stage"] == s, "outstanding"].sum()) for s in (1, 2, 3)}}


def concentration(book: pd.DataFrame) -> dict:
    act = book[book["status"] == "Active"] if len(book) else book
    if act.empty or act["outstanding"].sum() <= 0:
        return {"by_area": pd.Series(dtype=float), "by_product": pd.Series(dtype=float), "largest_share": 0.0}
    tot = act["outstanding"].sum()
    return {"by_area": (act.groupby(act["area"].replace("", "unknown"))["outstanding"].sum() / tot).sort_values(ascending=False),
            "by_product": (act.groupby("product")["outstanding"].sum() / tot).sort_values(ascending=False),
            "largest_share": float(act["outstanding"].max() / tot)}


def alerts(book: pd.DataFrame, settings, pending_reviews: int = 0) -> list[tuple[str, str]]:
    """(tone, message) for every limit currently breached."""
    out = []
    s = portfolio_summary(book, settings)
    if s["loans"] and s["npl_ratio"] > settings.max_npl_ratio:
        out.append(("stop", f"NPL ratio {s['npl_ratio']:.1%} is above the {settings.max_npl_ratio:.1%} limit."))
    c = concentration(book)
    for area, share in c["by_area"].items():
        if area != "unknown" and share > settings.max_area_share:
            out.append(("warn", f"{area.title()} is {share:.0%} of the book (limit {settings.max_area_share:.0%})."))
    if c["largest_share"] > settings.max_single_share and s["loans"] >= 10:
        out.append(("warn", f"The largest single loan is {c['largest_share']:.1%} of the book "
                            f"(limit {settings.max_single_share:.0%})."))
    if len(book) and (book["dpd"] >= econ.STAGE3_DPD).any():
        out.append(("warn", f"{int((book['dpd'] >= econ.STAGE3_DPD).sum())} loan(s) are 90+ days past due."))
    if pending_reviews:
        out.append(("warn", f"{pending_reviews} decision(s) are waiting for a second approver."))
    return out


def outcomes(asof=None, min_months: int = 6) -> pd.DataFrame:
    """Observed repayment outcome per loan that came from a scored application and is seasoned enough
    to judge: repaid=0 if it was ever 90+ days late or written off, else 1. Feeds the monitoring
    back-test and ``risk_economics.observed_default_rates``."""
    asof = _d(asof or date.today())
    loans, events = list_loans(), all_events()
    rows = []
    for _, l in loans[loans["application_id"].notna()].iterrows() if len(loans) else []:
        ev = events[events["loan_id"] == l["loan_id"]] if len(events) else events
        worst = max(snapshot(l.to_dict(), ev, d)["dpd"] for d in month_ends(_d(l["disbursed_on"]), asof))
        wo = bool(len(ev) and (ev["kind"] == "writeoff").any())
        end = snapshot(l.to_dict(), ev, asof)
        age_m = (asof - _d(l["disbursed_on"])).days / 30.4
        bad = wo or worst >= 90
        if bad or end["status"] == "Closed" or age_m >= min_months:
            rows.append({"application_id": l["application_id"], "loan_id": l["loan_id"], "band": l["band"],
                         "repaid": 0 if bad else 1})
    return pd.DataFrame(rows, columns=["application_id", "loan_id", "band", "repaid"])
