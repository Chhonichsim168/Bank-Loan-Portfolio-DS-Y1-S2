"""Private customer support threads and staff replies in the existing database."""
from __future__ import annotations

import secrets
import pandas as pd

from src import audit, customer_portal as portal

SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_support_tickets (
    ticket_id TEXT PRIMARY KEY, username TEXT NOT NULL, subject TEXT NOT NULL,
    loan_id TEXT REFERENCES loans(loan_id), created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Open' CHECK(status IN ('Open','Resolved'))
);
CREATE INDEX IF NOT EXISTS support_ticket_owner ON customer_support_tickets(username);
CREATE TABLE IF NOT EXISTS customer_support_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id TEXT NOT NULL REFERENCES customer_support_tickets(ticket_id),
    sender TEXT NOT NULL, role TEXT NOT NULL, body TEXT NOT NULL, sent_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS support_message_withdrawals (
    message_id INTEGER PRIMARY KEY REFERENCES customer_support_messages(id),
    username TEXT NOT NULL, withdrawn_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_support_read (
    username TEXT NOT NULL, ticket_id TEXT NOT NULL REFERENCES customer_support_tickets(ticket_id),
    last_message_id INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(username,ticket_id)
);
CREATE INDEX IF NOT EXISTS support_messages_ticket ON customer_support_messages(ticket_id,id);
CREATE TRIGGER IF NOT EXISTS support_messages_no_update BEFORE UPDATE ON customer_support_messages
BEGIN SELECT RAISE(ABORT, 'support messages are append-only'); END;
-- Retention is the only permitted message deletion; active chats remain protected.
DROP TRIGGER IF EXISTS support_messages_no_delete;
CREATE TRIGGER support_messages_no_delete BEFORE DELETE ON customer_support_messages
WHEN COALESCE((SELECT julianday(MAX(sent_at)) FROM customer_support_messages
               WHERE ticket_id=OLD.ticket_id), julianday('now')) > julianday('now', '-24 hours')
BEGIN SELECT RAISE(ABORT, 'active support messages cannot be deleted'); END;
"""


def initialize():
    conn = portal.connect()
    try:
        conn.executescript(SCHEMA)
        conn.execute("BEGIN IMMEDIATE")
        try:
            expired = [row[0] for row in conn.execute(
                "SELECT t.ticket_id FROM customer_support_tickets t "
                "LEFT JOIN customer_support_messages m ON m.ticket_id=t.ticket_id "
                "GROUP BY t.ticket_id HAVING julianday(COALESCE(MAX(m.sent_at),t.created_at)) "
                "<= julianday('now','-24 hours')")]
            for tid in expired:
                conn.execute("DELETE FROM customer_notifications_read WHERE notification_id IN "
                    "(SELECT 'support:' || id FROM customer_support_messages WHERE ticket_id=?)", (tid,))
                conn.execute("DELETE FROM customer_support_read WHERE ticket_id=?", (tid,))
                conn.execute("DELETE FROM support_message_withdrawals WHERE message_id IN (SELECT id FROM customer_support_messages WHERE ticket_id=?)",(tid,))
                conn.execute("DELETE FROM customer_support_messages WHERE ticket_id=?", (tid,))
                conn.execute("DELETE FROM customer_support_tickets WHERE ticket_id=?", (tid,))
            if expired:
                audit.append(conn, "system", "system", "support_retention_cleanup",
                             f"Deleted {len(expired)} support chats inactive for at least 24 hours.")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def _body(text):
    text = str(text).strip()
    if not text or len(text) > 5000:
        raise ValueError("Enter a message within 5,000 characters.")
    return text


def _ticket(conn, ticket_id, user):
    cur = conn.execute("SELECT * FROM customer_support_tickets WHERE ticket_id=?", (ticket_id,))
    row = cur.fetchone()
    if not row or (user.role == "customer" and row[1] != user.username):
        raise PermissionError("This conversation is not available to your account.")
    ticket = dict(zip([c[0] for c in cur.description], row))
    expired = conn.execute("SELECT julianday(COALESCE(MAX(sent_at),?)) <= julianday('now','-24 hours') "
                           "FROM customer_support_messages WHERE ticket_id=?",
                           (ticket["created_at"], ticket_id)).fetchone()[0]
    if expired:
        raise PermissionError("This chat has expired after 24 hours. Start a new chat to contact support.")
    return ticket


AUTO_REPLY = ("Thanks for your message! Our support team will reply as soon as possible. "
              "Please check this chat for updates.")


def _acknowledge(conn, ticket_id):
    if conn.execute("SELECT 1 FROM customer_support_messages WHERE ticket_id=? AND role='bot' LIMIT 1",
                    (ticket_id,)).fetchone():
        return
    conn.execute("INSERT INTO customer_support_messages (ticket_id,sender,role,body,sent_at) VALUES (?,?,?,?,?)",
                 (ticket_id, "support-bot", "bot", AUTO_REPLY, audit._now()))


def create_ticket(subject, message, loan_id=None):
    user = portal.require_role("customer")
    subject, message = str(subject).strip(), _body(message)
    if not subject or len(subject) > 120:
        raise ValueError("Enter a subject within 120 characters.")
    if loan_id:
        portal.loan_details(loan_id)  # only the customer's own loans may be referenced
    initialize()
    ticket_id = "SUP-" + secrets.token_hex(5).upper()
    with portal.transaction("customer_support_opened", ticket_id) as conn:
        conn.execute("INSERT INTO customer_support_tickets "
                     "(ticket_id,username,subject,loan_id,created_at) VALUES (?,?,?,?,?)",
                     (ticket_id,user.username,subject,loan_id or None,audit._now()))
        sent = conn.execute("INSERT INTO customer_support_messages (ticket_id,sender,role,body,sent_at) VALUES (?,?,?,?,?)",
                     (ticket_id,user.username,user.role,message,audit._now()))
        from src import customer_undo
        customer_undo.record(conn,user.username,"message","Sent message",None,{"ticket":ticket_id},sent.lastrowid)
        _acknowledge(conn, ticket_id)
    return ticket_id


def tickets():
    user = portal.require_role("customer", *portal.STAFF)
    initialize()
    conn = portal.connect()
    try:
        where, params = ("WHERE t.username=?", (user.username,)) if user.role == "customer" else ("", ())
        frame = pd.read_sql_query("SELECT t.*,p.full_name,"
            "(SELECT MAX(sent_at) FROM customer_support_messages m WHERE m.ticket_id=t.ticket_id) AS last_update, "
            "(SELECT CASE WHEN EXISTS(SELECT 1 FROM support_message_withdrawals w WHERE w.message_id=m.id) "
            "THEN 'Message withdrawn' ELSE m.body END FROM customer_support_messages m WHERE m.ticket_id=t.ticket_id ORDER BY id DESC LIMIT 1) AS preview, "
            "(SELECT role FROM customer_support_messages m WHERE m.ticket_id=t.ticket_id AND role!='bot' AND NOT EXISTS(SELECT 1 FROM support_message_withdrawals w WHERE w.message_id=m.id) "
            " ORDER BY id DESC LIMIT 1) AS last_sender "
            "FROM customer_support_tickets t LEFT JOIN customer_profiles p ON p.username=t.username "
            + where + " ORDER BY last_update DESC,t.ticket_id", conn, params=params)
        frame["loan_id"] = frame["loan_id"].map(lambda value: value.strip() if isinstance(value,str) and value.strip() else None)
        frame["unread"] = [conn.execute(
            "SELECT COUNT(*) FROM customer_support_messages m WHERE m.ticket_id=? "
            "AND NOT EXISTS(SELECT 1 FROM support_message_withdrawals w WHERE w.message_id=m.id) "
            "AND m.id>COALESCE((SELECT last_message_id FROM customer_support_read WHERE username=? AND ticket_id=?),0) "
            + ("AND m.role IN ('admin','risk','officer')" if user.role == "customer" else "AND m.role='customer'"),
            (tid,user.username,tid)).fetchone()[0] for tid in frame["ticket_id"]]
        frame["waiting"] = (frame["status"] == "Open") & (frame["last_sender"] == "customer")
        return frame
    finally:
        conn.close()


def overdue_notices():
    """System-generated loan facts for this customer; never pretend these are staff messages."""
    portal.require_role("customer")
    from src.data_pipeline import today_local
    notices=[]
    loans=portal.my_loans()
    for lid in loans["loan_id"] if not loans.empty else []:
        loan,snap,schedule,_=portal.loan_details(lid)
        missed=schedule[schedule["payment_status"] == "Overdue"]
        if snap["status"] != "Active" or missed.empty:
            continue
        due=missed["due_date"].iloc[0]
        notices.append(dict(loan_id=lid,amount=round(float(missed["amount_due"].sum()),2),
            due_date=due,days_late=(today_local().date()-due).days,installments=len(missed)))
    return sorted(notices,key=lambda row:row["due_date"])


def messages(ticket_id):
    user = portal.require_role("customer", *portal.STAFF)
    initialize()
    conn = portal.connect()
    try:
        _ticket(conn, ticket_id, user)
        return pd.read_sql_query("SELECT m.id,m.sender,m.role,CASE WHEN EXISTS(SELECT 1 FROM support_message_withdrawals w WHERE w.message_id=m.id) "
            "THEN 'Message withdrawn' ELSE m.body END AS body,m.sent_at, "
            "CASE WHEN m.role='customer' AND EXISTS (SELECT 1 FROM customer_support_read r "
            "JOIN customer_support_tickets t ON t.ticket_id=r.ticket_id "
            "WHERE r.ticket_id=m.ticket_id AND r.username!=t.username AND r.last_message_id>=m.id) "
            "THEN 'Seen' ELSE 'Sent' END AS delivery "
            "FROM customer_support_messages m WHERE m.ticket_id=? ORDER BY m.id", conn, params=(ticket_id,))
    finally:
        conn.close()


def chat_profiles(ticket_id):
    """Expose identity only for participants of an authorized conversation."""
    user = portal.require_role("customer", *portal.STAFF)
    initialize()
    conn = portal.connect()
    try:
        _ticket(conn, ticket_id, user)
        rows = conn.execute("SELECT DISTINCT m.sender,p.full_name,f.image FROM customer_support_messages m "
            "LEFT JOIN customer_profiles p ON p.username=m.sender "
            "LEFT JOIN customer_photos f ON f.username=m.sender "
            "WHERE m.ticket_id=? AND m.role!='bot'", (ticket_id,)).fetchall()
        from src import auth
        accounts = auth._read_users()
        return {sender: {"name": name or accounts.get(sender,{}).get("display_name") or sender,
                         "photo": photo} for sender,name,photo in rows}
    finally:
        conn.close()


def mark_read(ticket_id, last_message_id):
    user = portal.require_role("customer", *portal.STAFF)
    conn = portal.connect()
    try:
        previous = conn.execute("SELECT last_message_id FROM customer_support_read WHERE username=? AND ticket_id=?",
                                (user.username,ticket_id)).fetchone()
        if previous and previous[0] >= int(last_message_id):
            return
    finally:
        conn.close()
    with portal.transaction("support_chat_read", ticket_id) as conn:
        _ticket(conn, ticket_id, user)
        maximum = conn.execute("SELECT COALESCE(MAX(id),0) FROM customer_support_messages WHERE ticket_id=?",
                               (ticket_id,)).fetchone()[0]
        boundary = min(int(last_message_id), maximum)
        previous = conn.execute("SELECT last_message_id FROM customer_support_read WHERE username=? AND ticket_id=?",
                                (user.username,ticket_id)).fetchone()
        if previous and previous[0] >= boundary:
            return
        conn.execute("INSERT INTO customer_support_read VALUES (?,?,?) ON CONFLICT(username,ticket_id) "
                     "DO UPDATE SET last_message_id=MAX(last_message_id,excluded.last_message_id)",
                     (user.username,ticket_id,boundary))
        if user.role == "customer":
            conn.execute("INSERT OR IGNORE INTO customer_notifications_read (username,notification_id,read_at) "
                "SELECT ?, 'support:' || id, ? FROM customer_support_messages WHERE ticket_id=? AND id<=? "
                "AND role IN ('admin','risk','officer')", (user.username,audit._now(),ticket_id,boundary))


def reply(ticket_id, message):
    user = portal.require_role("customer", *portal.STAFF)
    message = _body(message)
    initialize()
    with portal.transaction("customer_support_reply", ticket_id) as conn:
        _ticket(conn, ticket_id, user)
        sent = conn.execute("INSERT INTO customer_support_messages (ticket_id,sender,role,body,sent_at) VALUES (?,?,?,?,?)",
                     (ticket_id,user.username,user.role,message,audit._now()))
        from src import customer_undo
        customer_undo.record(conn,user.username,"message","Sent message",None,{"ticket":ticket_id},sent.lastrowid)
        if user.role == "customer":
            _acknowledge(conn, ticket_id)
        conn.execute("UPDATE customer_support_tickets SET status='Open' WHERE ticket_id=?", (ticket_id,))


def set_status(ticket_id, status):
    user = portal.require_role(*portal.STAFF)
    if status not in {"Open", "Resolved"}:
        raise ValueError("Choose Open or Resolved.")
    initialize()
    with portal.transaction("customer_support_status", f"{ticket_id}: {status}") as conn:
        _ticket(conn, ticket_id, user)
        conn.execute("UPDATE customer_support_tickets SET status=? WHERE ticket_id=?", (status,ticket_id))


def reply_notifications():
    user = portal.require_role("customer")
    initialize()
    conn = portal.connect()
    try:
        rows = conn.execute("SELECT m.id,t.subject,m.sent_at FROM customer_support_messages m "
                            "JOIN customer_support_tickets t ON t.ticket_id=m.ticket_id "
                            "WHERE t.username=? AND NOT EXISTS(SELECT 1 FROM support_message_withdrawals w WHERE w.message_id=m.id) AND m.role IN ('admin','risk','officer')", (user.username,)).fetchall()
        return [dict(id=f"support:{r[0]}", title="Support replied", body=f"The loan team replied to: {r[1]}. "
                     "Open Customer support to read the conversation.", ts=r[2], tone="info") for r in rows]
    finally:
        conn.close()
