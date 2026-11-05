"""
auth.py
=======
Credit Desk - authentication, roles, page permissions and user administration.

Dependency-free (stdlib ``hashlib`` / ``hmac``), but a real access-control layer:

* PBKDF2-HMAC-SHA256 at 600,000 iterations (OWASP guidance); older hashes are verified at their
  own iteration count and silently upgraded on the next successful sign-in.
* **No shipped credentials.** On first start, if no user file exists, an Administrator is created
  with a random one-time password written to ``data/first_run_admin.txt`` (mode 0600) and the
  server console; it must be changed at first sign-in. ``README`` documents the procedure.
* **Brute-force protection.** ``MAX_FAILURES`` consecutive failures lock the account for
  ``LOCKOUT_MINUTES``. Every failed, locked and disabled-account attempt is audit-logged.
* **Multi-factor sign-in** (TOTP, RFC 6238, works with any authenticator app). Optional per user;
  mandatory for everyone if ``CREDIT_DESK_REQUIRE_MFA=1``.
* **Idle session timeout** (``CREDIT_DESK_SESSION_MINUTES``, default 20).
* **User administration** (create, change role, disable, reset password / MFA) with a guard
  against removing the last active Administrator. Every action is audit-logged.
* **SSO.** If the bank has Active Directory / OIDC, replace ``authenticate()`` with an
  identity-provider call and keep the rest of this module (roles, timeout, audit) unchanged.

Honest limits: TOTP secrets are stored in the user file (keep it 0600 and off shared storage);
there is no per-IP rate limit because Streamlit does not expose the client address - put the app
behind a reverse proxy (see ``deploy/nginx.conf.example``) for that.
"""

from __future__ import annotations

from src.storage import DATA_DIR

import base64
import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import string
import struct
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

from src import audit

ROOT = Path(__file__).resolve().parent.parent
USERS_FILE = Path(os.environ.get("CREDIT_DESK_USERS_FILE", DATA_DIR / "users.json"))
FIRST_RUN_FILE = DATA_DIR / "first_run_admin.txt"

ROLE_LABELS: dict[str, str] = {
    "admin": "Administrator",
    "risk": "Risk Manager",
    "officer": "Credit Officer",
    "customer": "Customer",
}

# Which roles may see which page slug. A slug with no entry is open to any signed-in user.
PAGE_ACCESS: dict[str, set[str]] = {
    "policy": {"risk", "admin"},
    "model": {"risk", "admin"},
    "data": {"risk", "admin"},
    "users": {"admin"},
    "backups": {"admin"},
}

PBKDF2_ITERATIONS = 600_000
LEGACY_ITERATIONS = 200_000          # records written before the iteration count was stored
MAX_FAILURES = 5
LOCKOUT_MINUTES = 15
MIN_PASSWORD_LENGTH = 12
_COMMON = {"password", "password1", "password123", "123456789012", "qwertyuiop12", "letmein12345",
           "welcome12345", "administrator", "changeme1234", "creditdesk123"}
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,40}$")


# =========================================================================================
# SETTINGS
# =========================================================================================
def session_timeout_minutes() -> int:
    try:
        return max(1, int(os.environ.get("CREDIT_DESK_SESSION_MINUTES", "20")))
    except ValueError:
        return 20


def mfa_required() -> bool:
    return os.environ.get("CREDIT_DESK_REQUIRE_MFA", "").strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class User:
    username: str
    display_name: str
    role: str
    mfa_enabled: bool = False
    must_change: bool = False

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role.title())


# =========================================================================================
# PASSWORDS
# =========================================================================================
def hash_password(password: str, salt: str | None = None, iterations: int | None = None) -> tuple[str, str]:
    """Salted PBKDF2-SHA256. Returns (hash_hex, salt_hex) - store both plus the iteration count."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt),
                                 iterations or PBKDF2_ITERATIONS).hex()
    return digest, salt


SIMPLE_MIN_LENGTH = 4


def validate_password(password: str, username: str = "") -> list[str]:
    from src.mode import strong_passwords
    if not strong_passwords():
        # Simple-password mode (the default): only a short minimum length.
        return [] if len(password) >= SIMPLE_MIN_LENGTH else [f"Use at least {SIMPLE_MIN_LENGTH} characters."]
    errs = []
    if len(password) < MIN_PASSWORD_LENGTH:
        errs.append(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    classes = sum(bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if classes < 3:
        errs.append("Mix at least three of: lower case, upper case, digits, symbols.")
    if username and username.lower() in password.lower():
        errs.append("The password must not contain the username.")
    if password.lower() in _COMMON:
        errs.append("That password is too common.")
    return errs


def generate_temp_password() -> str:
    pools = [string.ascii_lowercase, string.ascii_uppercase, string.digits, "!@#$%^&*-_=+"]
    chars = [secrets.choice(p) for p in pools] + [secrets.choice("".join(pools)) for _ in range(12)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


# =========================================================================================
# USER STORE (JSON file, written atomically under a lock)
# =========================================================================================
@contextlib.contextmanager
def _file_lock():
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_path = USERS_FILE.with_suffix(".lock")
    with open(lock_path, "a+") as fh:
        try:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX)
        except ImportError:        # Windows: single-process use is the supported case
            pass
        try:
            yield
        finally:
            try:
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_UN)
            except ImportError:
                pass


def _read_users() -> dict:
    try:
        return json.loads(USERS_FILE.read_text()) if USERS_FILE.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_users(users: dict) -> None:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=USERS_FILE.parent, prefix=".users-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(users, f, indent=2, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, USERS_FILE)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _new_record(display_name: str, role: str, password: str | None, must_change: bool,
                email: str = "", email_verified: bool = False) -> dict:
    """``password=None`` makes a Google-only account: it has no password and can only sign in
    with Google until the owner chooses a password in My account."""
    digest, salt = hash_password(password) if password else ("", "")
    return {"display_name": display_name, "role": role, "hash": digest, "salt": salt,
            "iterations": PBKDF2_ITERATIONS, "disabled": False, "must_change": must_change,
            "mfa_secret": "", "mfa_last_counter": 0, "failed": 0, "locked_until": "",
            "created_at": _iso(_now()), "password_changed_at": _iso(_now()) if password else "",
            "email": email, "email_verified": bool(email and email_verified), "google": False}


# =========================================================================================
# EMAIL ADDRESSES
# One email per account (unique, stored lower-case). A *verified* email is one whose owner proved
# control of it - with Google, with a code we emailed, or because an Administrator entered it.
# Google sign-in only ever opens an account whose email is verified, so nobody can type someone
# else's address into their own account and later receive that person's Google sign-in.
# =========================================================================================
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(normalize_email(email))) and len(email) <= 254


def mask_email(email: str) -> str:
    """da•••@gmail.com - shown on screen after a code is sent, never the full address."""
    email = normalize_email(email)
    if "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    return f"{local[:2]}{'•' * 3}@{domain}"


def _username_for_email(users: dict, email: str) -> str | None:
    email = normalize_email(email)
    if not email:
        return None
    return next((u for u, r in users.items() if normalize_email(r.get("email", "")) == email), None)


def find_username_by_email(email: str) -> str | None:
    return _username_for_email(_read_users(), email)


def has_password(username: str) -> bool:
    return bool((_read_users().get(username) or {}).get("hash"))


def account_email(username: str) -> dict:
    rec = _read_users().get(username) or {}
    return {"email": rec.get("email", ""), "verified": bool(rec.get("email_verified")),
            "google": bool(rec.get("google")), "password": bool(rec.get("hash"))}


def _claim_email(users: dict, username: str, email: str) -> None:
    """Make sure no OTHER account holds ``email``. An unverified claim by someone else is
    released (they never proved it was theirs); a verified one is a hard conflict."""
    other = _username_for_email(users, email)
    if other and other != username:
        if users[other].get("email_verified"):
            raise ValueError("That email address is already used by another account.")
        users[other]["email"], users[other]["email_verified"] = "", False
        audit.log_event("system", "system", "email_released",
                        f"{other}: unverified address released to its verified owner ({mask_email(email)})",
                        strict=False)


def set_email(username: str, email: str, *, verified: bool = False, actor: str | None = None) -> None:
    """Change (or with '' remove) an account's email. ``verified`` = proven by the caller."""
    email = normalize_email(email)
    if email and not valid_email(email):
        raise ValueError("Enter a valid email address, for example name@gmail.com.")
    with _file_lock():
        users = _read_users()
        rec = users.get(username)
        if rec is None:
            raise ValueError("Unknown user.")
        if not email and not rec.get("hash"):
            raise ValueError("This account signs in with Google only, so it must keep its email. "
                             "Set a password first if you want to remove it.")
        old = normalize_email(rec.get("email", ""))
        if email:
            _claim_email(users, username, email)
        if email != old:
            rec["email"] = email
            rec["email_verified"] = bool(email and verified)
            rec["google"] = False if email != old else rec.get("google", False)
            rec.pop("google_link_until", None)
        elif verified and email:
            rec["email_verified"] = True
        _write_users(users)
    who = actor or username
    audit.log_event(who, _actor_role(who), "email_changed",
                    f"{username}: {mask_email(email) or 'removed'}{' (verified)' if verified and email else ''}")
    cur = current_user()
    if cur and cur.username == username:
        refresh_user()


def admin_emails() -> set[str]:
    """Gmail addresses that become Administrators the first time they sign in with Google
    (CREDIT_DESK_ADMIN_EMAILS, comma separated - set in .streamlit/secrets.toml)."""
    raw = os.environ.get("CREDIT_DESK_ADMIN_EMAILS", "")
    return {normalize_email(e) for e in raw.replace(";", ",").split(",") if valid_email(e)}


def _free_username(users: dict, email: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]", "", normalize_email(email).split("@")[0])[:34] or "user"
    if len(base) < 3:
        base = (base + "user")[:6]
    name, n = base, 2
    while name in users:
        name, n = f"{base}{n}", n + 1
    return name


# ---- one-time email codes (sign-up verification and password reset) ----------------------
EMAIL_CODE_MINUTES = 15
EMAIL_CODE_TRIES = 5
EMAIL_CODE_RESEND_SECONDS = 60


def _code_hash(username: str, purpose: str, code: str) -> str:
    return hashlib.sha256(f"{username}|{purpose}|{code}".encode()).hexdigest()


def issue_email_code(username: str, purpose: str) -> str:
    """A 6-digit single-use code for ``purpose`` ('verify' or 'reset'). Only its hash is stored;
    it expires after 15 minutes and 5 wrong tries. Raises ValueError if asked again too soon."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    with _file_lock():
        users = _read_users()
        rec = users.get(username)
        if not rec or not rec.get("email"):
            raise ValueError("This account has no email address.")
        prev = rec.get("email_code") or {}
        if prev.get("purpose") == purpose and prev.get("sent_at"):
            wait = EMAIL_CODE_RESEND_SECONDS - (_now() - datetime.fromisoformat(prev["sent_at"])).total_seconds()
            if wait > 0:
                raise ValueError(f"Please wait {int(wait) + 1} seconds before asking for another code.")
        rec["email_code"] = {"purpose": purpose, "hash": _code_hash(username, purpose, code),
                             "expires": _iso(_now() + timedelta(minutes=EMAIL_CODE_MINUTES)),
                             "sent_at": _iso(_now()), "tries": 0}
        _write_users(users)
    audit.log_event(username, rec["role"], "email_code_sent", f"{purpose} code to {mask_email(rec['email'])}",
                    strict=False)
    return code


def _consume_email_code(users: dict, username: str, purpose: str, code: str) -> None:
    rec = users.get(username) or {}
    data = rec.get("email_code") or {}
    if data.get("purpose") != purpose or not data.get("hash"):
        raise ValueError("No active code. Ask for a new code.")
    if datetime.fromisoformat(data["expires"]) < _now():
        rec.pop("email_code", None)
        raise ValueError("This code has expired. Ask for a new code.")
    candidate = _code_hash(username, purpose, re.sub(r"\s", "", str(code or "")))
    if not hmac.compare_digest(candidate, data["hash"]):
        data["tries"] = int(data.get("tries", 0)) + 1
        if data["tries"] >= EMAIL_CODE_TRIES:
            rec.pop("email_code", None)
            raise ValueError("Too many wrong codes. Ask for a new code.")
        raise ValueError(f"That code is not correct ({EMAIL_CODE_TRIES - data['tries']} tries left).")
    rec.pop("email_code", None)


def verify_email_with_code(username: str, code: str) -> None:
    with _file_lock():
        users = _read_users()
        try:
            _consume_email_code(users, username, "verify", code)
        finally:
            _write_users(users)
        rec = users[username]
        rec["email_verified"] = True
        _write_users(users)
    audit.log_event(username, rec["role"], "email_verified", f"code sent to {mask_email(rec['email'])}")
    cur = current_user()
    if cur and cur.username == username:
        refresh_user()


def reset_password_with_email_code(email: str, code: str, new_password: str) -> str:
    """Forgot password by email. Returns the username. Proving the code also verifies the email."""
    username = find_username_by_email(email)
    if not username:
        raise ValueError("That code is not correct.")
    errs = validate_password(new_password, username)
    if errs:
        raise ValueError(" ".join(errs))
    with _file_lock():
        users = _read_users()
        try:
            _consume_email_code(users, username, "reset", code)
        finally:
            _write_users(users)
        rec = users[username]
        if rec.get("disabled"):
            raise ValueError("This account is disabled. Contact an Administrator.")
        rec["hash"], rec["salt"] = hash_password(new_password)
        rec["iterations"] = PBKDF2_ITERATIONS
        rec["password_changed_at"] = _iso(_now())
        rec["must_change"] = False
        rec["failed"], rec["locked_until"] = 0, ""
        rec["email_verified"] = True
        rec["session_version"] = int(rec.get("session_version", 0)) + 1
        _write_users(users)
    audit.log_event(username, rec["role"], "password_recovered", "Email code; MFA preserved")
    return username


# ---- Google ------------------------------------------------------------------------------
GOOGLE_LINK_MINUTES = 10


def start_google_link(username: str) -> None:
    """Signed-in user pressed 'Verify with Google': for the next 10 minutes a Google sign-in with
    this account's (unverified) email proves the address and links Google to the account."""
    with _file_lock():
        users = _read_users()
        rec = users.get(username)
        if not rec or not rec.get("email"):
            raise ValueError("Add your email address first.")
        rec["google_link_until"] = _iso(_now() + timedelta(minutes=GOOGLE_LINK_MINUTES))
        _write_users(users)


def google_sign_in(email: str, name: str = "", email_verified: bool = True) -> AuthResult:
    """Map a Google identity to a Credit Desk account, creating one on first use.

    * an account with this VERIFIED email -> that account (Google is now linked to it)
    * an account that just pressed 'Verify with Google' for this email -> verified and linked
    * otherwise a new account: Administrator if the email is in CREDIT_DESK_ADMIN_EMAILS, else
      Customer (the same role as the self-service Create account form). An Administrator can
      change the role in User management.
    """
    email = normalize_email(email)
    if not email_verified or not valid_email(email):
        return AuthResult("bad", message="Google did not confirm this email address. Use another Google account.")
    created = linked = None
    with _file_lock():
        users = _read_users()
        username = _username_for_email(users, email)
        rec = users.get(username) if username else None
        if rec is not None and not rec.get("email_verified"):
            until = rec.get("google_link_until") or ""
            if until and datetime.fromisoformat(until) > _now():
                rec["email_verified"], linked = True, username
                rec.pop("google_link_until", None)
            else:
                _claim_email(users, "", email)       # releases the unproven claim
                rec = None
        if rec is None:
            role = "admin" if email in admin_emails() else "customer"
            username = _free_username(users, email)
            rec = _new_record((name or email.split("@")[0]).strip()[:120], role, None, False,
                              email=email, email_verified=True)
            users[username] = rec
            created = role
        if rec.get("disabled"):
            _write_users(users)
            audit.log_event(username, rec["role"], "login_blocked", "account disabled (Google)", strict=False)
            return AuthResult("disabled", message="This account is disabled. Contact an Administrator.")
        rec["google"] = True
        rec["must_change"] = False       # Google proved who this is - no one-time password step needed
        rec["failed"], rec["locked_until"] = 0, ""
        rec["last_login"] = _iso(_now())
        _write_users(users)
        user = _public(username, rec)
    if created:
        audit.log_event("google-sign-in", "system", "user_created",
                        f"{username} as {created} ({mask_email(email)}, Google)")
    if linked:
        audit.log_event(username, rec["role"], "email_verified", "Google sign-in proved the address")
    return AuthResult("mfa" if user.mfa_enabled else "ok", user)


# Trial accounts: created ONLY when CREDIT_DESK_DEMO_USERS=1 (the launcher scripts set it) and no user
# file exists yet. Deliberately weak and publicly documented - never use in a real deployment.
DEMO_USERS = {
    "admin": ("Administrator", "admin", "admin123"),
    "risk": ("Risk Manager", "risk", "risk123"),
    "officer": ("Credit Officer", "officer", "officer123"),
}


def demo_mode() -> bool:
    from src.mode import simple_accounts
    return simple_accounts()


def ensure_bootstrap() -> None:
    """First start only: create one Administrator with a random one-time password. Nothing is
    shipped in the repository, so there is no default credential to find."""
    with _file_lock():
        if _read_users():
            return
        if demo_mode():
            _write_users({u: _new_record(name, role, pw, must_change=False)
                          for u, (name, role, pw) in DEMO_USERS.items()})
            audit.log_event("system", "system", "bootstrap_demo_users",
                            "Trial accounts created (CREDIT_DESK_DEMO_USERS=1)", strict=False)
            return
        pw = os.environ.get("CREDIT_DESK_ADMIN_PASSWORD") or generate_temp_password()
        _write_users({"admin": _new_record("Administrator", "admin", pw, must_change=True)})
    if not os.environ.get("CREDIT_DESK_ADMIN_PASSWORD"):
        FIRST_RUN_FILE.write_text(
            "Credit Desk first-run administrator\n"
            f"username: admin\none-time password: {pw}\n"
            "You must change it at first sign-in. Delete this file afterwards.\n")
        os.chmod(FIRST_RUN_FILE, 0o600)
        print(f"[credit-desk] First run: administrator 'admin' created. One-time password is in "
              f"{FIRST_RUN_FILE}", file=sys.stderr)
    audit.log_event("system", "system", "bootstrap_admin", "First-run administrator created", strict=False)


def _public(username: str, rec: dict) -> User:
    return User(username=username, display_name=rec["display_name"], role=rec["role"],
                mfa_enabled=bool(rec.get("mfa_secret")), must_change=bool(rec.get("must_change")))


def sign_in_methods(rec: dict) -> str:
    google = rec.get("google") or (not rec.get("hash") and rec.get("email_verified"))
    methods = (["Google"] if google else []) + (["Password"] if rec.get("hash") else [])
    return " + ".join(methods) or "-"


def list_users() -> list[dict]:
    return [{"username": u, "display_name": r["display_name"], "role": r["role"],
             "email": r.get("email", ""), "email_verified": bool(r.get("email_verified")),
             "sign_in": sign_in_methods(r),
             "disabled": bool(r.get("disabled")), "must_change": bool(r.get("must_change")),
             "mfa": bool(r.get("mfa_secret")), "created_at": r.get("created_at", ""),
             "last_login": r.get("last_login", ""), "password_changed_at": r.get("password_changed_at", "")}
            for u, r in sorted(_read_users().items())]


def _actor_role(actor: str) -> str:
    return _read_users().get(actor, {}).get("role", "system")


def _active_admins(users: dict, excluding: str = "") -> int:
    return sum(1 for u, r in users.items()
               if r["role"] == "admin" and not r.get("disabled") and u != excluding)


def create_user(username: str, display_name: str, role: str, password: str,
                must_change: bool = True, actor: str = "system", email: str = "",
                email_verified: bool = False) -> None:
    username = username.strip()
    email = normalize_email(email)
    if email and not valid_email(email):
        raise ValueError("Enter a valid email address, for example name@gmail.com.")
    if not _USERNAME_RE.match(username):
        raise ValueError("Username: 3-40 characters, letters, digits, dot, dash or underscore.")
    if role not in ROLE_LABELS:
        raise ValueError("Unknown role.")
    if not display_name.strip():
        raise ValueError("Enter a display name.")
    errs = validate_password(password, username)
    if errs:
        raise ValueError(" ".join(errs))
    with _file_lock():
        users = _read_users()
        if username in users:
            raise ValueError("That username already exists.")
        if email:
            _claim_email(users, username, email)
        users[username] = _new_record(display_name.strip(), role, password, must_change,
                                      email=email, email_verified=email_verified)
        _write_users(users)
    audit.log_event(actor, _actor_role(actor), "user_created",
                    f"{username} as {role}" + (f" ({mask_email(email)})" if email else ""))


def issue_recovery_code(username, password):
    """Require the current password before generating a new single-use secret."""
    code = secrets.token_urlsafe(24)
    with _file_lock():
        users = _read_users()
        rec = users.get(username)
        if not rec or rec.get("disabled"):
            raise ValueError("Unable to create a recovery code.")
        if not rec.get("hash"):
            raise ValueError("You sign in with Google, so you do not need a recovery code. "
                             "Set a password first if you also want to sign in with a password.")
        digest, _ = hash_password(password, rec["salt"], int(rec.get("iterations", LEGACY_ITERATIONS)))
        if not hmac.compare_digest(digest, rec["hash"]):
            raise ValueError("Current password is incorrect.")
        rec["recovery_hash"] = hashlib.sha256(code.encode()).hexdigest()
        _write_users(users)
    audit.log_event(username, rec["role"], "recovery_code_created", "Previous code invalidated")
    return code


def recover_password(username, code, new_password):
    errs = validate_password(new_password, username)
    if errs:
        raise ValueError(" ".join(errs))
    with _file_lock():
        users = _read_users()
        rec = users.get(username)
        candidate = hashlib.sha256(str(code).strip().encode()).hexdigest()
        if (not rec or rec.get("disabled") or not rec.get("recovery_hash")
                or not hmac.compare_digest(candidate, rec["recovery_hash"])):
            raise ValueError("Username or recovery code is incorrect.")
        rec["hash"], rec["salt"] = hash_password(new_password)
        rec["iterations"] = PBKDF2_ITERATIONS
        rec["password_changed_at"] = _iso(_now())
        rec["must_change"] = False
        rec["failed"], rec["locked_until"] = 0, ""
        rec["session_version"] = int(rec.get("session_version",0)) + 1
        rec.pop("recovery_hash", None)
        _write_users(users)
    audit.log_event(username, rec["role"], "password_recovered", "Single-use recovery code consumed; MFA preserved")


def update_user(username: str, *, role: str | None = None, disabled: bool | None = None,
                reset_mfa: bool = False, actor: str = "system") -> None:
    changes = []
    with _file_lock():
        users = _read_users()
        if username not in users:
            raise ValueError("Unknown user.")
        rec = users[username]
        new_role = role or rec["role"]
        new_disabled = rec.get("disabled", False) if disabled is None else disabled
        if new_role not in ROLE_LABELS:
            raise ValueError("Unknown role.")
        loses_admin = rec["role"] == "admin" and not rec.get("disabled") and (new_role != "admin" or new_disabled)
        if loses_admin and _active_admins(users, excluding=username) == 0:
            raise ValueError("At least one active Administrator must remain.")
        if new_role != rec["role"]:
            changes.append(f"role {rec['role']} -> {new_role}")
            rec["role"] = new_role
        if new_disabled != rec.get("disabled", False):
            changes.append("disabled" if new_disabled else "enabled")
            rec["disabled"] = new_disabled
            rec["failed"], rec["locked_until"] = 0, ""
        if reset_mfa:
            rec["mfa_secret"], rec["mfa_last_counter"] = "", 0
            changes.append("MFA reset")
        _write_users(users)
    if changes:
        audit.log_event(actor, _actor_role(actor), "user_updated", f"{username}: {', '.join(changes)}")


def set_password(username: str, new_password: str, *, must_change: bool = False,
                 actor: str | None = None, action: str = "password_changed") -> None:
    errs = validate_password(new_password, username)
    if errs:
        raise ValueError(" ".join(errs))
    with _file_lock():
        users = _read_users()
        if username not in users:
            raise ValueError("Unknown user.")
        rec = users[username]
        rec["hash"], rec["salt"] = hash_password(new_password)
        rec["iterations"] = PBKDF2_ITERATIONS
        rec["must_change"] = must_change
        rec["failed"], rec["locked_until"] = 0, ""
        rec["password_changed_at"] = _iso(_now())
        _write_users(users)
    who = actor or username
    audit.log_event(who, _actor_role(who), action, username if who != username else "")
    cur = current_user()
    if cur and cur.username == username:
        refresh_user()


def remove_password(username: str, actor: str) -> None:
    """Make an account Google-only (Administrator, when creating a Google sign-in account)."""
    with _file_lock():
        users = _read_users()
        rec = users.get(username)
        if rec is None:
            raise ValueError("Unknown user.")
        if not (rec.get("email") and rec.get("email_verified")):
            raise ValueError("A Google-only account needs a verified email address.")
        rec["hash"], rec["salt"], rec["must_change"] = "", "", False
        rec.pop("recovery_hash", None)
        _write_users(users)
    audit.log_event(actor, _actor_role(actor), "user_updated", f"{username}: Google sign-in only")


# =========================================================================================
# AUTHENTICATION
# =========================================================================================
@dataclass
class AuthResult:
    status: str                  # ok | mfa | bad | locked | disabled
    user: User | None = None
    message: str = ""


def authenticate(username: str, password: str) -> AuthResult:
    """Check credentials, enforce lockout, audit every failure. Never says WHICH part was wrong.
    ``username`` may also be the account's email address."""
    username = username.strip()
    with _file_lock():
        users = _read_users()
        if "@" in username:
            username = _username_for_email(users, username) or username
        rec = users.get(username)
        if rec is None:
            hash_password(password, "00" * 16)        # equalise timing with a real check
            audit.log_event(username[:60] or "(blank)", "-", "login_failed", "unknown username", strict=False)
            return AuthResult("bad", message="Incorrect username or password.")

        from src.mode import lockout_enabled
        lockout = lockout_enabled()
        locked_until = rec.get("locked_until") or ""
        if lockout and locked_until and datetime.fromisoformat(locked_until) > _now():
            audit.log_event(username, rec["role"], "login_blocked", "account locked", strict=False)
            return AuthResult("locked", message=f"Account locked after repeated failures. Try again in "
                              f"{LOCKOUT_MINUTES} minutes or ask an Administrator.")
        if rec.get("disabled"):
            audit.log_event(username, rec["role"], "login_blocked", "account disabled", strict=False)
            return AuthResult("disabled", message="This account is disabled. Contact an Administrator.")

        if not rec.get("hash"):
            audit.log_event(username, rec["role"], "login_failed", "Google-only account", strict=False)
            return AuthResult("bad", message="This account signs in with Google. Press Continue with Google.")
        iters = int(rec.get("iterations", LEGACY_ITERATIONS))
        digest, _ = hash_password(password, rec["salt"], iters)
        if not hmac.compare_digest(digest, rec["hash"]):
            if not lockout:
                # No account lock (the default): a wrong password is refused and recorded, nothing more.
                audit.log_event(username, rec["role"], "login_failed", "bad password", strict=False)
                return AuthResult("bad", message="Incorrect username or password.")
            rec["failed"] = int(rec.get("failed", 0)) + 1
            detail = f"bad password ({rec['failed']}/{MAX_FAILURES})"
            if rec["failed"] >= MAX_FAILURES:
                rec["locked_until"] = _iso(_now() + timedelta(minutes=LOCKOUT_MINUTES))
                rec["failed"] = 0
                detail += f" - locked for {LOCKOUT_MINUTES} minutes"
            _write_users(users)
            audit.log_event(username, rec["role"], "login_failed", detail, strict=False)
            return AuthResult("bad", message="Incorrect username or password.")

        rec["failed"], rec["locked_until"] = 0, ""
        rec["last_login"] = _iso(_now())               # shown on User management (inactive accounts)
        if iters < PBKDF2_ITERATIONS:                 # transparent upgrade of an old hash
            rec["hash"], rec["salt"] = hash_password(password)
            rec["iterations"] = PBKDF2_ITERATIONS
        _write_users(users)
        user = _public(username, rec)
    return AuthResult("mfa" if user.mfa_enabled else "ok", user)


# ---- TOTP (RFC 6238) ------------------------------------------------------------------
def new_mfa_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _totp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    return f"{(struct.unpack('>I', mac[off:off + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def check_totp(secret: str, code: str, last_counter: int = 0, at: float | None = None) -> int | None:
    """Return the matching time-step counter (to store, blocking replay) or None."""
    code = re.sub(r"\s", "", code or "")
    if not re.fullmatch(r"\d{6}", code):
        return None
    now = int((at if at is not None else time.time()) // 30)
    for c in (now - 1, now, now + 1):
        if c > last_counter and hmac.compare_digest(_totp(secret, c), code):
            return c
    return None


def verify_mfa(username: str, code: str) -> bool:
    with _file_lock():
        users = _read_users()
        rec = users.get(username)
        if not rec or not rec.get("mfa_secret"):
            return False
        counter = check_totp(rec["mfa_secret"], code, int(rec.get("mfa_last_counter", 0)))
        if counter is None:
            rec["failed"] = int(rec.get("failed", 0)) + 1
            if rec["failed"] >= MAX_FAILURES:
                rec["locked_until"] = _iso(_now() + timedelta(minutes=LOCKOUT_MINUTES))
                rec["failed"] = 0
            _write_users(users)
            audit.log_event(username, rec["role"], "mfa_failed", "wrong code", strict=False)
            return False
        rec["mfa_last_counter"], rec["failed"] = counter, 0
        _write_users(users)
        return True


def enrol_mfa(username: str, secret: str, code: str) -> bool:
    """Save ``secret`` for the user if ``code`` proves their authenticator has it."""
    counter = check_totp(secret, code)
    if counter is None:
        return False
    with _file_lock():
        users = _read_users()
        users[username]["mfa_secret"], users[username]["mfa_last_counter"] = secret, counter
        _write_users(users)
    audit.log_event(username, users[username]["role"], "mfa_enrolled", "")
    refresh_user()
    return True


# =========================================================================================
# ACCESS + SESSION
# =========================================================================================
LOCAL_USER = User("local", "Local user", "admin")
NO_LOGIN_PAGES = {"users", "account"}        # pages that only make sense with accounts


def start_local_session() -> None:
    """No-sign-in mode: this browser session is the single local operator (full access)."""
    if current_user() is None:
        st.session_state["_auth_user"] = LOCAL_USER
        audit.log_event(LOCAL_USER.username, LOCAL_USER.role, "login", "Opened (no sign-in mode)", strict=False)
    touch()


def can_access(role: str, slug: str) -> bool:
    from src.mode import login_required
    if role == "customer":
        return login_required() and slug in {"customer", "pay", "schedule", "apply", "documents", "profile", "account", "notifications", "support", "help"}
    if slug in {"customer", "pay", "schedule", "apply", "documents", "profile", "notifications", "support", "help"}:
        return False
    if slug in {"requests", "support_staff", "staff_profile"}:
        return role in {"admin", "risk", "officer"}
    if not login_required() and slug in NO_LOGIN_PAGES:
        return False
    allowed = PAGE_ACCESS.get(slug)
    return allowed is None or role in allowed


def current_user() -> User | None:
    return st.session_state.get("_auth_user")


def is_authenticated() -> bool:
    return current_user() is not None


def refresh_user() -> None:
    cur = current_user()
    if cur:
        rec = _read_users().get(cur.username)
        if rec and not rec.get("disabled"):
            st.session_state["_auth_user"] = _public(cur.username, rec)


def touch() -> None:
    st.session_state["_auth_last"] = time.time()


def auto_logout_enabled(username: str) -> bool:
    """Whether this user is signed out automatically after idle minutes. Default OFF
    (src/mode.py); each user switches it with the toggle in the left rail."""
    from src.mode import auto_logout_default
    rec = _read_users().get(username) or {}
    return bool(rec.get("auto_logout", auto_logout_default()))


def set_auto_logout(username: str, on: bool) -> None:
    with _file_lock():
        users = _read_users()
        rec = users.get(username)
        if rec is None:
            return
        rec["auto_logout"] = bool(on)
        _write_users(users)
    audit.log_event(username, rec["role"], "user_updated",
                    f"automatic sign-out turned {'on' if on else 'off'}", strict=False)


def check_session() -> bool:
    """Call on every run. Signs the user out and returns False if disabled, or idle too long
    while automatic sign-out is on."""
    user = current_user()
    if not user:
        return False
    last = st.session_state.get("_auth_last", time.time())
    rec = _read_users().get(user.username)
    if not rec or rec.get("disabled"):
        log_out("Account disabled")
        return False
    if int(st.session_state.get("_auth_session_version",0)) != int(rec.get("session_version",0)):
        log_out("Password was reset. Please sign in again.")
        return False
    from src.mode import auto_logout_default
    auto = bool(rec.get("auto_logout", auto_logout_default()))
    if auto and time.time() - last > session_timeout_minutes() * 60:
        log_out("Session timed out", action="session_timeout")
        return False
    refresh_user()
    touch()
    return True


def log_in(user: User) -> None:
    audit.log_event(user.username, user.role, "login", "Signed in")      # strict: no audit, no session
    st.session_state.pop("_auth_pending", None)
    st.session_state["_auth_user"] = user
    st.session_state["_auth_session_version"] = int((_read_users().get(user.username) or {}).get("session_version",0))
    touch()


def log_out(reason: str = "Signed out", action: str = "logout") -> None:
    user = current_user()
    if user:
        audit.log_event(user.username, user.role, action, reason, strict=False)
    notice = reason if action != "logout" else ""
    google = google_identity() is not None
    st.session_state.clear()
    if notice:
        st.session_state["_login_notice"] = notice
    if google:
        # Also end the Google session, or the sign-in page would sign the person straight back in.
        st.session_state["_google_logout"] = True


def pending_setup(user: User) -> str | None:
    """What a signed-in user must do before anything else: 'password', 'mfa' or None."""
    if user.must_change:
        return "password"
    if mfa_required() and not user.mfa_enabled:
        return "mfa"
    return None


# =========================================================================================
# SCREENS
# =========================================================================================
_GOOGLE_G = ("data:image/svg+xml;base64," + base64.b64encode(
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 '
    b'1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 '
    b'9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 '
    b'5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76'
    b'-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>'
    b'<path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57'
    b'-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>').decode())


def google_configured() -> bool:
    """True when .streamlit/secrets.toml has an [auth] + [auth.google] section and Authlib is
    installed - then the sign-in page shows 'Continue with Google'."""
    try:
        section = st.secrets.get("auth")
        google = section.get("google") if section else None
        ok = bool(section and google and section.get("redirect_uri") and section.get("cookie_secret")
                  and google.get("client_id") and google.get("client_secret"))
    except Exception:
        return False
    if not ok:
        return False
    try:
        import importlib.util
        from streamlit.auth_util import is_authlib_installed
        # Authlib reaches Google through httpx; without it the Google button would end on
        # "Internal Server Error", so it is hidden instead (START installs both).
        has_httpx = any(importlib.util.find_spec(m) is not None for m in ("httpx", "httpx2"))
        return bool(is_authlib_installed()) and has_httpx
    except Exception:
        return False


def google_identity() -> dict | None:
    """The Google account of this browser (st.user), or None when not signed in with Google."""
    try:
        info = st.user
        if not info.get("is_logged_in"):
            return None
        return {"email": normalize_email(info.get("email", "")), "name": str(info.get("name", "") or ""),
                "verified": bool(info.get("email_verified", False))}
    except Exception:
        return None


def _start_google() -> None:
    st.login("google")


def _google_logout() -> None:
    st.session_state["_google_declined"] = True
    try:
        st.logout()
    except Exception:
        pass


def _auth_css() -> None:
    st.markdown(f"""<style>
    .cd-auth-head {{ text-align:center; margin: 3.2rem 0 1.3rem 0; }}
    .cd-auth-mark {{ width:54px; height:54px; border-radius:16px; margin:0 auto .8rem auto;
        background:linear-gradient(135deg,#0B6B62,#07453F); color:#fff; font-size:28px; line-height:54px;
        box-shadow:0 8px 22px rgba(11,107,98,.28); }}
    .cd-auth-brand {{ color:#1B2430; font-size:1.95rem; font-weight:700; letter-spacing:-.02em; }}
    .cd-auth-sub {{ color:#5B6676; font-size:.93rem; margin-top:.25rem; }}
    .st-key-cd_auth_card {{ background:#FFFFFF; border:1px solid #E1E6EC; border-radius:16px;
        padding:1.2rem 1.4rem 1.1rem 1.4rem; box-shadow:0 10px 30px rgba(27,36,48,.07); }}
    .st-key-cd_auth_card [data-testid="stForm"] {{ border:0; padding:0; box-shadow:none; background:transparent; }}
    .st-key-cd_auth_card [data-baseweb="tab-list"] {{ gap:.2rem; }}
    .st-key-cd_auth_card button[data-baseweb="tab"] p {{ font-weight:600; }}
    .cd-or {{ display:flex; align-items:center; gap:.7rem; color:#8A96A6; font-size:.8rem; margin:.9rem 0 .5rem; }}
    .cd-or:before, .cd-or:after {{ content:""; flex:1; border-top:1px solid #E1E6EC; }}
    .cd-auth-note {{ background:#EEF6F4; color:#0B4F48; border-radius:10px; padding:.65rem .8rem;
        font-size:.86rem; line-height:1.45; margin:.2rem 0 .7rem 0; }}
    .cd-auth-note.warn {{ background:#FFF7E6; color:#7A4A06; }}
    .cd-auth-step {{ font-size:.72rem; font-weight:700; letter-spacing:.08em; color:#0B6B62;
        text-transform:uppercase; margin:.2rem 0 .1rem; }}
    .cd-auth-title {{ font-size:1.12rem; font-weight:700; color:#1B2430; margin-bottom:.15rem; }}
    .cd-auth-cap {{ color:#5B6676; font-size:.86rem; margin-bottom:.6rem; line-height:1.45; }}
    .cd-auth-foot {{ text-align:center; color:#8A96A6; font-size:.78rem; margin-top:.9rem; }}
    .st-key-auth_forgot_row {{ align-items:flex-end !important; margin:-.55rem 0 .15rem 0; }}
    .st-key-auth_forgot_row button p, [class*="_row"] button[kind="tertiary"] p {{ color:#0B6B62 !important;
        font-weight:600; font-size:.88rem; }}
    [class*="st-key-auth_back"], [class*="st-key-signup_back"] {{ align-items:center !important; }}
    .st-key-cd_auth_card .stButton button[kind="tertiary"] p {{ color:#0B6B62 !important; font-weight:600; }}
    [class*="st-key-google_btn"] button {{ background:#FFFFFF !important; color:#1F1F1F !important;
        border:1px solid #DADCE0 !important; border-radius:999px !important; min-height:44px;
        font-weight:600 !important; padding-left:2.6rem !important;
        background-image:url("{_GOOGLE_G}") !important; background-repeat:no-repeat !important;
        background-size:20px 20px !important; background-position:1.1rem center !important; }}
    [class*="st-key-google_btn"] button:hover {{ background-color:#F7F8F8 !important; border-color:#C6CACE !important; }}
    [class*="st-key-google_btn"] button p {{ color:#1F1F1F !important; }}
    </style>""", unsafe_allow_html=True)


def _brand() -> None:
    _auth_css()
    st.markdown(
        """
        <div class="cd-auth-head">
          <div class="cd-auth-mark">&#9703;</div>
          <div class="cd-auth-brand">Credit Desk</div>
          <div class="cd-auth-sub">Loan portfolio analytics and decisioning console</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _wide() -> dict:
    from src.ui import STRETCH
    return STRETCH


def _google_button(label: str, key: str) -> None:
    if google_configured():
        st.button(label, key=key, on_click=_start_google, **_wide())


def _or(text: str) -> None:
    st.markdown(f'<div class="cd-or">{text}</div>', unsafe_allow_html=True)


def _note(html: str, warn: bool = False) -> None:
    st.markdown(f'<div class="cd-auth-note{" warn" if warn else ""}">{html}</div>', unsafe_allow_html=True)


def email_codes_on() -> bool:
    """6-digit email codes are offered when an email sender is set up - or, in trial mode, shown on
    screen instead of emailed so the whole flow can be demonstrated without an email account."""
    from src import mailer
    return mailer.configured() or demo_mode()


def _send_code(username: str, purpose: str) -> str | None:
    """Issue + email a code. Returns an error message, or None when sent."""
    from src import mailer
    rec = _read_users().get(username) or {}
    try:
        code = issue_email_code(username, purpose)
        if mailer.configured():
            mailer.send_code(rec.get("email", ""), purpose, rec.get("display_name", ""), code, EMAIL_CODE_MINUTES)
        else:                                   # trial mode without an email account
            st.session_state["_demo_code"] = (purpose, code)
    except (ValueError, RuntimeError) as exc:
        return str(exc)
    return None


def _demo_code_note(purpose: str) -> None:
    from src import mailer
    demo = st.session_state.get("_demo_code")
    if demo and demo[0] == purpose and not mailer.configured():
        _note(f"<b>Trial mode:</b> email sending is not set up, so the code is shown here instead of being "
              f"emailed: <b style='letter-spacing:.2em;font-size:1.05rem'>{demo[1]}</b>", warn=True)


def _go(view: str) -> None:
    """Switch the card between 'signin', 'signup' and 'forgot' (button callback)."""
    st.session_state["_auth_view"] = view
    for k in ("_signup", "_reset", "_reset_use_recovery", "_demo_code", "_google_error"):
        st.session_state.pop(k, None)


def _sign_in_after(username: str) -> None:
    """Open the app for ``username`` - via the authenticator step when MFA is on."""
    rec = _read_users().get(username) or {}
    if rec.get("mfa_secret"):
        st.session_state["_auth_pending"] = {"username": username}
        st.rerun()
    _finish(username)


def _heading(title: str, caption: str = "", step: str = "") -> None:
    st.markdown((f'<div class="cd-auth-step">{step}</div>' if step else "")
                + f'<div class="cd-auth-title">{title}</div>'
                + (f'<div class="cd-auth-cap">{caption}</div>' if caption else ""), unsafe_allow_html=True)


def _handle_google_return() -> bool:
    """Called before the sign-in card. If this browser just came back from Google, sign the person
    in (or show why not). Returns True when the page has been taken over."""
    if st.session_state.pop("_google_logout", False):
        if google_identity():
            _google_logout()
            return True
    if not google_configured() or st.session_state.get("_auth_pending") or st.session_state.get("_google_declined"):
        return False
    ident = google_identity()
    if not ident:
        return False
    res = google_sign_in(ident["email"], ident["name"], ident["verified"])
    if res.status == "ok":
        _finish(res.user.username)
        return True
    if res.status == "mfa":
        st.session_state["_auth_pending"] = {"username": res.user.username}
        st.rerun()
    st.session_state["_google_error"] = (ident["email"], res.message)
    return False


def render_login() -> None:
    """The sign-in page: ONE card. It shows the sign-in form with 'Sign in' and 'Sign up' buttons
    side by side and a 'Forgot password?' link under the password; 'Sign up' and 'Forgot password?'
    swap the card's content (with a way back). Google sign-in appears when .streamlit/secrets.toml
    has the Google keys; email codes when it has an [email] sender (or on screen in trial mode)."""
    ensure_bootstrap()
    if _handle_google_return():
        return
    _brand()
    _, mid, _ = st.columns([1, 1.25, 1])
    with mid:
        if st.session_state.get("_login_notice"):
            st.info(st.session_state.pop("_login_notice"))
        pending = st.session_state.get("_auth_pending")
        if pending:
            with st.container(key="cd_auth_card"):
                _heading("Two-step sign-in", "Enter the 6-digit code from your authenticator app for "
                         f"<b>{pending['username']}</b>.")
                with st.form("mfa_form", border=False):
                    code = st.text_input("Authenticator code", max_chars=7, key="_mfa_code", placeholder="123456")
                    go = st.form_submit_button("Verify", type="primary", **_wide())
                if st.button("Back"):
                    st.session_state.pop("_auth_pending", None)
                    if google_identity():
                        _google_logout()
                    else:
                        st.rerun()
                if go:
                    if verify_mfa(pending["username"], code):
                        _finish(pending["username"])
                    else:
                        st.error("Incorrect or expired code.")
            return

        view = st.session_state.get("_auth_view", "signin")
        with st.container(key="cd_auth_card"):
            if view == "signup":
                _sign_up_view()
            elif view == "forgot":
                _forgot_view()
            else:
                _sign_in_view()

        if demo_mode() and view == "signin":
            st.warning("TRIAL MODE - simple shared passwords are enabled. Sign in with: "
                       "admin / admin123, risk / risk123 or officer / officer123.")
        elif USERS_FILE.exists() and FIRST_RUN_FILE.exists():
            st.info(f"First run: the one-time administrator password is in {FIRST_RUN_FILE.name} "
                    "inside the app's data folder (and was printed to the server console).")
        st.markdown('<div class="cd-auth-foot">Authorised users only. Every sign-in attempt is recorded.</div>',
                    unsafe_allow_html=True)


def _sign_in_view() -> None:
    _heading("Welcome back", "Sign in to continue to Credit Desk.")
    err = st.session_state.pop("_google_error", None)
    if err:
        st.error(f"{err[1]} ({mask_email(err[0])})")
        st.button("Use a different Google account", key="google_other", on_click=_google_logout)
    if google_configured():
        _google_button("Continue with Google", "google_btn_signin")
        _or("or sign in with your username or email")
    username = st.text_input("Username or email", key="_login_user", placeholder="e.g. officer or you@gmail.com")
    password = st.text_input("Password", type="password", key="_login_pass", placeholder="Your password")
    with st.container(key="auth_forgot_row"):
        st.button("Forgot password?", key="auth_forgot_link", type="tertiary", on_click=_go, args=("forgot",))
    left, right = st.columns(2, gap="small")
    submitted = left.button("Sign in", key="auth_signin_btn", type="primary", **_wide())
    right.button("Sign up", key="auth_signup_btn", on_click=_go, args=("signup",), **_wide())
    if submitted:
        if not username.strip() or not password:
            st.error("Enter your username (or email) and your password.")
            return
        res = authenticate(username, password)
        if res.status == "ok":
            _finish(res.user.username)
        elif res.status == "mfa":
            st.session_state["_auth_pending"] = {"username": res.user.username}
            st.rerun()
        else:
            st.error(res.message)


def _back_to_sign_in(label: str = "← Back to sign in", key: str = "auth_back") -> None:
    with st.container(key=f"{key}_row"):
        st.button(label, key=key, type="tertiary", on_click=_go, args=("signin",))


def _sign_up_view() -> None:
    from src import mailer
    step = st.session_state.get("_signup")
    if step and step.get("stage") == "verify":
        _heading("Check your email", step="Step 2 of 2")
        _note(f"&#9993;&#65039; We sent a 6-digit code to <b>{mask_email(step['email'])}</b>. "
              f"It expires in {EMAIL_CODE_MINUTES} minutes. Check Spam if you cannot see it.")
        _demo_code_note("verify")
        with st.form("signup_verify", border=False, clear_on_submit=True):
            code = st.text_input("6-digit code", max_chars=7, placeholder="123456")
            go = st.form_submit_button("Verify email", type="primary", **_wide())
        if go:
            try:
                verify_email_with_code(step["username"], code)
                st.session_state["_signup"] = {**step, "stage": "done"}
                st.session_state.pop("_demo_code", None)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        a, b = st.columns(2)
        if a.button("Send a new code", key="signup_resend", **_wide()):
            problem = _send_code(step["username"], "verify")
            if problem:
                st.error(problem)
            else:
                st.rerun()
        if b.button("Verify later", key="signup_skip", **_wide()):
            st.session_state["_signup"] = {**step, "stage": "done", "skipped": True}
            st.rerun()
        return
    if step and step.get("stage") == "done":
        _heading("&#9989; Your account is ready", f"Username <b>{step['username']}</b> · you can also sign in "
                 "with your email.")
        if step.get("skipped"):
            _note("Your email is <b>not verified yet</b>. You can verify it later in <b>My account</b>.", warn=True)
        else:
            _note(f"<b>{mask_email(step['email'])}</b> is verified. If you forget your password, "
                  "we will send a code to this email.")
        if step.get("recovery"):
            st.markdown("**Your private recovery code** - keep it somewhere safe. It resets your password if "
                        "you cannot use your email, and is shown only now:")
            st.code(step["recovery"], language=None)
        if st.button("Continue to Credit Desk", key="signup_enter", type="primary", **_wide()):
            username = step["username"]
            st.session_state.pop("_signup", None)
            st.session_state["_auth_view"] = "signin"
            _sign_in_after(username)
        _back_to_sign_in("Back to sign in", "signup_back_done")
        return

    _heading("Create your account", "Open a customer account to apply for loans, follow your requests and "
             "see your payments online.")
    if google_configured():
        _google_button("Sign up with Google", "google_btn_signup")
        _or("or sign up with your email")
    with st.form("customer_signup", border=False):
        name = st.text_input("Full name", max_chars=120, placeholder="e.g. Sok Dara", key="_signup_name")
        email = st.text_input("Email", max_chars=254, placeholder="you@gmail.com", key="_signup_email",
                              help="We send a code to this address to confirm it and if you forget your password.")
        new_username = st.text_input("Choose a username", max_chars=40, placeholder="e.g. sokdara", key="_signup_user",
                                     help="3-40 letters, digits, dot, dash or underscore.")
        c1, c2 = st.columns(2)
        new_password = c1.text_input("Password", type="password", key="_signup_pw")
        repeat = c2.text_input("Confirm password", type="password", key="_signup_pw2")
        agree = st.checkbox("I agree that the bank may use my email to contact me about my account.",
                            key="_signup_agree")
        register = st.form_submit_button("Create account", type="primary", **_wide())
    _back_to_sign_in("Already have an account? Sign in", "signup_back")
    if not register:
        return
    if not name.strip() or not email.strip() or not new_username.strip():
        st.error("Fill in your full name, email and a username.")
    elif not valid_email(email):
        st.error("Enter a valid email address, for example name@gmail.com.")
    elif new_password != repeat:
        st.error("The passwords do not match.")
    elif not agree:
        st.error("Tick the box to agree before creating the account.")
    else:
        try:
            create_user(new_username, name, "customer", new_password, must_change=False,
                        actor="customer-registration", email=email)
        except ValueError as exc:
            st.error(str(exc))
            return
        uname = new_username.strip()
        info = {"username": uname, "email": normalize_email(email),
                "recovery": issue_recovery_code(uname, new_password)}
        if email_codes_on():
            problem = _send_code(uname, "verify")
            if problem is None:
                st.session_state["_signup"] = {**info, "stage": "verify"}
                st.rerun()
            st.warning(f"Account created, but the verification email could not be sent: {problem}")
        st.session_state["_signup"] = {**info, "stage": "done", "skipped": True}
        st.rerun()


def _forgot_view() -> None:
    if not email_codes_on() or st.session_state.get("_reset_use_recovery"):
        _recovery_code_view()
        return
    rs = st.session_state.get("_reset")
    if not rs:
        _heading("Forgot your password?", "Enter the email of your account. We will send you a 6-digit code.",
                 step="Step 1 of 2")
        if google_configured():
            _note("Signed up with <b>Google</b>? You have no password to forget - go back and press "
                  "<b>Continue with Google</b>.")
        with st.form("reset_email", border=False):
            email = st.text_input("Email", key="reset_email_in", placeholder="you@gmail.com")
            go = st.form_submit_button("Send code", type="primary", **_wide())
        if go:
            if not valid_email(email):
                st.error("Enter a valid email address.")
            else:
                username = find_username_by_email(email)
                rec = _read_users().get(username) or {}
                if username and rec.get("hash") and not rec.get("disabled"):
                    problem = _send_code(username, "reset")
                    if problem and "wait" not in problem.lower():
                        st.error(problem)
                        return
                else:
                    audit.log_event(normalize_email(email)[:60], "-", "reset_requested",
                                    "no password account for this email", strict=False)
                # Same answer whether or not the address has an account.
                st.session_state["_reset"] = {"email": normalize_email(email)}
                st.rerun()
        st.button("Use a saved recovery code instead", key="reset_to_recovery", type="tertiary",
                  on_click=lambda: st.session_state.update(_reset_use_recovery=True))
        _back_to_sign_in()
        return

    _heading("Enter the code", step="Step 2 of 2")
    _note(f"&#9993;&#65039; If <b>{mask_email(rs['email'])}</b> has an account, a 6-digit code is on its way. "
          f"It expires in {EMAIL_CODE_MINUTES} minutes. Check Spam if you cannot see it.")
    _demo_code_note("reset")
    with st.form("reset_code", border=False, clear_on_submit=True):
        code = st.text_input("6-digit code", max_chars=7, placeholder="123456")
        pw1 = st.text_input("New password", type="password")
        pw2 = st.text_input("Confirm new password", type="password")
        go = st.form_submit_button("Reset password and sign in", type="primary", **_wide())
    if go:
        if pw1 != pw2:
            st.error("The passwords do not match.")
        else:
            try:
                username = reset_password_with_email_code(rs["email"], code, pw1)
                st.session_state.pop("_reset", None)
                st.session_state.pop("_demo_code", None)
                st.session_state["_auth_view"] = "signin"
                _sign_in_after(username)
            except ValueError as exc:
                st.error(str(exc))
    a, b = st.columns(2)
    if a.button("Send a new code", key="reset_resend", **_wide()):
        username = find_username_by_email(rs["email"])
        if username and has_password(username):
            problem = _send_code(username, "reset")
            if problem:
                st.error(problem)
                return
        st.success("If the address has an account, a new code is on its way.")
    if b.button("Change email", key="reset_change", **_wide()):
        st.session_state.pop("_reset", None)
        st.rerun()
    _back_to_sign_in()


def _recovery_code_view() -> None:
    _heading("Reset with a recovery code", "Use the private recovery code you saved when you created the "
             "account (or made in My account). No code? Ask an administrator.")
    if google_configured():
        _note("Signed up with <b>Google</b>? You have no password to forget - go back and press "
              "<b>Continue with Google</b>.")
    with st.form("password_recovery", clear_on_submit=True, border=False):
        recovery_user = st.text_input("Username or email", key="recover_username")
        recovery_code = st.text_input("Recovery code", type="password", placeholder="the code you saved")
        recovery_password = st.text_input("New password", type="password", key="recover_new")
        recovery_repeat = st.text_input("Confirm new password", type="password", key="recover_confirm")
        recover = st.form_submit_button("Reset password", type="primary", **_wide())
    if recover:
        who = recovery_user.strip()
        if "@" in who:
            who = find_username_by_email(who) or who
        if recovery_password != recovery_repeat:
            st.error("The passwords do not match.")
        else:
            try:
                recover_password(who, recovery_code, recovery_password)
                st.session_state["_login_notice"] = ("Password reset. Sign in with your new password, then make "
                                                     "a new recovery code in My account.")
                _go("signin")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    if email_codes_on():
        st.button("Reset by email code instead", key="reset_to_email", type="tertiary",
                  on_click=lambda: st.session_state.pop("_reset_use_recovery", None))
    else:
        st.caption("Email reset codes are not switched on for this installation.")
    _back_to_sign_in()


def _finish(username: str) -> None:
    rec = _read_users().get(username)
    try:
        log_in(_public(username, rec))
    except audit.AuditError as exc:
        st.error(f"Sign-in refused: {exc}")
        return
    st.rerun()


def render_mfa_enrol(user: User) -> None:
    """Show a new secret and enable MFA once the user proves their app produces valid codes."""
    key = f"_mfa_secret_{user.username}"
    secret = st.session_state.setdefault(key, new_mfa_secret())
    issuer = "CreditDesk"
    uri = f"otpauth://totp/{issuer}:{user.username}?secret={secret}&issuer={issuer}&digits=6&period=30"
    st.markdown("1. In an authenticator app (Microsoft Authenticator, Google Authenticator, Authy...) add an "
                "account **by entering a key** and paste this secret:")
    st.code(secret, language=None)
    st.caption(f"Or open this link on the phone that has the app: {uri}")
    with st.form(f"mfa_enrol_{user.username}", clear_on_submit=True):
        code = st.text_input("2. Enter the 6-digit code the app now shows", max_chars=7)
        go = st.form_submit_button("Turn on MFA", type="primary")
    if go:
        if enrol_mfa(user.username, secret, code):
            st.session_state.pop(key, None)
            st.success("MFA is on. You will be asked for a code at every sign-in.")
            st.rerun()
        else:
            st.error("That code is not valid. Check the app's clock and try the next code.")


def render_forced_setup(user: User, step: str) -> None:
    """Block the app until a required password change or MFA enrolment is done."""
    _brand()
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        if step == "password":
            st.subheader("Set a new password")
            st.caption("Your password was issued by an Administrator. Choose your own before continuing.")
            with st.form("force_pw", border=True):
                cur = st.text_input("Current (one-time) password", type="password")
                pw1 = st.text_input("New password", type="password")
                pw2 = st.text_input("Repeat new password", type="password")
                go = st.form_submit_button("Change password", type="primary")
            if go:
                rec = _read_users().get(user.username, {})
                ok, _ = hash_password(cur, rec.get("salt", "00"), int(rec.get("iterations", LEGACY_ITERATIONS)))
                if not hmac.compare_digest(ok, rec.get("hash", "")):
                    st.error("Current password is incorrect.")
                elif pw1 != pw2:
                    st.error("The new passwords do not match.")
                elif pw1 == cur:
                    st.error("Choose a password different from the one-time password.")
                else:
                    try:
                        set_password(user.username, pw1)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        else:
            st.subheader("Set up multi-factor sign-in")
            st.caption("Your organisation requires MFA.")
            render_mfa_enrol(user)
        if st.button("Sign out"):
            log_out()
            st.rerun()
