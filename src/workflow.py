"""
workflow.py
===========
Credit Desk - saved credit decisions, application IDs, second-approval (maker-checker).

Before this module a "decision record" was a Markdown file that existed only if the officer
clicked Download. Now a decision is a database record, written when the officer saves it:

* a unique **application ID** (``APP-YYYYMMDD-XXXXXX``) so a case can be traced end to end;
* the officer is the **signed-in user**, not free text;
* the full inputs, reason codes, score, interval, cut-off, **policy version** and **model
  version** are stored, so the case can be reproduced later;
* the record is append-only and its SHA-256 is written to the hash-chained audit log in the
  same transaction - **no audit record, no decision**.

Second approval (four eyes). A saved decision is *Final* unless one of these applies, in which
case it is *Pending second approval* and a different Risk Manager / Administrator must
approve, reject or return it:

    - the officer chose **Refer**;
    - the loan exceeds the officer authority limit in the active policy;
    - the officer **approved** something the hard policy blocks or the model scores in the
      decline band (an override of the system's recommendation).

Honest limit: this is a working control, not a full loan-origination system - there is no
SLA clock, assignment queue or document store.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from src import audit
from src.mode import single_operator

APPROVING = {"Approve", "Approve with conditions"}
REVIEW_ROLES = {"risk", "admin"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id  TEXT NOT NULL UNIQUE,
    created_at      TEXT NOT NULL,
    username        TEXT NOT NULL,
    role            TEXT NOT NULL,
    customer_ref    TEXT NOT NULL DEFAULT '',
    outcome         TEXT NOT NULL,
    loan_amount     REAL NOT NULL,
    probability     REAL NOT NULL,
    score_low       REAL,
    score_high      REAL,
    routing         TEXT NOT NULL,
    cutoff          REAL NOT NULL,
    policy_version  INTEGER NOT NULL,
    model_version   TEXT NOT NULL,
    policy_pass     INTEGER NOT NULL,
    breaches        TEXT NOT NULL DEFAULT '',
    inputs          TEXT NOT NULL,
    reasons         TEXT NOT NULL,
    rationale       TEXT NOT NULL DEFAULT '',
    checklist       TEXT NOT NULL DEFAULT '{}',
    needs_review    INTEGER NOT NULL DEFAULT 0,
    review_reasons  TEXT NOT NULL DEFAULT '',
    record_sha256   TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS decisions_no_update BEFORE UPDATE ON decisions
BEGIN SELECT RAISE(ABORT, 'decisions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS decisions_no_delete BEFORE DELETE ON decisions
BEGIN SELECT RAISE(ABORT, 'decisions are append-only'); END;

CREATE TABLE IF NOT EXISTS decision_reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL REFERENCES decisions(id),
    ts          TEXT NOT NULL,
    username    TEXT NOT NULL,
    role        TEXT NOT NULL,
    verdict     TEXT NOT NULL CHECK (verdict IN ('approved', 'rejected', 'returned')),
    comment     TEXT NOT NULL DEFAULT ''
);
CREATE TRIGGER IF NOT EXISTS reviews_no_update BEFORE UPDATE ON decision_reviews
BEGIN SELECT RAISE(ABORT, 'reviews are append-only'); END;
CREATE TRIGGER IF NOT EXISTS reviews_no_delete BEFORE DELETE ON decision_reviews
BEGIN SELECT RAISE(ABORT, 'reviews are append-only'); END;
"""


def _conn():
    conn = audit.connect()
    conn.executescript(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_application_id() -> str:
    return f"APP-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(3).upper()}"


@dataclass
class SavedDecision:
    application_id: str
    needs_review: bool
    review_reasons: list[str]
    record_sha256: str


def review_requirements(*, outcome: str, loan_amount: float, authority_limit: float,
                        policy_pass: bool, routing: str, out_of_range: bool = False) -> list[str]:
    """Why (if at all) this decision needs a second approver."""
    why = []
    if outcome == "Refer":
        why.append("Referred to a senior officer")
    if outcome in APPROVING and loan_amount > authority_limit:
        why.append(f"Loan exceeds the officer authority limit (${authority_limit:,.0f})")
    if outcome in APPROVING and not policy_pass:
        why.append("Approved despite a hard-policy breach (policy exception)")
    if outcome in APPROVING and routing == "Decline" and policy_pass:
        why.append("Approved against a decline-band model score (override)")
    if outcome in APPROVING and out_of_range:
        why.append("Inputs outside the model's training range (score is an extrapolation)")
    # FIX: overrides were only checked in one direction. Approving against a decline score needed
    # a second approver, but declining a customer the model routes to approval (Fast-track or
    # Review) with no policy breach did not - so a good applicant could be refused unchecked.
    if outcome == "Decline" and routing in ("Fast-track", "Review") and policy_pass:
        why.append("Declined against an approve-band model score (override)")
    return why


def save_decision(*, username: str, role: str, customer_ref: str, outcome: str, loan_amount: float,
                  probability: float, score_low: float | None, score_high: float | None,
                  routing: str, cutoff: float, policy_version: int, model_version: str,
                  policy_pass: bool, breaches: list[str], inputs: dict, reasons: list[dict],
                  rationale: str, checklist: dict, authority_limit: float,
                  out_of_range: bool = False) -> SavedDecision:
    """Write the decision and its audit event in ONE transaction. Raises if either fails."""
    if outcome in APPROVING and not all(checklist.values()):
        raise ValueError("Complete every verification item before approving.")
    why = review_requirements(outcome=outcome, loan_amount=loan_amount, authority_limit=authority_limit,
                              policy_pass=policy_pass, routing=routing, out_of_range=out_of_range)
    if why and not rationale.strip():
        raise ValueError("A rationale is required when the decision needs a second approval.")
    app_id = new_application_id()
    body = {
        "application_id": app_id, "created_at": _now(), "user": username, "customer_ref": customer_ref,
        "outcome": outcome, "probability": probability, "routing": routing, "cutoff": cutoff,
        "policy_version": policy_version, "model_version": model_version, "inputs": inputs,
        "reasons": reasons, "rationale": rationale, "checklist": checklist, "breaches": breaches,
    }
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO decisions (application_id, created_at, username, role, customer_ref, outcome, "
            "loan_amount, probability, score_low, score_high, routing, cutoff, policy_version, "
            "model_version, policy_pass, breaches, inputs, reasons, rationale, checklist, needs_review, "
            "review_reasons, record_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (app_id, body["created_at"], username, role, customer_ref, outcome, loan_amount, probability,
             score_low, score_high, routing, cutoff, policy_version, model_version, int(policy_pass),
             ", ".join(breaches), json.dumps(inputs, default=str), json.dumps(reasons, default=str),
             rationale, json.dumps(checklist), int(bool(why)), "; ".join(why), digest))
        audit.append(conn, username, role, "decision_saved",
                     f"{app_id} - {outcome} - score {probability*100:.1f}% - policy v{policy_version} - "
                     f"model {model_version} - sha256 {digest[:16]}"
                     + (f" - PENDING 2nd approval: {'; '.join(why)}" if why else ""))
        conn.execute("COMMIT")
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        audit._fallback({"ts": _now(), "username": username, "role": role, "action": "decision_save_failed",
                         "detail": f"{outcome} {loan_amount}", "error": str(exc)})
        raise audit.AuditError(f"Decision was NOT saved: {exc}") from exc
    finally:
        conn.close()
    return SavedDecision(app_id, bool(why), why, digest)


def review(application_id: str, *, username: str, role: str, verdict: str, comment: str) -> None:
    if role not in REVIEW_ROLES:
        raise PermissionError("Only a Risk Manager or Administrator can review a decision.")
    if verdict not in {"approved", "rejected", "returned"}:
        raise ValueError("Unknown verdict.")
    if not comment.strip():
        raise ValueError("A comment is required.")
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        d = conn.execute("SELECT id, username, needs_review FROM decisions WHERE application_id = ?",
                         (application_id,)).fetchone()
        if not d:
            raise ValueError("Unknown application.")
        if not d[2]:
            raise ValueError("This decision does not need a second approval.")
        if d[1] == username and not single_operator():
            raise PermissionError("Four-eyes rule: you cannot review a decision you made.")
        if conn.execute("SELECT 1 FROM decision_reviews WHERE decision_id = ? AND verdict IN "
                        "('approved','rejected','returned')", (d[0],)).fetchone():
            raise ValueError("This decision has already been reviewed.")
        conn.execute("INSERT INTO decision_reviews (decision_id, ts, username, role, verdict, comment) "
                     "VALUES (?,?,?,?,?,?)", (d[0], _now(), username, role, verdict, comment.strip()))
        audit.append(conn, username, role, f"decision_{verdict}", f"{application_id}: {comment.strip()}")
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def decisions(limit: int = 500) -> pd.DataFrame:
    """Every saved decision with its current status, newest first."""
    conn = _conn()
    try:
        df = pd.read_sql_query(
            "SELECT d.application_id, d.created_at, d.username, d.customer_ref, d.outcome, d.loan_amount, "
            "d.probability, d.score_low, d.score_high, d.routing, d.policy_version, d.model_version, "
            "d.policy_pass, d.breaches, d.needs_review, d.review_reasons, d.rationale, d.inputs, d.reasons, "
            "r.username AS reviewer, r.verdict AS review_verdict, r.comment AS review_comment, r.ts AS reviewed_at "
            "FROM decisions d LEFT JOIN decision_reviews r ON r.decision_id = d.id "
            "ORDER BY d.id DESC LIMIT ?", conn, params=(limit,))
    finally:
        conn.close()
    if df.empty:
        df["status"] = []
        return df
    def status(r):
        if not r["needs_review"]:
            return "Final"
        if pd.isna(r["review_verdict"]):
            return "Pending second approval"
        return {"approved": "Final (approved by reviewer)", "rejected": "Rejected by reviewer",
                "returned": "Returned to officer"}[r["review_verdict"]]
    df["status"] = df.apply(status, axis=1)
    return df


REVIEW_SLA_DAYS = 2      # a case should not wait longer than this for its second approval


def add_timing(df: pd.DataFrame) -> pd.DataFrame:
    """Date facts for every saved decision:
    received        - application date from the saved inputs (blank for older records)
    days_to_decide  - days from receipt to the officer's decision
    days_waiting    - for a case pending second approval, days since it was saved
    over_sla        - pending longer than REVIEW_SLA_DAYS"""
    out = df.copy()
    if out.empty:
        for c in ("received", "days_to_decide", "days_waiting", "over_sla"):
            out[c] = []
        return out
    out["received"] = [json.loads(i or "{}").get("application_date", "") for i in out["inputs"]]
    saved_local = pd.to_datetime(out["created_at"], utc=True).dt.tz_convert("Asia/Phnom_Penh").dt.tz_localize(None)
    rec = pd.to_datetime(out["received"], errors="coerce")
    out["days_to_decide"] = (saved_local.dt.normalize() - rec).dt.days.astype("Int64")
    now = pd.Timestamp.now(tz="UTC")
    waited = ((now - pd.to_datetime(out["created_at"], utc=True)).dt.total_seconds() // 86400).astype("Int64")
    pending = out["status"] == "Pending second approval"
    out["days_waiting"] = waited.where(pending)
    out["over_sla"] = pending & (waited > REVIEW_SLA_DAYS)
    return out


def customer_history(customer_ref: str, limit: int = 5000) -> pd.DataFrame:
    """Every earlier decision for the same customer / case reference, newest first, with the
    application date taken from the saved inputs. Used to show an officer a repeat applicant."""
    ref = (customer_ref or "").strip()
    df = decisions(limit)
    if not ref or df.empty:
        return pd.DataFrame(columns=["application_id", "created_at", "application_date", "outcome",
                                     "loan_amount", "status", "username"])
    df = df[df["customer_ref"].str.strip().str.lower() == ref.lower()].copy()
    df["application_date"] = [json.loads(i or "{}").get("application_date", "") for i in df["inputs"]]
    return df[["application_id", "created_at", "application_date", "outcome", "loan_amount", "status", "username"]]


def inputs_frame(limit: int = 5000) -> pd.DataFrame:
    """Application inputs of saved decisions as columns - the 'recent population' for drift."""
    df = decisions(limit)
    if df.empty:
        return pd.DataFrame()
    rows = [json.loads(x) for x in df["inputs"]]
    out = pd.DataFrame(rows)
    out["application_id"] = df["application_id"].values
    out["probability"] = df["probability"].values
    return out
