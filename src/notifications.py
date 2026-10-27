"""
notifications.py
================
Credit Desk - late-payment notifications.

Pure functions over the loan book (``loanbook.portfolio``) plus a cheap signature so the app can
cache the sidebar alert and recompute it only when a loan or a loan event is added.

Severity follows the delinquency buckets used everywhere else in the app:
    1-29 days   -> Reminder     (call the customer)
    30-59 days  -> Warning      (formal overdue notice, visit)
    60-89 days  -> Serious      (escalate to a Risk Manager)
    90+ days    -> Default      (non-performing: restructure or write-off decision)
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from src import loanbook

SEVERITY = [  # (min dpd, label, colour, what to do)
    (90, "Default", "#B42318", "Non-performing. A Risk Manager decides: restructure or write off."),
    (60, "Serious", "#C4320A", "Escalate to a Risk Manager; agree a payment plan or restructure."),
    (30, "Warning", "#B54708", "Send the formal overdue notice and visit the customer."),
    (1, "Reminder", "#A15C07", "Call the customer and record a promise to pay."),
    (0, "Overdue today", "#A15C07", "The instalment was due today and is unpaid - call the customer."),
]
ORDER = ["Default", "Serious", "Warning", "Reminder", "Overdue today"]


def severity(dpd: int) -> tuple[str, str, str]:
    for lo, label, colour, action in SEVERITY:
        if dpd >= lo:
            return label, colour, action
    return SEVERITY[-1][1], SEVERITY[-1][2], SEVERITY[-1][3]


def signature() -> tuple:
    """Changes whenever a loan or a loan event is added: the cache key for the sidebar alert."""
    loans, events = loanbook.list_loans(), loanbook.all_events()
    return (len(loans), int(events["id"].max()) if len(events) else 0, len(events))


def overdue(book: pd.DataFrame, asof=None) -> pd.DataFrame:
    """One row per ACTIVE loan with an unpaid instalment on or before ``asof``, most urgent first."""
    cols = ["loan_id", "customer_ref", "product", "severity", "dpd", "bucket", "arrears", "outstanding",
            "instalments_missed", "oldest_unpaid_due", "last_payment", "last_promise", "action"]
    if book is None or book.empty:
        return pd.DataFrame(columns=cols)
    asof = loanbook._d(asof or date.today())
    act = book[(book["status"] == "Active") & (book["arrears"] > loanbook.TOL)]
    if act.empty:
        return pd.DataFrame(columns=cols)
    events = loanbook.all_events()
    rows = []
    for _, r in act.iterrows():
        ev = events[(events["loan_id"] == r["loan_id"]) & (events["event_date"] <= asof.isoformat())] \
            if len(events) else events
        loan = loanbook.get_loan(r["loan_id"])
        sched = loanbook.schedule(loan, ev)
        paid = float(ev.loc[ev["kind"].isin(["payment", "settle"]), "amount"].sum()) if len(ev) else 0.0
        covered = int((sched["installment"].cumsum() <= paid + loanbook.TOL).sum())
        unpaid_due = sched.iloc[covered:]
        unpaid_due = unpaid_due[unpaid_due["due_date"] <= asof]
        pays = ev[ev["kind"].isin(["payment", "settle"])] if len(ev) else ev
        prom = ev[ev["kind"] == "promise"] if len(ev) else ev
        dpd = int(r["dpd"])
        label, _, action = severity(dpd)
        rows.append({
            "loan_id": r["loan_id"], "customer_ref": r["customer_ref"], "product": r["product"],
            "severity": label, "dpd": dpd, "bucket": r["bucket"], "arrears": round(float(r["arrears"]), 2),
            "outstanding": round(float(r["outstanding"]), 2), "instalments_missed": int(len(unpaid_due)),
            "oldest_unpaid_due": unpaid_due["due_date"].iloc[0] if len(unpaid_due) else None,
            "last_payment": pays["event_date"].iloc[-1] if len(pays) else None,
            "last_promise": (f"{prom['event_date'].iloc[-1]}: {prom['detail'].iloc[-1]}" if len(prom) else None),
            "action": action,
        })
    out = pd.DataFrame(rows, columns=cols)
    out["_o"] = out["severity"].map({s: i for i, s in enumerate(ORDER)})
    return out.sort_values(["_o", "dpd", "arrears"], ascending=[True, False, False]).drop(columns="_o") \
              .reset_index(drop=True)


def summary(late: pd.DataFrame) -> dict:
    """Headline counts for the sidebar and the KPI row."""
    if late is None or late.empty:
        return {"customers": 0, "loans": 0, "arrears": 0.0, "by_severity": {s: 0 for s in ORDER},
                "over_30": 0, "over_90": 0}
    return {"customers": int(late["customer_ref"].nunique()), "loans": int(len(late)),
            "arrears": float(late["arrears"].sum()),
            "by_severity": {s: int((late["severity"] == s).sum()) for s in ORDER},
            "over_30": int((late["dpd"] >= 30).sum()), "over_90": int((late["dpd"] >= 90).sum())}


def due_soon(book: pd.DataFrame, asof=None, days: int = 3) -> pd.DataFrame:
    """Active loans NOT late whose next instalment falls within ``days`` (a heads-up, not an alert)."""
    if book is None or book.empty:
        return pd.DataFrame()
    d = loanbook.upcoming_dues(book, asof or date.today(), days)
    return d[d["arrears"] <= loanbook.TOL]
