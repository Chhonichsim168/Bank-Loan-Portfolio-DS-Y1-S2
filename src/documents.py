"""
documents.py
============
Credit Desk - supporting documents attached to a case (ID copy, payslip, valuation, contract...).

Files are stored on this computer only, in ``data/documents`` (owner-only), under a name derived from
their SHA-256 - the uploader's file name is just a display label. Each attachment is an append-only
database row written in the same transaction as a hash-chained audit entry, and its hash is checked
again whenever it is downloaded, so a file swapped on disk is refused.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src import audit
from src.security import safe_filename

ROOT = Path(__file__).resolve().parent.parent
DOC_DIR = Path(os.environ.get("CREDIT_DESK_DOC_DIR", ROOT / "data" / "documents"))
ALLOWED = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
MAX_BYTES = 10 * 1024 * 1024
_MAGIC = {".pdf": (b"%PDF",), ".png": (b"\x89PNG",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",)}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS case_documents (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    case_id   TEXT NOT NULL,
    username  TEXT NOT NULL,
    label     TEXT NOT NULL,
    kind      TEXT NOT NULL,
    filename  TEXT NOT NULL,
    sha256    TEXT NOT NULL,
    size      INTEGER NOT NULL,
    stored    TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS case_documents_no_update BEFORE UPDATE ON case_documents
BEGIN SELECT RAISE(ABORT, 'documents log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS case_documents_no_delete BEFORE DELETE ON case_documents
BEGIN SELECT RAISE(ABORT, 'documents log is append-only'); END;
"""

KINDS = ["Identity", "Income proof", "Bank statement", "Collateral / valuation", "Contract", "Other"]


# Words in the file name (or, for a PDF, its text) that tell what the document is. Checked in
# this order; the first match wins. Nothing matches -> "Other".
KIND_WORDS = (
    ("Identity", ("identity", "id_card", "idcard", "id card", "national_id", "passport", "nid", "kyc",
                  "identity document")),
    ("Income proof", ("income", "payslip", "pay_slip", "pay slip", "salary", "payroll", "employment_letter",
                      "income proof")),
    ("Bank statement", ("bank_statement", "bank statement", "statement", "bank")),
    ("Collateral / valuation", ("collateral", "valuation", "appraisal", "land_title", "hard_title",
                                "property_title", "title_deed")),
    ("Contract", ("contract", "agreement", "loan_agreement")),
)


def _words(text: str) -> str:
    return " " + "".join(ch if ch.isalnum() else " " for ch in text.lower()) + " "


def detect_kind(file_name: str, content: bytes = b"") -> tuple[str, str]:
    """(document type, short reason). Reads the file name first, then the start of a PDF."""
    name = _words(Path(file_name or "").stem)
    for kind, words in KIND_WORDS:
        for w in words:
            if _words(w) in name:
                return kind, f'the file name contains "{w}"'
    if content[:4] == b"%PDF":
        text = _words(content[:200_000].decode("latin-1", errors="ignore"))
        for kind, words in KIND_WORDS:
            for w in words:
                if len(w) > 4 and _words(w) in text:
                    return kind, f'the document mentions "{w}"'
    return "Other", "no known keyword in the file name"


def _conn():
    conn = audit.connect()
    conn.executescript(_SCHEMA)
    return conn


def attach(case_id: str, content: bytes, original_name: str, kind: str, username: str, role: str) -> int:
    ext = Path(original_name or "").suffix.lower()
    if ext not in ALLOWED:
        raise ValueError("Only PDF, PNG and JPG files can be attached.")
    if not content or len(content) > MAX_BYTES:
        raise ValueError("The file is empty or larger than 10 MB.")
    if not any(content.startswith(m) for m in _MAGIC[ext]):
        raise ValueError("The file contents do not match its extension.")
    if kind not in KINDS:
        raise ValueError("Choose what kind of document this is.")
    digest = hashlib.sha256(content).hexdigest()
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(DOC_DIR, 0o700)
    path = DOC_DIR / f"{digest}{ext}"
    if not path.exists():
        path.write_bytes(content)
        os.chmod(path, 0o600)
    label = safe_filename(original_name)
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "INSERT INTO case_documents (ts, case_id, username, label, kind, filename, sha256, size, stored) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), case_id, username, label, kind,
             label, digest, len(content), path.name))
        audit.append(conn, username, role, "document_attached", f"{case_id} - {kind} - {label} - sha256 {digest[:16]}")
        conn.execute("COMMIT")
        return int(cur.lastrowid)
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise audit.AuditError(f"Document was NOT attached: {exc}") from exc
    finally:
        conn.close()


def for_case(case_id: str) -> pd.DataFrame:
    conn = _conn()
    try:
        return pd.read_sql_query(
            "SELECT id, ts, username, kind, label, size, sha256 FROM case_documents WHERE case_id = ? ORDER BY id",
            conn, params=(case_id,))
    finally:
        conn.close()


def read(doc_id: int) -> tuple[bytes, str, str]:
    """(content, label, mime). Raises if the stored file is missing or no longer matches its hash."""
    conn = _conn()
    try:
        row = conn.execute("SELECT label, sha256, stored FROM case_documents WHERE id = ?", (doc_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise ValueError("Unknown document.")
    label, digest, stored = row
    path = DOC_DIR / stored
    if not path.exists():
        raise FileNotFoundError("The stored file is missing.")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Integrity check failed: the stored file was changed after it was attached.")
    return data, label, ALLOWED.get(path.suffix.lower(), "application/octet-stream")
