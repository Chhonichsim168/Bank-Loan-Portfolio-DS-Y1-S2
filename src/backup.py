"""
backup.py
=========
Credit Desk - encrypted backup and restore of everything the app stores on this computer.

A backup contains: the database (audit log, policy versions, saved decisions, loan book, document
index), the user file, registered models, uploaded data extracts and attached documents. It is one
file, encrypted with a passphrase you choose (Fernet = AES-128-CBC + HMAC-SHA256, key derived with
PBKDF2-SHA256, 480,000 iterations). **Lose the passphrase and the backup cannot be opened - there is
no recovery.** Store backups on a different drive from the app.

Restore checks the passphrase, every file's SHA-256 against the manifest and every path inside the
archive (no ``..``, no absolute paths) before it touches anything, and first saves the current state
as ``pre_restore_<time>.cdbk`` next to the app data.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from src import audit, auth, documents, policy_store, registry

MAGIC = b"CDBK1"
KDF_ITERATIONS = 480_000
MIN_PASSPHRASE = 12
MAX_BACKUP_BYTES = 250 * 1024 * 1024
_OK_NAME = re.compile(r"^(db/audit_log\.db|users\.json|(models|uploads|documents)/[A-Za-z0-9._-]+|manifest\.json)$")


def _key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=KDF_ITERATIONS)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def _dirs() -> dict[str, Path]:
    return {"models": registry.model_dir(), "uploads": policy_store.UPLOAD_DIR, "documents": documents.DOC_DIR}


def _check_pass(passphrase: str) -> None:
    if len(passphrase) < MIN_PASSPHRASE:
        raise ValueError(f"Use a passphrase of at least {MIN_PASSPHRASE} characters.")


def _require_admin(role="admin"):
    current = auth.current_user()
    if role != "admin" or (current is not None and current.role != "admin"):
        raise PermissionError("Only an Administrator can create, inspect or restore backups.")


def _verify_database(data, files=None):
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "verify.db"
        path.write_bytes(data)
        try:
            conn = sqlite3.connect(path)
            try:
                conn.execute("PRAGMA query_only=ON")
                if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("The backup database is damaged. No data has been changed.")
                if conn.execute("PRAGMA foreign_key_check").fetchone():
                    raise ValueError("The backup contains broken record links. No data has been changed.")
                previous = audit.GENESIS
                for row in conn.execute("SELECT ts,username,role,action,detail,prev_hash,hash FROM events ORDER BY id"):
                    ts, user, role, action, detail, prev, digest = row
                    if prev != previous or digest != audit._digest(prev, ts, user, role, action, detail):
                        raise ValueError("The backup audit history could not be verified. No data has been changed.")
                    previous = digest
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if files is not None and "case_documents" in tables:
                    for stored, digest in conn.execute("SELECT stored,sha256 FROM case_documents"):
                        if not isinstance(stored, str) or Path(stored).name != stored:
                            raise ValueError("A document in the backup has an invalid storage path.")
                        name = "documents/" + stored
                        if name not in files or hashlib.sha256(files[name]).hexdigest() != digest:
                            raise ValueError("A supporting document is missing or damaged in this backup.")
                counts = {}
                for label, table in {"profiles":"customer_profiles", "photos":"customer_photos", "loans":"loans",
                                     "requests":"customer_requests", "support_messages":"customer_support_messages",
                                     "documents":"case_documents"}.items():
                    counts[label] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] if table in tables else 0
                counts["payments"] = conn.execute("SELECT COUNT(*) FROM loan_events WHERE kind IN ('payment','settle')").fetchone()[0] if "loan_events" in tables else 0
                return counts
            finally:
                conn.close()
        except sqlite3.DatabaseError as exc:
            raise ValueError("This backup does not contain a valid Credit Desk database. No data has been changed.") from exc


def _restore_dirs():
    targets = {name: path.resolve() for name, path in _dirs().items()}
    protected = {audit.DB_PATH.parent.resolve(), auth.USERS_FILE.parent.resolve(),
                 (audit.DB_PATH.parent / 'backups').resolve()}
    for name, target in targets.items():
        original = _dirs()[name]
        if original.is_symlink() or (hasattr(original, "is_junction") and original.is_junction()):
            raise ValueError("Restore folders must be normal folders, not links.")
        if target.parent == target or target in protected or target in audit.DB_PATH.resolve().parents or target in auth.USERS_FILE.resolve().parents:
            raise ValueError("A restore folder points outside its intended data directory.")
    paths = list(targets.values())
    if any(a == b or a in b.parents or b in a.parents for i,a in enumerate(paths) for b in paths[i+1:]):
        raise ValueError("Restore folders overlap. Correct the data-folder settings first.")
    return targets


def create(passphrase: str, actor: str = "system", role: str = "admin") -> bytes:
    _require_admin(role)
    _check_pass(passphrase)
    files: dict[str, bytes] = {}
    if audit.DB_PATH.exists():
        with tempfile.TemporaryDirectory() as td:
            snap = Path(td) / "snap.db"
            src, dst = sqlite3.connect(audit.DB_PATH), sqlite3.connect(snap)
            try:
                src.backup(dst)                      # consistent copy even while the app is writing
            finally:
                dst.close(); src.close()
            files["db/audit_log.db"] = snap.read_bytes()
    if auth.USERS_FILE.exists():
        files["users.json"] = auth.USERS_FILE.read_bytes()
    for prefix, d in _dirs().items():
        if d.exists():
            for f in sorted(d.iterdir()):
                if f.is_file() and re.fullmatch(r"[A-Za-z0-9._-]+", f.name):
                    files[f"{prefix}/{f.name}"] = f.read_bytes()
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "format": 1,
                "files": {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=1))
        for n, b in files.items():
            z.writestr(n, b)
    salt = os.urandom(16)
    blob = MAGIC + salt + Fernet(_key(passphrase, salt)).encrypt(buf.getvalue())
    audit.log_event(actor, role, "backup_created", f"{len(files)} files, {len(blob):,} bytes", strict=False)
    return blob


def _open(blob: bytes, passphrase: str) -> tuple[dict, dict[str, bytes]]:
    if len(blob) > MAX_BACKUP_BYTES:
        raise ValueError("This backup is larger than the supported 250 MB limit.")
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 17:
        raise ValueError("This is not a Credit Desk backup file.")
    salt = blob[len(MAGIC):len(MAGIC) + 16]
    try:
        raw = Fernet(_key(passphrase, salt)).decrypt(blob[len(MAGIC) + 16:])
    except InvalidToken:
        raise ValueError("Wrong passphrase, or the backup file is damaged.") from None
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ValueError("The backup archive is damaged. Choose a different backup.") from exc
    with archive as z:
        names = z.namelist()
        if len(names) != len(set(names)) or len(names) > 10000:
            raise ValueError("The backup contains duplicate or too many files.")
        if sum(i.file_size for i in z.infolist()) > 1024 * 1024 * 1024:
            raise ValueError("The expanded backup is larger than the supported 1 GB limit.")
        for n in names:
            if not _OK_NAME.fullmatch(n) or ".." in n:
                raise ValueError(f"Unsafe or unexpected file in backup: {n!r}")
        try:
            manifest = json.loads(z.read("manifest.json"))
        except (KeyError, ValueError) as exc:
            raise ValueError("The backup manifest is missing or damaged.") from exc
        if manifest.get("format") != 1 or not isinstance(manifest.get("files"), dict) or not manifest.get("created_utc"):
            raise ValueError("This backup format is not supported.")
        files = {n: z.read(n) for n in names if n != "manifest.json"}
    for n, h in manifest["files"].items():
        if n not in files or hashlib.sha256(files[n]).hexdigest() != h:
            raise ValueError(f"Integrity check failed for {n}; the backup was altered or damaged.")
    if set(files) != set(manifest["files"]):
        raise ValueError("The backup contains files that are not listed in its manifest.")
    if "db/audit_log.db" in files:
        _verify_database(files["db/audit_log.db"], files)
    if "users.json" in files:
        try:
            users = json.loads(files["users.json"])
            if not isinstance(users, dict) or any(not isinstance(u, dict) or u.get("role") not in auth.ROLE_LABELS or not u.get("hash") or not u.get("salt") for u in users.values()):
                raise ValueError("Invalid accounts")
        except (ValueError, TypeError) as exc:
            raise ValueError("The backup account file is damaged.") from exc
    return manifest, files


def inspect(blob: bytes, passphrase: str) -> dict:
    """Verify a backup without changing anything. Returns its manifest summary."""
    _require_admin()
    m, files = _open(blob, passphrase)
    return {"created_utc": m["created_utc"], "files": len(files), "has_database": "db/audit_log.db" in files,
            "has_users": "users.json" in files,
            "records": _verify_database(files["db/audit_log.db"]) if "db/audit_log.db" in files else {}}


def restore(blob: bytes, passphrase: str, actor: str = "system", role: str = "admin") -> dict:
    _require_admin(role)
    manifest, files = _open(blob, passphrase)                      # nothing is touched until this passes
    targets = _restore_dirs()
    if "db/audit_log.db" not in files or "users.json" not in files:
        raise ValueError("Restoring requires a complete backup containing the database and accounts.")
    users = json.loads(files["users.json"])
    if not any(u["role"] == "admin" and not u.get("disabled") for u in users.values()):
        raise ValueError("The backup has no active Administrator. Restore was refused to prevent losing access.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    safety_dir = audit.DB_PATH.parent / "backups"
    safety_dir.mkdir(parents=True, exist_ok=True)
    safety = safety_dir / f"pre_restore_{stamp}.cdbk"
    safety.write_bytes(create(passphrase, actor, role))
    os.chmod(safety, 0o600)

    # Stage every file before replacing current state. Directory moves stay in
    # each configured target's parent, and SQLite performs the database swap.
    incoming, previous, swapped = {}, {}, []
    old_users = auth.USERS_FILE.read_bytes() if auth.USERS_FILE.exists() else None
    def remove_checked(path, target):
        resolved = path.resolve()
        allowed_names = {target.name, target.name + '.incoming-' + stamp, target.name + '.previous-' + stamp}
        if resolved.parent != target.parent.resolve() or resolved.name not in allowed_names:
            raise ValueError("Refusing to remove an unexpected restore folder.")
        if path.exists():
            shutil.rmtree(path)
    def copy_database(source, destination):
        src, dst = sqlite3.connect(source), sqlite3.connect(destination)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    with tempfile.TemporaryDirectory(prefix='.restore-', dir=audit.DB_PATH.parent) as td:
        stage = Path(td)
        source_db, old_db = stage / 'incoming.db', stage / 'previous.db'
        source_db.write_bytes(files['db/audit_log.db'])
        had_db = audit.DB_PATH.exists()
        if had_db:
            copy_database(audit.DB_PATH, old_db)
        database_started = False
        try:
            for prefix, target in targets.items():
                target.parent.mkdir(parents=True, exist_ok=True)
                folder = target.with_name(target.name + '.incoming-' + stamp)
                folder.mkdir()
                incoming[prefix] = folder
                for name, data in files.items():
                    if name.startswith(prefix + '/'):
                        destination = folder / name.split('/', 1)[1]
                        destination.write_bytes(data)
                        os.chmod(destination, 0o600)
                os.chmod(folder, 0o700)
            for prefix, target in targets.items():
                previous[prefix] = target.with_name(target.name + '.previous-' + stamp)
                if target.exists():
                    target.rename(previous[prefix])
                swapped.append(prefix)
                incoming[prefix].rename(target)
            with auth._file_lock():
                auth._write_users(users)
            database_started = True
            copy_database(source_db, audit.DB_PATH)
        except Exception as original:
            rollback_errors = []
            try:
                if database_started and had_db:
                    copy_database(old_db, audit.DB_PATH)
            except Exception as exc:
                rollback_errors.append(exc)
            try:
                if old_users is not None:
                    with auth._file_lock():
                        auth._write_users(json.loads(old_users))
                elif auth.USERS_FILE.exists():
                    auth.USERS_FILE.unlink()
            except Exception as exc:
                rollback_errors.append(exc)
            for prefix in reversed(swapped):
                try:
                    target = targets[prefix]
                    remove_checked(target, target)
                    if previous[prefix].exists():
                        previous[prefix].rename(target)
                except Exception as exc:
                    rollback_errors.append(exc)
            if rollback_errors:
                raise RuntimeError(f"Restore could not finish. The previous state is saved in {safety.name}; "
                                   "keep that file and ask the administrator to recover it.") from original
            raise
        finally:
            for prefix, folder in incoming.items():
                remove_checked(folder, targets[prefix])
        for prefix, folder in previous.items():
            remove_checked(folder, targets[prefix])
    audit.log_event(actor, role, "backup_restored", f"backup of {manifest['created_utc']} - {len(files)} files "
                    f"- previous state saved as {safety.name}", strict=False)
    return {"restored_files": len(files), "created_utc": manifest["created_utc"], "safety_copy": str(safety)}
