"""
app_store.py
============
Credit Desk - the loan applications behind every chart, kept in the SQLite database.

Until v22 the analysis pages read ``data/loan_data.csv`` directly. Now that file (or an extract an
Administrator loads under Data and governance > Data source) is IMPORTED ONCE, value for value,
into the table ``applications`` of ``data/audit_log.db``; from then on the pages read the table.
Users can add a record or remove records (Application data page) and every chart, KPI and the
model follow automatically, because the cache key is the table's change counter.

Nothing is changed on import: the same 12 columns, the same values, the same order. Running the
pipeline on the table gives exactly the frame it gave on the CSV (tests/test_v23.py checks it).

* every add / delete is written in the same transaction as a hash-chained audit entry;
* deleted rows are kept in ``applications_deleted`` (who, when, why) - nothing silently vanishes;
* a delete that would leave too few rows (or one outcome only) to train a model is refused.
"""

from __future__ import annotations

import io
import json
import math
from datetime import datetime, timezone

import pandas as pd

from src import audit

SOURCE_COLUMNS = ["application_date", "applicant_income", "coapplicant_income", "loan_amount",
                  "loan_term_months", "credit_history", "dependents", "employment_status", "property_area",
                  "credit_score", "late_payments_12m", "approved"]
INT_COLUMNS = ["loan_term_months", "credit_history", "dependents", "credit_score", "late_payments_12m", "approved"]
FLOAT_COLUMNS = ["applicant_income", "coapplicant_income", "loan_amount"]
TEXT_COLUMNS = ["application_date", "employment_status", "property_area"]
MIN_ROWS = 500                      # the model needs at least this many rows to train

_SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    application_date   TEXT,
    applicant_income   REAL,
    coapplicant_income REAL,
    loan_amount        REAL,
    loan_term_months   INTEGER,
    credit_history     INTEGER,
    dependents         INTEGER,
    employment_status  TEXT,
    property_area      TEXT,
    credit_score       INTEGER,
    late_payments_12m  INTEGER,
    approved           INTEGER,
    extra              TEXT NOT NULL DEFAULT '{}',
    added_by           TEXT NOT NULL DEFAULT 'import',
    added_ts           TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS applications_deleted (
    id          INTEGER NOT NULL,
    row_json    TEXT NOT NULL,
    deleted_by  TEXT NOT NULL,
    deleted_ts  TEXT NOT NULL,
    reason      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applications_meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _conn():
    conn = audit.connect()
    conn.executescript(_SCHEMA)
    return conn


def _meta(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM applications_meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def _set_meta(conn, key: str, value: str) -> None:
    conn.execute("INSERT INTO applications_meta (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))


def _bump(conn) -> None:
    if not _meta(conn, "epoch"):                 # one id per database file (a restored backup has its own)
        import uuid
        _set_meta(conn, "epoch", uuid.uuid4().hex[:12])
    _set_meta(conn, "version", str(int(_meta(conn, "version", "0")) + 1))


def _py(v):
    """A pandas / numpy value as a plain Python value SQLite can store (NaN -> NULL)."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


# ---- import -------------------------------------------------------------------------------
def _source_id() -> tuple[str, str, str]:
    """(key, path, name) of the active data source. The key changes on every upload / revert."""
    from src import policy_store
    src = policy_store.active_data_source()
    conn = _conn()
    try:
        row = conn.execute("SELECT MAX(id) FROM data_sources").fetchone() if conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='data_sources'").fetchone() else None
    finally:
        conn.close()
    key = f"{row[0] if row and row[0] is not None else 0}:{src.path}"
    return key, src.path, src.name


def import_frame(raw: pd.DataFrame, source_key: str, source_name: str) -> int:
    """Replace the table with ``raw`` (a CSV read by pandas), keeping every value as it is."""
    extra_cols = [c for c in raw.columns if c not in SOURCE_COLUMNS]
    rows = []
    for rec in raw.to_dict("records"):
        extra = {c: _py(rec.get(c)) for c in extra_cols}
        rows.append(tuple(_py(rec.get(c)) for c in SOURCE_COLUMNS)
                    + (json.dumps(extra, default=str), "import", ""))
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM applications")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'applications'")
        conn.executemany(
            f"INSERT INTO applications ({', '.join(SOURCE_COLUMNS)}, extra, added_by, added_ts) "
            f"VALUES ({', '.join('?' * (len(SOURCE_COLUMNS) + 3))})", rows)
        _set_meta(conn, "source_key", source_key)
        _set_meta(conn, "source_name", source_name)
        _set_meta(conn, "extra_columns", json.dumps(extra_cols))
        _bump(conn)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return len(rows)


def ensure_loaded() -> None:
    """First start (or a new data source): import the active extract into the table."""
    key, path, name = _source_id()
    conn = _conn()
    try:
        current = _meta(conn, "source_key")
    finally:
        conn.close()
    if current != key:
        import_frame(pd.read_csv(path), key, name)


def version() -> str:
    """Changes whenever a row is added or removed or the source is re-imported (the cache key)."""
    ensure_loaded()
    conn = _conn()
    try:
        return f"{_meta(conn, 'epoch')}:{_meta(conn, 'version', '0')}"
    finally:
        conn.close()


def source_name() -> str:
    conn = _conn()
    try:
        return _meta(conn, "source_name", "loan_data.csv")
    finally:
        conn.close()


# ---- read ---------------------------------------------------------------------------------
def load_frame(with_ids: bool = False) -> pd.DataFrame:
    """The table as the pipeline expects it: the source columns, in file order and file dtypes."""
    ensure_loaded()
    conn = _conn()
    try:
        df = pd.read_sql_query(
            f"SELECT id, {', '.join(SOURCE_COLUMNS)}, extra, added_by, added_ts FROM applications ORDER BY id", conn)
        extra_cols = json.loads(_meta(conn, "extra_columns", "[]"))
    finally:
        conn.close()
    if extra_cols:
        ex = pd.DataFrame([json.loads(v) for v in df["extra"]], index=df.index)
        for c in extra_cols:
            df[c] = ex[c] if c in ex else None
    # Give every column exactly the type pandas gives when it reads the same values from a CSV
    # file, so the pipeline sees the same frame as before (ints stay ints, text stays text).
    data_cols = SOURCE_COLUMNS + extra_cols
    typed = pd.read_csv(io.StringIO(df[data_cols].to_csv(index=False)))
    df = pd.concat([df[["id", "added_by", "added_ts"]].reset_index(drop=True), typed], axis=1)
    out_cols = (["id"] if with_ids else []) + SOURCE_COLUMNS + extra_cols + (["added_by", "added_ts"] if with_ids else [])
    return df[out_cols].reset_index(drop=True)


def count() -> int:
    ensure_loaded()
    conn = _conn()
    try:
        return int(conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0])
    finally:
        conn.close()


# ---- change -------------------------------------------------------------------------------
def validate_record(rec: dict) -> dict:
    """Check one new record with the same rules as Score a file. Returns the cleaned record or
    raises ValueError listing every problem."""
    from src.data_pipeline import validate_applications
    missing = [c for c in SOURCE_COLUMNS if rec.get(c) is None or str(rec.get(c)).strip() == ""]
    if missing:
        raise ValueError("Fill in: " + ", ".join(missing))
    valid, issues = validate_applications(pd.DataFrame([rec]))
    if len(issues):
        raise ValueError("; ".join(f"{r.field}: {r.problem}" for r in issues.itertuples()))
    try:
        day = pd.Timestamp(str(rec["application_date"])).date()
    except Exception:
        raise ValueError("application_date: not a date (use YYYY-MM-DD)")
    if int(rec["approved"]) not in (0, 1):
        raise ValueError("approved: must be 1 (approved) or 0 (declined)")
    row = valid.iloc[0]
    out = {"application_date": day.isoformat(),
           "employment_status": str(row["employment_status"]), "property_area": str(row["property_area"]),
           "approved": int(rec["approved"])}
    for c in FLOAT_COLUMNS:
        out[c] = float(row[c])
    for c in INT_COLUMNS:
        if c != "approved":
            out[c] = int(row[c])
    return out


def add(rec: dict, username: str, role: str) -> int:
    """Add one application record. Returns its id."""
    clean = validate_record(rec)
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            f"INSERT INTO applications ({', '.join(SOURCE_COLUMNS)}, extra, added_by, added_ts) "
            f"VALUES ({', '.join('?' * (len(SOURCE_COLUMNS) + 3))})",
            tuple(clean[c] for c in SOURCE_COLUMNS) + ("{}", username, _now()))
        rid = int(cur.lastrowid)
        _bump(conn)
        audit.append(conn, username, role, "data_row_added",
                     f"application #{rid} - {clean['application_date']} - loan {clean['loan_amount']:,.0f} - "
                     f"{'approved' if clean['approved'] else 'declined'}")
        conn.execute("COMMIT")
        return rid
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


DELETE_ROLES = {"risk", "admin"}


def delete(ids: list[int], username: str, role: str, reason: str) -> int:
    """Remove records (Risk Manager / Administrator). The removed rows are archived."""
    if role not in DELETE_ROLES:
        raise PermissionError("Only a Risk Manager or Administrator can remove records.")
    ids = sorted({int(i) for i in ids})
    if not ids:
        raise ValueError("Choose at least one record.")
    if not (reason or "").strip():
        raise ValueError("Write the reason for removing the record(s) - it is kept in the audit log.")
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        marks = ",".join("?" * len(ids))
        rows = conn.execute(f"SELECT id, {', '.join(SOURCE_COLUMNS)}, extra FROM applications WHERE id IN ({marks})",
                            ids).fetchall()
        if len(rows) != len(ids):
            raise ValueError("Some of those records no longer exist - refresh the page.")
        left = conn.execute(f"SELECT COUNT(*), COUNT(DISTINCT approved) FROM applications WHERE id NOT IN ({marks})",
                            ids).fetchone()
        if left[0] < MIN_ROWS:
            raise ValueError(f"Refused: only {left[0]:,} records would be left; the model needs at least {MIN_ROWS}.")
        if left[1] < 2:
            raise ValueError("Refused: the records left would all have the same outcome; the model needs both.")
        cols = ["id"] + SOURCE_COLUMNS + ["extra"]
        now = _now()
        conn.executemany("INSERT INTO applications_deleted (id, row_json, deleted_by, deleted_ts, reason) "
                         "VALUES (?,?,?,?,?)",
                         [(r[0], json.dumps(dict(zip(cols, r)), default=str), username, now, reason.strip())
                          for r in rows])
        conn.execute(f"DELETE FROM applications WHERE id IN ({marks})", ids)
        _bump(conn)
        shown = ", ".join(f"#{i}" for i in ids[:20]) + (f" (+{len(ids) - 20} more)" if len(ids) > 20 else "")
        audit.append(conn, username, role, "data_rows_deleted", f"{len(ids)} record(s) {shown} - {reason.strip()}")
        conn.execute("COMMIT")
        return len(ids)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def deleted(limit: int = 500) -> pd.DataFrame:
    conn = _conn()
    try:
        return pd.read_sql_query("SELECT id, deleted_by, deleted_ts, reason, row_json FROM applications_deleted "
                                 "ORDER BY rowid DESC LIMIT ?", conn, params=(limit,))
    finally:
        conn.close()
