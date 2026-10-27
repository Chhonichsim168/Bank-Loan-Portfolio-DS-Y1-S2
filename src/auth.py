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
USERS_FILE = Path(os.environ.get("CREDIT_DESK_USERS_FILE", ROOT / "data" / "users.json"))
FIRST_RUN_FILE = ROOT / "data" / "first_run_admin.txt"

ROLE_LABELS: dict[str, str] = {
    "admin": "Administrator",
    "risk": "Risk Manager",
    "officer": "Credit Officer",
}

# Which roles may see which page slug. A slug with no entry is open to any signed-in user.
PAGE_ACCESS: dict[str, set[str]] = {
    "policy": {"risk", "admin"},
    "model": {"risk", "admin"},
    "data": {"risk", "admin"},
    "users": {"admin"},
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


def _new_record(display_name: str, role: str, password: str, must_change: bool) -> dict:
    digest, salt = hash_password(password)
    return {"display_name": display_name, "role": role, "hash": digest, "salt": salt,
            "iterations": PBKDF2_ITERATIONS, "disabled": False, "must_change": must_change,
            "mfa_secret": "", "mfa_last_counter": 0, "failed": 0, "locked_until": "",
            "created_at": _iso(_now()), "password_changed_at": _iso(_now())}


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


def list_users() -> list[dict]:
    return [{"username": u, "display_name": r["display_name"], "role": r["role"],
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
                must_change: bool = True, actor: str = "system") -> None:
    username = username.strip()
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
        users[username] = _new_record(display_name.strip(), role, password, must_change)
        _write_users(users)
    audit.log_event(actor, _actor_role(actor), "user_created", f"{username} as {role}")


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


# =========================================================================================
# AUTHENTICATION
# =========================================================================================
@dataclass
class AuthResult:
    status: str                  # ok | mfa | bad | locked | disabled
    user: User | None = None
    message: str = ""


def authenticate(username: str, password: str) -> AuthResult:
    """Check credentials, enforce lockout, audit every failure. Never says WHICH part was wrong."""
    username = username.strip()
    with _file_lock():
        users = _read_users()
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
    touch()


def log_out(reason: str = "Signed out", action: str = "logout") -> None:
    user = current_user()
    if user:
        audit.log_event(user.username, user.role, action, reason, strict=False)
    notice = reason if action != "logout" else ""
    st.session_state.clear()
    if notice:
        st.session_state["_login_notice"] = notice


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
def _brand() -> None:
    st.markdown(
        """
        <div class="cd-login-wrap">
          <div class="cd-login-brand">Credit Desk</div>
          <div class="cd-login-sub">Loan portfolio analytics and decisioning console</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_login() -> None:
    """Sign-in card; handles the password step and, if enrolled, the authenticator-code step."""
    ensure_bootstrap()
    _brand()
    _, mid, _ = st.columns([1, 1.1, 1])
    with mid:
        if st.session_state.get("_login_notice"):
            st.warning(st.session_state.pop("_login_notice"))
        pending = st.session_state.get("_auth_pending")
        if pending:
            with st.form("mfa_form", border=True):
                st.markdown(f"Enter the 6-digit code from your authenticator app for **{pending['username']}**.")
                code = st.text_input("Authenticator code", max_chars=7, key="_mfa_code")
                go = st.form_submit_button("Verify", type="primary")
            if st.button("Back"):
                st.session_state.pop("_auth_pending", None)
                st.rerun()
            if go:
                if verify_mfa(pending["username"], code):
                    _finish(pending["username"])
                else:
                    st.error("Incorrect or expired code.")
            return

        with st.form("login_form", clear_on_submit=False, border=True):
            username = st.text_input("Username", key="_login_user")
            password = st.text_input("Password", type="password", key="_login_pass")
            submitted = st.form_submit_button("Sign in", type="primary")
        if submitted:
            res = authenticate(username, password)
            if res.status == "ok":
                _finish(res.user.username)
            elif res.status == "mfa":
                st.session_state["_auth_pending"] = {"username": res.user.username}
                st.rerun()
            else:
                st.error(res.message)

        if demo_mode():
            st.warning("TRIAL MODE - simple shared passwords are enabled. Sign in with: "
                       "admin / admin123, risk / risk123 or officer / officer123.")
        elif USERS_FILE.exists() and FIRST_RUN_FILE.exists():
            st.info(f"First run: the one-time administrator password is in {FIRST_RUN_FILE.name} "
                    "inside the app's data folder (and was printed to the server console).")
        st.markdown(
            '<p style="text-align:center;color:#8A96A6;font-size:0.78rem;'
            'margin-top:0.9rem;">Authorised users only. Every sign-in attempt is recorded.</p>',
            unsafe_allow_html=True,
        )


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
