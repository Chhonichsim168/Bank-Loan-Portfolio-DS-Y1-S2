"""
audit.py
========
Credit Desk - tamper-evident, append-only audit log.

* **Hash-chained.** Every row stores the SHA-256 of the previous row plus its own content.
  Editing or deleting any row breaks every hash after it; ``verify_chain()`` finds the break.
* **Append-only.** SQLite triggers reject UPDATE and DELETE on the table.
* **Not silent.** A failed write is logged, written to a fallback file
  (``data/audit_fallback.jsonl``) and - for anything that matters (sign-in, saved decisions,
  policy changes) - raised as ``AuditError`` so the action is refused rather than un-recorded.
* **Same transaction as the business record.** ``connect()`` + ``append()`` let a decision or
  policy change and its audit row commit together or not at all.

Honest limit: a hash chain proves tampering happened; it cannot stop someone with full
filesystem and database access from rebuilding the whole chain. For regulated use, export the
latest hash (``head_hash()``) to a system the database admin does not control, on a schedule.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger("credit_desk.audit")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("CREDIT_DESK_AUDIT_DB", ROOT / "data" / "audit_log.db"))
FALLBACK_PATH = Path(os.environ.get("CREDIT_DESK_AUDIT_FALLBACK", ROOT / "data" / "audit_fallback.jsonl"))
GENESIS = "0" * 64


class AuditError(RuntimeError):
    """The audit trail could not be written; the action it describes must not proceed."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    username  TEXT NOT NULL,
    role      TEXT NOT NULL,
    action    TEXT NOT NULL,
    detail    TEXT NOT NULL DEFAULT '',
    prev_hash TEXT NOT NULL,
    hash      TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    """A connection in autocommit mode (callers open transactions explicitly with
    ``BEGIN IMMEDIATE``), with the audit schema guaranteed to exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        cols = [r[1] for r in conn.execute("PRAGMA table_info(events)")]
        if cols and "hash" not in cols:
            # A pre-chain database: keep it, read-only, under another name and start a clean chain.
            conn.execute("ALTER TABLE events RENAME TO events_legacy")
        conn.executescript(_SCHEMA)
    except Exception:
        conn.close()
        raise
    return conn


def _digest(prev: str, ts: str, username: str, role: str, action: str, detail: str) -> str:
    payload = json.dumps([prev, ts, username, role, action, detail], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def append(conn: sqlite3.Connection, username: str, role: str, action: str, detail: str = "") -> str:
    """Add one chained row using the caller's connection (and therefore the caller's
    transaction). Returns the new row's hash."""
    row = conn.execute("SELECT hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
    prev = row[0] if row else GENESIS
    ts = _now()
    h = _digest(prev, ts, username, role, action, detail)
    conn.execute(
        "INSERT INTO events (ts, username, role, action, detail, prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
        (ts, username, role, action, detail, prev, h))
    return h


def _fallback(record: dict) -> None:
    """Last-resort record of an event the database refused. Best effort, never raises."""
    try:
        FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(FALLBACK_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        os.chmod(FALLBACK_PATH, 0o600)
    except Exception:  # pragma: no cover - nothing left to try
        logger.critical("AUDIT FAILURE and fallback file also failed: %s", record)


def log_event(username: str, role: str, action: str, detail: str = "", *, strict: bool = True) -> bool:
    """Append one event in its own transaction.

    ``strict=True`` (default): a failure is logged, written to the fallback file and raised as
    ``AuditError``. ``strict=False`` is for low-value telemetry only; the failure is still
    logged and written to the fallback file, and the function returns False."""
    conn = None
    try:
        conn = connect()
        conn.execute("BEGIN IMMEDIATE")
        append(conn, username, role, action, detail)
        conn.execute("COMMIT")
        return True
    except Exception as exc:
        try:
            if conn is not None:
                conn.execute("ROLLBACK")
        except Exception:
            pass
        logger.error("Audit write failed (%s %s): %s", username, action, exc)
        _fallback({"ts": _now(), "username": username, "role": role, "action": action,
                   "detail": detail, "error": str(exc)})
        if strict:
            raise AuditError(f"Audit log unavailable - action not recorded: {exc}") from exc
        return False
    finally:
        if conn is not None:
            conn.close()


def log_if_changed(cache_key: str, username: str, role: str, action: str, detail: str) -> None:
    """Log only when ``detail`` differs from the last value logged under ``cache_key`` in this
    session (one entry per settled change rather than one per slider tick)."""
    import streamlit as st

    state_key = f"_audit_last_{cache_key}"
    if st.session_state.get(state_key) == detail:
        return
    log_event(username, role, action, detail, strict=False)
    st.session_state[state_key] = detail


def fetch_events(limit: int = 300) -> pd.DataFrame:
    """Most recent events first. Empty, correctly-shaped frame if nothing is logged yet."""
    cols = ["id", "ts", "username", "role", "action", "detail"]
    try:
        conn = connect()
        try:
            return pd.read_sql_query(
                "SELECT id, ts, username, role, action, detail FROM events ORDER BY id DESC LIMIT ?",
                conn, params=(limit,))
        finally:
            conn.close()
    except Exception as exc:
        logger.error("Could not read audit log: %s", exc)
        return pd.DataFrame(columns=cols)


def head_hash() -> str:
    """Hash of the newest row - export this somewhere the database admin cannot edit."""
    conn = connect()
    try:
        row = conn.execute("SELECT hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    return row[0] if row else GENESIS


def verify_chain() -> tuple[bool, int, int | None]:
    """Walk the whole chain. Returns (intact, rows_checked, first_bad_id)."""
    conn = connect()
    try:
        prev, n = GENESIS, 0
        for id_, ts, u, r, a, d, p, h in conn.execute(
                "SELECT id, ts, username, role, action, detail, prev_hash, hash FROM events ORDER BY id"):
            if p != prev or _digest(p, ts, u, r, a, d) != h:
                return False, n, id_
            prev, n = h, n + 1
        return True, n, None
    finally:
        conn.close()
