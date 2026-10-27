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
_OK_NAME = re.compile(r"^(db/audit_log\.db|users\.json|(models|uploads|documents)/[A-Za-z0-9._-]+|manifest\.json)$")


def _key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=KDF_ITERATIONS)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def _dirs() -> dict[str, Path]:
    return {"models": registry.model_dir(), "uploads": policy_store.UPLOAD_DIR, "documents": documents.DOC_DIR}


def _check_pass(passphrase: str) -> None:
    if len(passphrase) < MIN_PASSPHRASE:
        raise ValueError(f"Use a passphrase of at least {MIN_PASSPHRASE} characters.")


def create(passphrase: str, actor: str = "system", role: str = "admin") -> bytes:
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
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 17:
        raise ValueError("This is not a Credit Desk backup file.")
    salt = blob[len(MAGIC):len(MAGIC) + 16]
    try:
        raw = Fernet(_key(passphrase, salt)).decrypt(blob[len(MAGIC) + 16:])
    except InvalidToken:
        raise ValueError("Wrong passphrase, or the backup file is damaged.") from None
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        for n in names:
            if not _OK_NAME.match(n) or ".." in n:
                raise ValueError(f"Unsafe or unexpected file in backup: {n!r}")
        manifest = json.loads(z.read("manifest.json"))
        files = {n: z.read(n) for n in names if n != "manifest.json"}
    for n, h in manifest["files"].items():
        if n not in files or hashlib.sha256(files[n]).hexdigest() != h:
            raise ValueError(f"Integrity check failed for {n}; the backup was altered or damaged.")
    if set(files) != set(manifest["files"]):
        raise ValueError("The backup contains files that are not listed in its manifest.")
    return manifest, files


def inspect(blob: bytes, passphrase: str) -> dict:
    """Verify a backup without changing anything. Returns its manifest summary."""
    m, files = _open(blob, passphrase)
    return {"created_utc": m["created_utc"], "files": len(files), "has_database": "db/audit_log.db" in files,
            "has_users": "users.json" in files}


def restore(blob: bytes, passphrase: str, actor: str = "system", role: str = "admin") -> dict:
    manifest, files = _open(blob, passphrase)                      # nothing is touched until this passes
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safety_dir = audit.DB_PATH.parent / "backups"
    safety_dir.mkdir(parents=True, exist_ok=True)
    safety = safety_dir / f"pre_restore_{stamp}.cdbk"
    safety.write_bytes(create(passphrase, actor, role))
    os.chmod(safety, 0o600)

    if "db/audit_log.db" in files:
        tmp = audit.DB_PATH.with_suffix(".restoring")
        tmp.write_bytes(files["db/audit_log.db"])
        for ext in ("-wal", "-shm"):
            Path(str(audit.DB_PATH) + ext).unlink(missing_ok=True)
        os.replace(tmp, audit.DB_PATH)
    if "users.json" in files:
        auth.USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        auth.USERS_FILE.write_bytes(files["users.json"])
        os.chmod(auth.USERS_FILE, 0o600)
    for prefix, d in _dirs().items():
        wanted = {n.split("/", 1)[1]: b for n, b in files.items() if n.startswith(prefix + "/")}
        if d.exists():
            shutil.rmtree(d)
        if wanted:
            d.mkdir(parents=True, exist_ok=True)
            os.chmod(d, 0o700)
            for name, data in wanted.items():
                (d / name).write_bytes(data)
                os.chmod(d / name, 0o600)
    audit.log_event(actor, role, "backup_restored", f"backup of {manifest['created_utc']} - {len(files)} files "
                    f"- previous state saved as {safety.name}", strict=False)
    return {"restored_files": len(files), "created_utc": manifest["created_utc"], "safety_copy": str(safety)}
