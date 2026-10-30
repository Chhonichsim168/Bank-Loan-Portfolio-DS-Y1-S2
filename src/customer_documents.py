"""Ownership checks around the existing hashed supporting-document store."""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from src import audit, customer_portal as portal, documents

SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_document_withdrawals (
    document_id INTEGER PRIMARY KEY REFERENCES case_documents(id), username TEXT NOT NULL, withdrawn_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_document_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL REFERENCES case_documents(id),
    status TEXT NOT NULL CHECK(status IN ('Accepted','Needs replacement')),
    note TEXT NOT NULL, reviewed_by TEXT NOT NULL, reviewed_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS customer_document_reviews_no_update BEFORE UPDATE ON customer_document_reviews
BEGIN SELECT RAISE(ABORT, 'document reviews are append-only'); END;
CREATE TRIGGER IF NOT EXISTS customer_document_reviews_no_delete BEFORE DELETE ON customer_document_reviews
BEGIN SELECT RAISE(ABORT, 'document reviews are append-only'); END;
"""


def initialize():
    conn = documents._conn()
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()


def _access(request_id, upload=False):
    user = portal.require_role("customer") if upload else portal.require_role("customer", *portal.STAFF)
    conn = portal.connect()
    try:
        row = conn.execute("SELECT r.username,r.status,c.cancelled_at FROM customer_requests r "
                           "LEFT JOIN customer_request_cancellations c ON c.request_id=r.request_id "
                           "WHERE r.request_id=?", (request_id,)).fetchone()
        if not row or (user.role == "customer" and row[0] != user.username):
            raise PermissionError("This request is not available to your account.")
        if upload and (row[1] != "Pending review" or row[2]):
            raise ValueError("Documents can be uploaded while the request is pending review. Contact support for later changes.")
        return user
    finally:
        conn.close()


def attach(request_id, content, filename, kind):
    user = _access(request_id, upload=True)
    suffix = Path(filename or "").suffix.lower()
    if suffix not in documents.ALLOWED:
        raise ValueError("Choose a PDF, JPG or PNG document.")
    if not content or len(content) > documents.MAX_BYTES:
        raise ValueError("Choose a non-empty document no larger than 10 MB.")
    if suffix in {".jpg", ".jpeg", ".png"}:
        from PIL import Image, UnidentifiedImageError
        try:
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in {"JPEG", "PNG"}:
                    raise ValueError("Choose a JPG or PNG image, or a PDF document.")
                if image.width * image.height > 40_000_000:
                    raise ValueError("This image is too large. Choose a smaller scan.")
                image.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError("The scan could not be opened. Upload a valid JPG or PNG image.") from exc
    elif not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
        raise ValueError("This file is not a complete PDF. Export it again and retry.")
    # Existing store supplies safe filenames, content hashes, audit records and backup inclusion.
    def still_pending(conn):
        row = conn.execute("SELECT r.username,r.status,c.cancelled_at FROM customer_requests r "
            "LEFT JOIN customer_request_cancellations c ON c.request_id=r.request_id WHERE r.request_id=?",
            (request_id,)).fetchone()
        if not row or row[0] != user.username:
            raise PermissionError("This request is not available to your account.")
        if row[1] != "Pending review" or row[2]:
            raise ValueError("This request is no longer pending review. Refresh your records and contact support.")
    initialize()
    def record_upload(conn,document_id):
        from src import customer_undo
        customer_undo.record(conn,user.username,"document","Uploaded document",None,{"request":request_id},document_id)
    return documents.attach(f"customer-request:{request_id}", content, filename, kind, user.username, user.role,
                            guard=still_pending,on_attached=record_upload)


def for_request(request_id):
    _access(request_id)
    initialize()
    conn = portal.connect()
    try:
        return pd.read_sql_query("SELECT d.id,d.label,d.kind,d.ts,d.size,"
            "COALESCE(r.status,'Awaiting review') AS status,COALESCE(r.note,'') AS note,r.reviewed_at "
            "FROM case_documents d LEFT JOIN customer_document_reviews r ON r.id="
            "(SELECT MAX(x.id) FROM customer_document_reviews x WHERE x.document_id=d.id) "
            "WHERE d.case_id=? AND NOT EXISTS(SELECT 1 FROM customer_document_withdrawals w WHERE w.document_id=d.id) ORDER BY d.id DESC", conn, params=(f"customer-request:{request_id}",))
    finally:
        conn.close()


def download(request_id, document_id):
    allowed = for_request(request_id)
    if allowed.empty or document_id not in set(allowed["id"]):
        raise PermissionError("This document is not available for this request.")
    return documents.read(int(document_id))


def review(request_id, document_id, status, note):
    user = portal.require_role(*portal.STAFF)
    allowed = for_request(request_id)
    if allowed.empty or document_id not in set(allowed["id"]):
        raise PermissionError("This document is not available for this request.")
    if status not in {"Accepted", "Needs replacement"}:
        raise ValueError("Choose Accepted or Needs replacement.")
    note = str(note).strip()
    if len(note) > 2000 or (status == "Needs replacement" and not note):
        raise ValueError("Explain what needs replacing in a note within 2,000 characters.")
    with portal.transaction("customer_document_reviewed", f"{request_id}: document {document_id}: {status}") as conn:
        if conn.execute("SELECT 1 FROM customer_document_withdrawals WHERE document_id=?",(document_id,)).fetchone():
            raise ValueError("This document was withdrawn. Refresh the request before reviewing.")
        conn.execute("INSERT INTO customer_document_reviews (document_id,status,note,reviewed_by,reviewed_at) "
                     "VALUES (?,?,?,?,?)", (document_id,status,note,user.username,audit._now()))


def review_notifications():
    user = portal.require_role("customer")
    initialize()
    conn = portal.connect()
    try:
        rows = conn.execute("SELECT r.id,r.status,r.reviewed_at,d.label FROM customer_document_reviews r "
            "JOIN case_documents d ON d.id=r.document_id JOIN customer_requests a "
            "ON d.case_id='customer-request:' || a.request_id WHERE a.username=?", (user.username,)).fetchall()
        return [dict(id=f"document-review:{r[0]}", title="Document review update", body=f"{r[3]}: {r[1]}. "
                     "Open the document section in your request history for details.", ts=r[2], tone="info") for r in rows]
    finally:
        conn.close()
