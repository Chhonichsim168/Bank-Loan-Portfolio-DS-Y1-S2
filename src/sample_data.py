"""
sample_data.py
==============
Ready-made test records so every page has something to show on a fresh install:

* Decision queue - decisions in every status: waiting for a second approver (some past the 2-day
  target), approved / rejected / returned by a reviewer, final approvals and declines, and a
  repeat applicant.
* Loan book      - loans in every state, with dates counted back from TODAY so they stay correct:
  matured and fully repaid, settled early, written off, matured but unpaid, maturing soon,
  brand-new loans with a first instalment due in the next days, current loans, and loans in every
  arrears bucket (1-29, 30-59, 60-89, 90+), a restructured loan, a partial payment and a promise
  to pay. Some loans come from scored applications, so the "assumed vs observed default rate"
  table has evidence too.

Everything is written through the normal functions (workflow.save_decision / review,
loanbook.create_loan / add_event), so every business rule and every audit entry applies. Records
are marked: customer references start with "SAMPLE-" and rationales say "Sample data".

It runs ONCE (a marker file, data/sample_data_loaded.txt, records that it ran) and never twice -
also not if SAMPLE- records already exist. Existing records are kept; the samples are added beside
them. For a real deployment switch it off BEFORE the first start with CREDIT_DESK_SAMPLE_DATA=0 (a
line in the START Credit Desk file). To start again from an empty system, close the app and delete
data/audit_log.db and data/sample_data_loaded.txt.
"""
from __future__ import annotations

import math
import os
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone

import pandas as pd

from src import audit, loanbook, workflow
from src import decisioning as dec

OFFICER, RISK = ("officer", "officer"), ("risk", "risk")
CHECKS = {"identity": True, "income": True, "bureau": True, "liabilities": True}


def enabled() -> bool:
    return os.environ.get("CREDIT_DESK_SAMPLE_DATA", "1").strip().lower() not in {"0", "false", "no", "off"}


def marker_path():
    return audit.DB_PATH.parent / "sample_data_loaded.txt"


def already_loaded() -> bool:
    d, loans = workflow.decisions(5000), loanbook.list_loans()
    return bool((len(d) and d["customer_ref"].str.startswith("SAMPLE-").any())
                or (len(loans) and loans["customer_ref"].str.startswith("SAMPLE-").any()))


def seed_if_empty(ctx_fn) -> dict | None:
    """Load the sample records once. ``ctx_fn`` returns the app context (model, policy, cut-off);
    it is only called when loading is actually needed."""
    if not enabled() or marker_path().exists():
        return None
    if already_loaded():
        _write_marker("skipped - sample records already present")
        return None
    counts = seed(ctx_fn())
    _write_marker(f"loaded {counts}")
    return counts


def _write_marker(text: str) -> None:
    try:
        marker_path().parent.mkdir(parents=True, exist_ok=True)
        marker_path().write_text(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {text}\n")
    except OSError:
        pass


# -----------------------------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------------------------
@contextmanager
def _clock(when: datetime):
    """Record a decision / review / loan as made at ``when`` (UTC) - only the timestamps and ids
    of those records; the audit log keeps the real time the sample data was loaded."""
    saved = (workflow._now, workflow.new_application_id, loanbook.new_loan_id)
    stamp = when.astimezone(timezone.utc)
    workflow._now = lambda: stamp.isoformat(timespec="seconds")
    workflow.new_application_id = lambda: saved[1]().replace(datetime.now(timezone.utc).strftime("%Y%m%d"),
                                                              stamp.strftime("%Y%m%d"))
    loanbook.new_loan_id = lambda: saved[2]().replace(datetime.now(timezone.utc).strftime("%Y%m%d"),
                                                      stamp.strftime("%Y%m%d"))
    try:
        yield
    finally:
        workflow._now, workflow.new_application_id, loanbook.new_loan_id = saved


def _at(d: date, hour: int = 3) -> datetime:          # 03:00 UTC = 10:00 in Phnom Penh
    return datetime.combine(d, time(hour, 0), tzinfo=timezone.utc)


def _months(d: date, n: int) -> date:
    return (pd.Timestamp(d) + pd.DateOffset(months=n)).date()


BASE = dict(applicant_income=6000.0, coapplicant_income=0.0, loan_amount=100000.0, loan_term_months=240,
            credit_history=1, dependents=1, employment_status="salaried", property_area="urban",
            credit_score=740, late_payments_12m=0)


def _decide(c, ref: str, when: datetime, outcome: str, app: dict, extras: dict | None = None,
            rationale: str = "Sample data.", user=OFFICER, want: set | None = None) -> tuple[str, dict]:
    """Score ``app`` exactly as Score an application does, then save the officer's ``outcome``.
    ``want`` = routings the scenario needs; the applicant is strengthened until it gets one."""
    app = {**BASE, **app}
    for _ in range(12):
        r = dec.assess(c.model.pipeline, app, c.policy, c.cutoff, extras)
        if not want or r["routing"] in want:
            break
        app["credit_score"] = min(850, app["credit_score"] + 25)
        app["applicant_income"] = app["applicant_income"] * 1.12
    extras = {"existing_monthly_debt": 0.0, "collateral_value": 0.0, "product": "Personal", **(extras or {})}
    inputs = {**app, **extras,
              "application_date": (when.date() - timedelta(days=2)).isoformat()}
    reasons = [{"label": x.label, "contribution": x.contribution, "detail": x.detail}
               for x in dec.explain(c.model.pipeline, app)["reasons"]]
    lo, hi, _ = dec.score_interval(c.model, r["probability"])
    with _clock(when):
        saved = workflow.save_decision(
            username=user[0], role=user[1], customer_ref=ref, outcome=outcome, loan_amount=app["loan_amount"],
            probability=r["probability"], score_low=lo, score_high=hi, routing=r["routing"], cutoff=c.cutoff,
            policy_version=c.policy_version, model_version=c.model_version, policy_pass=r["policy_pass"],
            breaches=r["breaches"], inputs=inputs, reasons=reasons, rationale=rationale,
            checklist=CHECKS if outcome in workflow.APPROVING else {},
            authority_limit=c.settings.officer_authority_limit, out_of_range=bool(r["out_of_range"]))
    return saved.application_id, {**app, "routing": r["routing"]}


def _review(app_id: str, when: datetime, verdict: str, comment: str) -> None:
    with _clock(when):
        workflow.review(app_id, username=RISK[0], role=RISK[1], verdict=verdict, comment=comment)


def _loan(ref, product, principal, rate, term, disbursed: date, *, first_due: date | None = None,
          band="Review", area="urban", employment="salaried", collateral=0.0, app_id=None) -> str:
    first_due = first_due or _months(disbursed, 1)
    with _clock(_at(disbursed)):
        return loanbook.create_loan(username=OFFICER[0], role=OFFICER[1], customer_ref=ref, product=product,
                                    principal=principal, annual_rate=rate, term_months=term,
                                    disbursed_on=disbursed, first_due_on=first_due, collateral_value=collateral,
                                    band=band, application_id=app_id, area=area, employment=employment)


def _pay(lid: str, *, until: date, skip: set[int] = frozenset(), late_days: int = 0,
         partial_last: float | None = None, upto_no: int | None = None) -> int:
    """Pay every scheduled instalment due on or before ``until`` (except numbers in ``skip``),
    ``late_days`` after its due date. Returns how many were paid."""
    loan = loanbook.get_loan(lid)
    ev = loanbook.events_for(lid)
    sched = loanbook.schedule(loan, ev).reset_index(drop=True)
    paid = float(ev.loc[ev["kind"] == "payment", "amount"].sum()) if len(ev) else 0.0
    covered = int((sched["installment"].cumsum() <= paid + loanbook.TOL).sum())   # already paid (FIFO)
    sched = sched.iloc[covered:]
    due = sched[(sched["due_date"] <= until)]
    if upto_no is not None:
        due = due[due["no"] <= upto_no]
    due = due[~due["no"].isin(skip)]
    n = 0
    for i, r in enumerate(due.itertuples()):
        when = min(r.due_date + timedelta(days=late_days), date.today())
        amount = math.ceil(float(r.installment) * 100) / 100     # whole cents, never short
        if partial_last is not None and i == len(due) - 1:
            amount = round(amount * partial_last, 2)
        loanbook.add_event(lid, username=OFFICER[0], role=OFFICER[1], kind="payment", event_date=when,
                           amount=amount, detail="Sample data - instalment received")
        n += 1
    return n


def _event(lid, kind, when: date, detail, amount=0.0, payload=None, user=RISK):
    loanbook.add_event(lid, username=user[0], role=user[1], kind=kind, event_date=when, amount=amount,
                       detail=detail, payload=payload)


# -----------------------------------------------------------------------------------------
# the scenarios
# -----------------------------------------------------------------------------------------
def seed(c) -> dict:
    T = date.today()
    now = datetime.now(timezone.utc)
    n_dec = 0

    # ---- 1. Decision queue: every status --------------------------------------------------
    # Waiting for a second approver (two of them past the 2-day target)
    _decide(c, "SAMPLE-C101", now - timedelta(days=4), "Refer",
            {"credit_score": 640, "late_payments_12m": 1, "applicant_income": 4200, "loan_amount": 110000},
            rationale="Sample data. Thin margin on affordability; refer for a senior view.")
    _decide(c, "SAMPLE-C102", now - timedelta(days=3), "Decline",
            {"applicant_income": 11000, "credit_score": 805, "loan_amount": 90000},
            rationale="Sample data. Officer declines a strong file - needs a second approver (override).",
            want={"Fast-track", "Review"})
    _decide(c, "SAMPLE-C103", now - timedelta(days=1), "Approve",
            {"applicant_income": 14000, "coapplicant_income": 3000, "credit_score": 790, "loan_amount": 320000,
             "loan_term_months": 360},
            extras={"product": "Housing", "collateral_value": 420000},
            rationale="Sample data. Above the officer authority limit; house as collateral.",
            want={"Fast-track", "Review"})
    _decide(c, "SAMPLE-C104", now - timedelta(hours=5), "Approve with conditions",
            {"employment_status": "unemployed", "coapplicant_income": 5200, "applicant_income": 900,
             "loan_amount": 60000},
            rationale="Sample data. Policy exception: unemployed applicant, spouse income and a guarantor.")
    n_dec += 4

    # Already reviewed: approved / rejected / returned
    a, _ = _decide(c, "SAMPLE-C105", now - timedelta(days=12), "Refer",
                   {"credit_score": 660, "applicant_income": 5000, "loan_amount": 95000,
                    "employment_status": "self_employed"},
                   rationale="Sample data. Self-employed income needs checking.")
    _review(a, now - timedelta(days=11), "approved", "Sample data. Tax returns verified - approve.")
    big_ok, _ = _decide(c, "SAMPLE-C106", now - timedelta(days=9), "Approve",
                        {"applicant_income": 16000, "credit_score": 810, "loan_amount": 280000, "loan_term_months": 300},
                        extras={"product": "Housing", "collateral_value": 380000},
                        rationale="Sample data. Large housing loan, strong file.", want={"Fast-track", "Review"})
    _review(big_ok, now - timedelta(days=8), "approved", "Sample data. Collateral valuation seen - approved.")
    b, _ = _decide(c, "SAMPLE-C107", now - timedelta(days=7), "Approve",
                   {"applicant_income": 9000, "credit_score": 700, "loan_amount": 300000, "loan_term_months": 360},
                   rationale="Sample data. Large loan.", want={"Fast-track", "Review", "Refer"})
    _review(b, now - timedelta(days=6), "rejected", "Sample data. Income does not support this size - rejected.")
    r, _ = _decide(c, "SAMPLE-C108", now - timedelta(days=6), "Refer",
                   {"credit_score": 630, "late_payments_12m": 2, "loan_amount": 75000},
                   rationale="Sample data. Two late payments - refer.")
    _review(r, now - timedelta(days=5), "returned", "Sample data. Bank statement missing - returned to officer.")
    n_dec += 4

    # Final without a second approver (two approvals left free for "Add a loan")
    _decide(c, "SAMPLE-C109", now - timedelta(days=2), "Approve",
            {"applicant_income": 8000, "credit_score": 780, "loan_amount": 85000, "loan_term_months": 180},
            rationale="Sample data. Clean file.", want={"Fast-track", "Review"})
    _decide(c, "SAMPLE-C110", now - timedelta(days=2, hours=3), "Approve with conditions",
            {"applicant_income": 7000, "credit_score": 760, "loan_amount": 70000, "property_area": "rural"},
            extras={"product": "Agriculture"},
            rationale="Sample data. Approve with seasonal repayment condition.", want={"Fast-track", "Review"})
    _decide(c, "SAMPLE-C111", now - timedelta(days=15), "Decline",
            {"applicant_income": 2200, "credit_score": 520, "late_payments_12m": 4, "credit_history": 0,
             "loan_amount": 150000}, rationale="Sample data. Several policy breaches.")
    # Repeat applicant: SAMPLE-C101 was declined 3 months ago, and has applied again (above)
    _decide(c, "SAMPLE-C101", now - timedelta(days=95), "Decline",
            {"credit_score": 590, "late_payments_12m": 3, "applicant_income": 3800, "loan_amount": 130000},
            rationale="Sample data. Too many late payments at the time.")
    n_dec += 4

    # ---- 2. Loan book: expired (finished) loans ---------------------------------------------
    loans = {}
    d = _months(T, -15)
    lid = _loan("SAMPLE-L01", "Personal", 8000, 0.12, 12, d, area="urban")
    _pay(lid, until=T); loans["Matured - fully repaid"] = lid

    d = _months(T, -27) - timedelta(days=6)
    lid = _loan("SAMPLE-L02", "Agriculture", 15000, 0.10, 24, d, area="rural", employment="self_employed")
    _pay(lid, until=T, late_days=2); loans["Matured - fully repaid (paid 2 days late each time)"] = lid

    d = _months(T, -22)
    lid = _loan("SAMPLE-L03", "Vehicle", 20000, 0.11, 36, d, area="semiurban", collateral=18000)
    _pay(lid, until=_months(d, 12), upto_no=12)
    snap = loanbook.snapshot(loanbook.get_loan(lid), loanbook.events_for(lid), _months(d, 13))
    _event(lid, "settle", _months(d, 13), "Sample data - settled early from the sale of a car",
           amount=round(snap["outstanding"], 2), user=OFFICER)
    loans["Closed - settled early"] = lid

    d = _months(T, -20)
    lid = _loan("SAMPLE-L04", "SME (individual)", 25000, 0.14, 24, d, band="Refer", area="urban",
                employment="self_employed")
    _pay(lid, until=_months(d, 6), upto_no=6)
    _event(lid, "note", _months(d, 9), "Sample data - shop closed; customer not reachable", user=OFFICER)
    _event(lid, "writeoff", _months(T, -4), "Sample data - written off after 9 months without payment")
    loans["Written off"] = lid

    d = _months(T, -16)
    lid = _loan("SAMPLE-L05", "Personal", 6000, 0.13, 12, d, band="Refer", area="semiurban")
    _pay(lid, until=T, upto_no=8)
    loans["Matured but NOT repaid (90+ days)"] = lid

    d = _months(T, -10) - timedelta(days=12)
    lid = _loan("SAMPLE-L06", "Personal", 10000, 0.12, 12, d)
    _pay(lid, until=T)
    loans["Current - matures within 3 months"] = lid

    # ---- 3. Loan book: active loans from scored applications ----------------------------------
    def from_app(ref, months_ago, amount, term, *, product="Housing", area="urban", employment="salaried",
                 rate=0.095, days_ago=None, first_in_days=None, collateral=0.0, shift_days=0):
        """``shift_days`` moves every due date that many days earlier than today's day of month, so
        an unpaid instalment is that many days late (and the next one falls due sooner)."""
        disb = (T - timedelta(days=days_ago) if days_ago is not None
                else _months(T, -months_ago) - timedelta(days=shift_days))
        app_id, app = _decide(c, ref, _at(disb - timedelta(days=5)), "Approve",
                              {"loan_amount": amount, "loan_term_months": term, "applicant_income": max(5000, amount / 20),
                               "credit_score": 760, "property_area": area, "employment_status": employment},
                              extras={"product": product, "collateral_value": collateral},
                              rationale="Sample data. Approved and disbursed.", want={"Fast-track", "Review"})
        first = T + timedelta(days=first_in_days) if first_in_days is not None else None
        return _loan(ref, product, amount, rate, term, disb, first_due=first, band=app["routing"], area=area,
                     employment=employment, collateral=collateral, app_id=app_id)

    lid = from_app("SAMPLE-L07", 30, 120000, 360, collateral=160000, shift_days=24)
    _pay(lid, until=T); loans["Current - housing, 30 months on book"] = lid

    lid = from_app("SAMPLE-L08", 8, 60000, 180, product="Personal", area="semiurban", shift_days=18)
    _pay(lid, until=T, late_days=4); loans["Current - pays a few days late"] = lid

    lid = from_app("SAMPLE-L09", 0, 45000, 120, product="Vehicle", days_ago=20, first_in_days=10)
    loans["New - first instalment due in 10 days"] = lid

    lid = from_app("SAMPLE-L10", 0, 80000, 240, product="Housing", days_ago=25, first_in_days=4)
    loans["New - first instalment due in 4 days"] = lid

    lid = from_app("SAMPLE-L11", 12, 50000, 120, product="Personal", shift_days=15)
    last = loanbook.schedule(loanbook.get_loan(lid))
    n_due = int((last["due_date"] <= T).sum())
    _pay(lid, until=T, skip={n_due}); loans["1-29 days late"] = lid

    lid = from_app("SAMPLE-L12", 14, 70000, 180, product="SME (individual)", employment="self_employed",
                   shift_days=15)
    n_due = int((loanbook.schedule(loanbook.get_loan(lid))["due_date"] <= T).sum())
    _pay(lid, until=T, skip={n_due - 1, n_due}); loans["30-59 days late"] = lid

    lid = from_app("SAMPLE-L13", 11, 40000, 120, product="Agriculture", area="rural", employment="self_employed",
                   shift_days=15)
    n_due = int((loanbook.schedule(loanbook.get_loan(lid))["due_date"] <= T).sum())
    _pay(lid, until=T, skip={n_due - 2, n_due - 1, n_due})
    _event(lid, "note", T - timedelta(days=6), "Sample data - called customer; harvest delayed by floods", user=OFFICER)
    _event(lid, "promise", T - timedelta(days=2),
           f"Sample data - promised to pay two instalments on {(T + timedelta(days=7)):%d/%m/%Y}", user=OFFICER)
    loans["60-89 days late, with a promise to pay"] = lid

    lid = from_app("SAMPLE-L14", 18, 90000, 240, product="Housing", area="semiurban")
    _pay(lid, until=T, upto_no=12); loans["90+ days late (stage 3)"] = lid

    lid = from_app("SAMPLE-L15", 20, 55000, 120, product="Personal")
    _pay(lid, until=_months(T, -5), upto_no=12)            # paid 12, then missed some
    r_day = _months(T, -4)
    _pay(lid, until=r_day, upto_no=99)                      # catch-up of the missed instalments
    _event(lid, "restructure", r_day, "Sample data - income fell; term extended to lower the instalment",
           payload={"new_term_months": 132, "new_annual_rate": 0.095, "first_due_on": _months(r_day, 1)})
    _pay(lid, until=T)
    loans["Restructured - now current"] = lid

    lid = from_app("SAMPLE-L16", 24, 35000, 120, product="SME (individual)", employment="self_employed")
    _pay(lid, until=_months(T, -16), upto_no=8)
    _event(lid, "writeoff", _months(T, -6), "Sample data - business failed; collection exhausted")
    loans["Written off (from a scored application)"] = lid

    lid = from_app("SAMPLE-L17", 9, 65000, 180, product="Personal", shift_days=10)
    _pay(lid, until=T, partial_last=0.5); loans["Partial last payment (small arrears)"] = lid

    lid = from_app("SAMPLE-L18", 7, 30000, 120, product="Agriculture", area="rural", employment="self_employed",
                   shift_days=5)
    _pay(lid, until=T); loans["Current - rural agriculture"] = lid

    n_dec += 12
    return {"decisions": len(workflow.decisions(5000)), "loans": len(loanbook.list_loans()),
            "scenarios": loans}
