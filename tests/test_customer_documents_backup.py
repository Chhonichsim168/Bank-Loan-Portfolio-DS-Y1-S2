import io
import sqlite3
from datetime import timedelta

import pandas as pd
import pytest
from PIL import Image

from src import audit, auth, backup, customer_documents as docs, customer_portal as portal
from src import customer_search, customer_support as support, documents
from src.data_pipeline import today_local


@pytest.fixture
def actors(sandbox, monkeypatch):
    actor = [auth.User("alice", "Alice", "customer")]
    monkeypatch.setattr(auth, "current_user", lambda: actor[0])
    auth._write_users({
        "admin": auth._new_record("Administrator", "admin", "ExampleAdmin!2026", False),
        "alice": auth._new_record("Alice", "customer", "ExampleCustomer!2026", False),
    })
    portal.save_profile("Alice", "012345678", "", "Phnom Penh")
    return actor


def scan(color="teal"):
    out = io.BytesIO()
    Image.new("RGB", (200, 150), color).save(out, format="PNG")
    return out.getvalue()


def test_document_owner_employee_review_and_validation(actors):
    rid = portal.submit_request(1000, 12, "Personal", "Education")
    content = scan()
    did = docs.attach(rid, content, "income.png", "Income proof")
    assert docs.download(rid, did)[0] == content
    assert docs.for_request(rid).iloc[0].status == "Awaiting review"
    for name, data in [("fake.png", b"not an image"), ("bad.exe", content), ("bad.pdf", b"%PDF-1.4 incomplete")]:
        with pytest.raises(ValueError):
            docs.attach(rid, data, name, "Identity")
    actors[0] = auth.User("bob", "Bob", "customer")
    with pytest.raises(PermissionError):
        docs.for_request(rid)
    with pytest.raises(PermissionError):
        docs.download(rid, did)
    with pytest.raises(PermissionError):
        docs.attach(rid, content, "scan.png", "Identity")
    actors[0] = auth.User("employee", "Employee", "officer")
    assert docs.download(rid, did)[0] == content
    with pytest.raises(ValueError):
        docs.review(rid, did, "Needs replacement", "")
    docs.review(rid, did, "Needs replacement", "Please upload a clearer scan.")
    docs.review(rid, did, "Accepted", "Clear scan checked.")
    actors[0] = auth.User("alice", "Alice", "customer")
    assert docs.for_request(rid).iloc[0].status == "Accepted"
    assert len(docs.review_notifications()) == 2
    portal.cancel_request(rid)
    with pytest.raises(ValueError):
        docs.attach(rid, content, "late.png", "Identity")
    assert docs.download(rid, did)[0] == content


def test_backup_roundtrip_preserves_customer_data_and_files(actors, sandbox):
    portal.save_profile("Alice", "012345678", "", "Phnom Penh", photo=scan())
    original_photo = portal.profile_photo()
    rid = portal.submit_request(1000, 12, "Personal", "Education")
    did = docs.attach(rid, scan(), "income.png", "Income proof")
    original_doc = docs.download(rid, did)[0]
    tid = support.create_ticket("Payment question", "How do I obtain a receipt?")
    actors[0] = auth.User("admin", "Administrator", "admin")
    docs.review(rid, did, "Accepted", "Verified")
    support.reply(tid, "Download the receipt from your payment history.")
    portal.review(rid, "Approved", "Verified", 1000, .12, 12)
    today = today_local().date()
    lid = portal.issue_loan(rid, today, today + timedelta(days=30))
    from src import loanbook, policy_store, registry
    loanbook.add_event(lid, username="admin", role="admin", kind="payment", event_date=today, amount=50)
    for folder in (registry.model_dir(), policy_store.UPLOAD_DIR):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "example.json").write_text("original")
    blob = backup.create("BackupExample!2026", "admin", "admin")
    info = backup.inspect(blob, "BackupExample!2026")
    assert info["records"]["photos"] == 1 and info["records"]["payments"] == 1
    actors[0] = auth.User("alice", "Alice", "customer")
    portal.save_profile("Changed name", "099999999", "", "Changed address", photo=scan("blue"))
    support.reply(tid, "A newer message to remove on restore")
    with pytest.raises(PermissionError):
        backup.create("BackupExample!2026", "alice", "customer")
    with pytest.raises(PermissionError):
        backup.restore(blob, "BackupExample!2026")
    actors[0] = auth.User("admin", "Administrator", "admin")
    for folder in (registry.model_dir(), policy_store.UPLOAD_DIR):
        (folder / "example.json").write_text("changed")
    result = backup.restore(blob, "BackupExample!2026", "admin", "admin")
    assert "safety_copy" in result
    for folder in (registry.model_dir(), policy_store.UPLOAD_DIR):
        assert (folder / "example.json").read_text() == "original"
    actors[0] = auth.User("alice", "Alice", "customer")
    assert portal.profile()["full_name"] == "Alice"
    assert portal.profile_photo() == original_photo
    assert docs.download(rid, did)[0] == original_doc
    assert docs.for_request(rid).iloc[0].status == "Accepted"
    assert len(support.messages(tid)) == 2
    assert portal.loan_details(lid)[1]["paid"] == 50
    assert auth._read_users()["alice"]["role"] == "customer"
    assert audit.verify_chain()[0]


def test_invalid_backup_does_not_change_data(actors):
    actors[0] = auth.User("admin", "Administrator", "admin")
    blob = backup.create("BackupExample!2026", "admin", "admin")
    before_users = auth.USERS_FILE.read_bytes()
    before_events = audit.fetch_events(100)
    with pytest.raises(ValueError):
        backup.restore(blob, "IncorrectPassword", "admin", "admin")
    with pytest.raises(ValueError):
        backup.restore(b"corrupt file", "BackupExample!2026", "admin", "admin")
    assert auth.USERS_FILE.read_bytes() == before_users
    assert audit.fetch_events(100).equals(before_events)


def test_search_is_literal_and_dates_are_inclusive():
    from datetime import date
    df = pd.DataFrame({"reference":["LN-[1]", "LN-2", "LN-3"], "status":["Active", "Closed", "Active"],
                       "date":["2026-07-30", "2026-08-30", "2026-09-30"]})
    assert customer_search.filter_records(df, "[1]", ("reference",)).reference.tolist() == ["LN-[1]"]
    assert len(customer_search.filter_records(df, "ln", ("reference",), "Active")) == 2
    assert len(customer_search.filter_records(df, date_column="date", dates=(date(2026,8,30),date(2026,9,30)))) == 2
    assert customer_search.filter_records(df, "missing", ("reference",)).empty


def test_backup_audit_validation_runs_before_restore(actors, sandbox):
    import hashlib, json, os, zipfile
    actors[0] = auth.User("admin", "Administrator", "admin")
    blob = backup.create("BackupExample!2026", "admin", "admin")
    manifest, files = backup._open(blob, "BackupExample!2026")
    changed = sandbox / "altered.db"
    changed.write_bytes(files["db/audit_log.db"])
    conn = sqlite3.connect(changed)
    conn.execute("DROP TRIGGER events_no_update")
    conn.execute("UPDATE events SET detail='altered history' WHERE id=(SELECT MIN(id) FROM events)")
    conn.commit()
    conn.close()
    files["db/audit_log.db"] = changed.read_bytes()
    manifest["files"] = {name: hashlib.sha256(data).hexdigest() for name,data in files.items()}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest))
        for name,data in files.items():
            z.writestr(name, data)
    salt = os.urandom(16)
    forged = backup.MAGIC + salt + backup.Fernet(backup._key("BackupExample!2026", salt)).encrypt(archive.getvalue())
    before = audit.fetch_events(100)
    with pytest.raises(ValueError, match="audit history"):
        backup.restore(forged, "BackupExample!2026", "admin", "admin")
    assert audit.fetch_events(100).equals(before)


def test_failed_restore_rolls_back_directory_changes(actors, sandbox, monkeypatch):
    from pathlib import Path
    from src import registry, policy_store
    actors[0] = auth.User("admin", "Administrator", "admin")
    for folder in (registry.model_dir(), policy_store.UPLOAD_DIR, documents.DOC_DIR):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "example.json").write_text("backup version")
    blob = backup.create("BackupExample!2026", "admin", "admin")
    for folder in (registry.model_dir(), policy_store.UPLOAD_DIR, documents.DOC_DIR):
        (folder / "example.json").write_text("current version")
    original_rename = Path.rename
    failed = [False]
    def disk_failure(path, target):
        if '.incoming-' in path.name and path.name.startswith('uploads') and not failed[0]:
            failed[0] = True
            raise OSError("Simulated disk failure")
        return original_rename(path, target)
    monkeypatch.setattr(Path, "rename", disk_failure)
    with pytest.raises(OSError, match="Simulated"):
        backup.restore(blob, "BackupExample!2026", "admin", "admin")
    for folder in (registry.model_dir(), policy_store.UPLOAD_DIR, documents.DOC_DIR):
        assert (folder / "example.json").read_text() == "current version"
    assert audit.verify_chain()[0]
