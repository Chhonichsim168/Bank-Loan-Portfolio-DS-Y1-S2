"""
policy_store.py
===============
Credit Desk - versioned, shared lending policy and data-source records.

Why this exists: policy rules, the model cut-off and the active data extract used to live in
``st.session_state``, which is private to one browser session and lost at sign-out. A Risk
Manager's change never reached a Credit Officer. Here they live in the database, so every
user scores against the same, *versioned* rule set.

Change control (four eyes):
    propose -> approve | reject
A proposal carries the full settings payload and a written reason. A different user with the
Risk Manager or Administrator role must approve it before it becomes the active version.
(Single-operator installs can set ``CREDIT_DESK_SINGLE_OPERATOR=1``; self-approval is then
allowed but recorded as such.)

All tables are append-only (triggers) and every action is also written to the hash-chained
audit log.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from src import audit
from src import decisioning as dec

ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = ROOT / "data" / "uploads"
DEFAULT_DATA = ROOT / "data" / "loan_data.csv"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS policy_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    username  TEXT NOT NULL,
    role      TEXT NOT NULL,
    kind      TEXT NOT NULL CHECK (kind IN ('propose', 'approve', 'reject')),
    ref_id    INTEGER,
    reason    TEXT NOT NULL DEFAULT '',
    payload   TEXT
);
CREATE TRIGGER IF NOT EXISTS policy_log_no_update BEFORE UPDATE ON policy_log
BEGIN SELECT RAISE(ABORT, 'policy log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS policy_log_no_delete BEFORE DELETE ON policy_log
BEGIN SELECT RAISE(ABORT, 'policy log is append-only'); END;

CREATE TABLE IF NOT EXISTS data_sources (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    username  TEXT NOT NULL,
    name      TEXT NOT NULL,
    path      TEXT NOT NULL,
    sha256    TEXT NOT NULL,
    rows      INTEGER NOT NULL DEFAULT 0
);
CREATE TRIGGER IF NOT EXISTS data_sources_no_update BEFORE UPDATE ON data_sources
BEGIN SELECT RAISE(ABORT, 'data source log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS data_sources_no_delete BEFORE DELETE ON data_sources
BEGIN SELECT RAISE(ABORT, 'data source log is append-only'); END;
"""


def _conn():
    conn = audit.connect()
    conn.executescript(_SCHEMA)
    return conn


@dataclass
class Settings:
    """Everything a risk manager can change, as one immutable-by-convention payload."""
    max_dti: float = 0.45
    max_lti: float = 3.5
    require_credit_history: bool = True
    exclude_unemployed: bool = True
    min_credit_score: int = 580
    max_late_payments: int = 2
    cutoff: float = 0.50
    officer_authority_limit: float = 250_000.0   # larger loans need a second approver
    max_total_dti: float = 0.55                  # new loan + EXISTING monthly debts, over income
    # --- pricing and loss assumptions (editable; replace with your own experience) -----------
    base_rate: float = 0.085                     # annual rate for the best band
    spread_review: float = 0.010                 # added for the "Review" band
    spread_refer: float = 0.030                  # added for the "Refer" band
    lgd_unsecured: float = 0.60                  # loss given default with no collateral
    collateral_haircut: float = 0.30             # collateral counted at (1 - haircut) of its value
    pd_fast_track: float = 0.02                  # assumed 12-month default probability per band
    pd_review: float = 0.05
    pd_refer: float = 0.12
    pd_decline: float = 0.25
    # --- portfolio limits that raise an alert on the Loan book page ---------------------------
    max_npl_ratio: float = 0.05
    max_area_share: float = 0.60
    max_single_share: float = 0.10

    def policy(self) -> dec.Policy:
        return dec.Policy(
            max_dti=self.max_dti, max_lti=self.max_lti,
            require_credit_history=self.require_credit_history,
            exclude_unemployed=self.exclude_unemployed,
            min_credit_score=int(self.min_credit_score),
            max_late_payments=int(self.max_late_payments),
            max_total_dti=self.max_total_dti,
            # FIX: check affordability at the highest rate an approved customer can be charged
            # (base rate + the larger band spread), not at a fixed illustrative 8.5%.
            assessment_rate=self.base_rate + max(self.spread_review, self.spread_refer),
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "Settings":
        raw = json.loads(text)
        known = {k: raw[k] for k in cls.__dataclass_fields__ if k in raw}
        return cls(**known)


@dataclass
class ActiveSettings:
    version: int            # id of the approved proposal; 0 = built-in defaults
    settings: Settings
    proposed_by: str = ""
    approved_by: str = ""
    effective_from: str = ""
    reason: str = "Built-in defaults"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def single_operator() -> bool:
    from src.mode import single_operator as _so
    return _so()


def validate(s: Settings) -> list[str]:
    errs = []
    if not 0.05 <= s.max_dti <= 1.0:
        errs.append("Maximum DTI must be between 5% and 100%.")
    if not 0.5 <= s.max_lti <= 15:
        errs.append("Maximum loan-to-income must be between 0.5x and 15x.")
    if not 0.05 <= s.cutoff <= 0.95:
        errs.append("Cut-off must be between 0.05 and 0.95.")
    if s.officer_authority_limit < 0:
        errs.append("Officer authority limit cannot be negative.")
    if not 0.05 <= s.max_total_dti <= 1.5:
        errs.append("Maximum total debt service must be between 5% and 150%.")
    if not 0.0 <= s.base_rate <= 0.60:
        errs.append("Base rate must be between 0% and 60%.")
    if not (0 <= s.spread_review <= 0.30 and 0 <= s.spread_refer <= 0.30):
        errs.append("Rate spreads must be between 0% and 30%.")
    if not 0.0 <= s.lgd_unsecured <= 1.0 or not 0.0 <= s.collateral_haircut <= 1.0:
        errs.append("LGD and collateral haircut must be between 0% and 100%.")
    pds = (s.pd_fast_track, s.pd_review, s.pd_refer, s.pd_decline)
    if any(not 0 <= x <= 1 for x in pds) or list(pds) != sorted(pds):
        errs.append("Default probabilities must be between 0% and 100% and not fall as the band gets riskier.")
    if not (0 < s.max_npl_ratio <= 1 and 0 < s.max_area_share <= 1 and 0 < s.max_single_share <= 1):
        errs.append("Portfolio limits must be between 0% and 100%.")
    return errs


def active() -> ActiveSettings:
    """The approved settings every page scores against."""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT a.id, a.ts, a.username, a.reason, p.id, p.username, p.reason, p.payload "
            "FROM policy_log a JOIN policy_log p ON p.id = a.ref_id "
            "WHERE a.kind = 'approve' ORDER BY a.id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return ActiveSettings(0, Settings())
    a_id, a_ts, a_user, _a_reason, p_id, p_user, p_reason, payload = row
    return ActiveSettings(version=p_id, settings=Settings.from_json(payload), proposed_by=p_user,
                          approved_by=a_user, effective_from=a_ts, reason=p_reason)


def propose(settings: Settings, username: str, role: str, reason: str) -> int:
    errs = validate(settings)
    if errs:
        raise ValueError(" ".join(errs))
    if not reason.strip():
        raise ValueError("Give a reason for the change - it is part of the audit record.")
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "INSERT INTO policy_log (ts, username, role, kind, reason, payload) "
            "VALUES (?, ?, ?, 'propose', ?, ?)",
            (_now(), username, role, reason.strip(), settings.to_json()))
        pid = int(cur.lastrowid)
        audit.append(conn, username, role, "policy_proposed", f"proposal #{pid}: {reason.strip()} | {settings.to_json()}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return pid


def pending() -> list[dict]:
    """Proposals not yet approved or rejected, oldest first."""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT p.id, p.ts, p.username, p.role, p.reason, p.payload FROM policy_log p "
            "WHERE p.kind = 'propose' AND NOT EXISTS "
            "(SELECT 1 FROM policy_log d WHERE d.ref_id = p.id AND d.kind IN ('approve','reject')) "
            "ORDER BY p.id").fetchall()
    finally:
        conn.close()
    return [{"id": r[0], "ts": r[1], "username": r[2], "role": r[3], "reason": r[4],
             "settings": Settings.from_json(r[5])} for r in rows]


def decide(proposal_id: int, approve: bool, username: str, role: str, comment: str = "") -> None:
    if role not in {"risk", "admin"}:
        raise PermissionError("Only a Risk Manager or Administrator can decide a policy change.")
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        prop = conn.execute("SELECT username FROM policy_log WHERE id = ? AND kind = 'propose'",
                            (proposal_id,)).fetchone()
        if not prop:
            raise ValueError("Unknown proposal.")
        done = conn.execute("SELECT 1 FROM policy_log WHERE ref_id = ? AND kind IN ('approve','reject')",
                            (proposal_id,)).fetchone()
        if done:
            raise ValueError("That proposal was already decided.")
        self_approval = prop[0] == username
        if approve and self_approval and not single_operator():
            raise PermissionError("Four-eyes rule: a different user must approve your proposal.")
        kind = "approve" if approve else "reject"
        note = comment.strip() + (" [self-approval, single-operator mode]" if approve and self_approval else "")
        conn.execute(
            "INSERT INTO policy_log (ts, username, role, kind, ref_id, reason) VALUES (?, ?, ?, ?, ?, ?)",
            (_now(), username, role, kind, proposal_id, note))
        audit.append(conn, username, role, f"policy_{kind}d" if approve else "policy_rejected",
                     f"proposal #{proposal_id}. {note}".strip())
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def history(limit: int = 50) -> list[dict]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, ts, username, role, kind, ref_id, reason, payload FROM policy_log "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    return [dict(zip(["id", "ts", "username", "role", "kind", "ref_id", "reason", "payload"], r)) for r in rows]


# -----------------------------------------------------------------------------------------
# DATA SOURCE (shared across sessions, versioned, stored under a controlled name)
# -----------------------------------------------------------------------------------------
@dataclass
class DataSource:
    path: str
    name: str
    sha256: str = ""
    username: str = ""
    ts: str = ""


def active_data_source() -> DataSource:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT path, name, sha256, username, ts FROM data_sources ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    if row and Path(row[0]).exists():
        return DataSource(*row)
    return DataSource(str(DEFAULT_DATA), DEFAULT_DATA.name)


def register_data_source(content: bytes, original_name: str, username: str, rows: int,
                         role: str = "admin") -> DataSource:
    """Store an uploaded extract under a hash-derived name in a private folder and make it the
    active source for every session. The user's file name is kept only as a display label."""
    from src.security import safe_filename

    digest = hashlib.sha256(content).hexdigest()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(UPLOAD_DIR, 0o700)
    path = UPLOAD_DIR / f"{digest[:20]}.csv"
    path.write_bytes(content)
    os.chmod(path, 0o600)
    name = safe_filename(original_name)
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO data_sources (ts, username, name, path, sha256, rows) VALUES (?,?,?,?,?,?)",
                     (_now(), username, name, str(path), digest, rows))
        audit.append(conn, username, role, "change_data_source",
                     f"{name} - {rows:,} rows - sha256 {digest[:16]}")
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()
    purge_uploads(keep={str(path)})
    return DataSource(str(path), name, digest, username, _now())


def use_default_source(username: str, role: str = "admin") -> DataSource:
    """Point every session back at the bundled sample extract."""
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO data_sources (ts, username, name, path, sha256, rows) VALUES (?,?,?,?,?,?)",
                     (_now(), username, DEFAULT_DATA.name, str(DEFAULT_DATA), "bundled", 0))
        audit.append(conn, username, role, "change_data_source", f"Reverted to bundled {DEFAULT_DATA.name}")
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()
    return DataSource(str(DEFAULT_DATA), DEFAULT_DATA.name, "bundled", username, _now())


def previous_paths(n: int = 2) -> set[str]:
    conn = _conn()
    try:
        rows = conn.execute("SELECT path FROM data_sources ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


def purge_uploads(keep: set[str] | None = None, retention_days: int | None = None) -> int:
    """Delete stored extracts that are neither active nor the previous one (kept for rollback),
    and anything older than the retention window. Returns files removed."""
    import time

    keep = set(keep or ()) | previous_paths(2)
    days = retention_days if retention_days is not None else int(os.environ.get("CREDIT_DESK_RETENTION_DAYS", "90"))
    removed = 0
    if not UPLOAD_DIR.exists():
        return 0
    for f in UPLOAD_DIR.glob("*.csv"):
        too_old = (time.time() - f.stat().st_mtime) > days * 86400
        if str(f) not in keep or (too_old and str(f) != active_data_source().path):
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    return removed
