"""Per-account action undo with conflict checks and an audit trail."""
import base64
import json
from src import auth, audit

SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_undo_actions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, kind TEXT NOT NULL,
 label TEXT NOT NULL, reference TEXT NOT NULL DEFAULT '', before_state TEXT NOT NULL,
 after_state TEXT NOT NULL, created_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'active', undone_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS undo_account ON customer_undo_actions(username,state,id);
"""


def _pack(value):
    if isinstance(value,bytes):
        return {"__bytes__":base64.b64encode(value).decode("ascii")}
    raise TypeError("Unsupported undo value")


def _unpack(value):
    return base64.b64decode(value["__bytes__"]) if set(value)=={"__bytes__"} else value


def record(conn,username,kind,label,before,after,reference=""):
    if before==after:
        return
    conn.execute("INSERT INTO customer_undo_actions (username,kind,label,reference,before_state,after_state,created_at) VALUES (?,?,?,?,?,?,?)",
        (username,kind,label,str(reference),json.dumps(before,default=_pack),json.dumps(after,default=_pack),audit._now()))


def profile_state(conn,username):
    row=conn.execute("SELECT * FROM customer_profiles WHERE username=?",(username,)).fetchone()
    photo=conn.execute("SELECT * FROM customer_photos WHERE username=?",(username,)).fetchone()
    return {"profile":list(row) if row else None,"photo":list(photo) if photo else None}


def draft_state(conn,username):
    row=conn.execute("SELECT * FROM customer_application_drafts WHERE username=?",(username,)).fetchone()
    return list(row) if row else None


def latest():
    from src import customer_portal as portal
    user=portal.require_role("customer",*portal.STAFF)
    conn=portal.connect()
    try:
        row=conn.execute("SELECT id,label FROM customer_undo_actions WHERE username=? AND state='active' ORDER BY id DESC LIMIT 1",(user.username,)).fetchone()
        return {"id":row[0],"label":row[1]} if row else None
    finally:
        conn.close()


def _restore_draft(conn,username,previous):
    conn.execute("DELETE FROM customer_application_drafts WHERE username=?",(username,))
    if previous:
        conn.execute("INSERT INTO customer_application_drafts VALUES (?,?,?)",previous)


def undo(expected_id):
    from src import customer_portal as portal
    user=portal.require_role("customer",*portal.STAFF)
    with portal.transaction("customer_action_undo",str(expected_id)) as conn:
        cur=conn.execute("SELECT * FROM customer_undo_actions WHERE username=? AND state='active' ORDER BY id DESC LIMIT 1",(user.username,))
        row=cur.fetchone()
        if not row or row[0]!=expected_id:
            raise ValueError("The latest action changed. Please try Undo again.")
        action=dict(zip([col[0] for col in cur.description],row))
        before=json.loads(action["before_state"],object_hook=_unpack)
        after=json.loads(action["after_state"],object_hook=_unpack)
        kind,ref=action["kind"],action["reference"]
        conflict=False
        if kind=="profile":
            if profile_state(conn,user.username)!=after:
                conflict=True
            else:
                conn.execute("DELETE FROM customer_profiles WHERE username=?",(user.username,))
                conn.execute("DELETE FROM customer_photos WHERE username=?",(user.username,))
                if before["profile"]:
                    conn.execute("INSERT INTO customer_profiles VALUES (?,?,?,?,?,?)",before["profile"])
                if before["photo"]:
                    conn.execute("INSERT INTO customer_photos VALUES (?,?,?)",before["photo"])
        elif kind=="draft":
            if draft_state(conn,user.username)!=after:
                conflict=True
            else:
                _restore_draft(conn,user.username,before)
        elif kind in {"request_submit","request_cancel"}:
            request=conn.execute("SELECT status FROM customer_requests WHERE request_id=? AND username=?",(ref,user.username)).fetchone()
            linked=conn.execute("SELECT 1 FROM customer_loan_links WHERE request_id=?",(ref,)).fetchone()
            cancelled=conn.execute("SELECT cancelled_at FROM customer_request_cancellations WHERE request_id=?",(ref,)).fetchone()
            conflict=not request or request[0]!="Pending review" or bool(linked)
            if kind=="request_submit":
                conflict=conflict or bool(cancelled)
                if not conflict:
                    conn.execute("INSERT INTO customer_request_cancellations VALUES (?,?)",(ref,audit._now()))
                    if draft_state(conn,user.username) is None:
                        _restore_draft(conn,user.username,before)
            else:
                conflict=conflict or not cancelled or cancelled[0]!=after
                if not conflict:
                    conn.execute("DELETE FROM customer_request_cancellations WHERE request_id=?",(ref,))
        elif kind=="document":
            document=conn.execute("SELECT case_id,username FROM case_documents WHERE id=?",(ref,)).fetchone()
            request=conn.execute("SELECT status FROM customer_requests WHERE request_id=? AND username=?",(after["request"],user.username)).fetchone()
            reviewed=conn.execute("SELECT 1 FROM customer_document_reviews WHERE document_id=?",(ref,)).fetchone()
            withdrawn=conn.execute("SELECT 1 FROM customer_document_withdrawals WHERE document_id=?",(ref,)).fetchone()
            conflict=(not document or document[1]!=user.username or document[0]!="customer-request:"+after["request"]
                      or not request or request[0]!="Pending review" or bool(reviewed) or bool(withdrawn))
            if not conflict:
                conn.execute("INSERT INTO customer_document_withdrawals VALUES (?,?,?)",(ref,user.username,audit._now()))
        elif kind=="message":
            message=conn.execute("SELECT ticket_id,sender FROM customer_support_messages WHERE id=?",(ref,)).fetchone()
            withdrawn=conn.execute("SELECT 1 FROM support_message_withdrawals WHERE message_id=?",(ref,)).fetchone()
            conflict=not message or message[1]!=user.username or bool(withdrawn)
            if not conflict:
                conn.execute("INSERT INTO support_message_withdrawals VALUES (?,?,?)",(ref,user.username,audit._now()))
                first=conn.execute("SELECT MIN(id) FROM customer_support_messages WHERE ticket_id=?",(message[0],)).fetchone()[0]
                if first==int(ref):
                    conn.execute("UPDATE customer_support_tickets SET subject='Support conversation' WHERE ticket_id=?",(message[0],))
        else:
            conflict=True
        conn.execute("UPDATE customer_undo_actions SET state=?,undone_at=? WHERE id=? AND username=?",
            ("blocked" if conflict else "undone",audit._now(),expected_id,user.username))
        return {"ok":not conflict,"kind":kind,"label":action["label"]}
