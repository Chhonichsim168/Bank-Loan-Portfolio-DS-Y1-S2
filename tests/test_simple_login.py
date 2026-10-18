"""Defaults: a sign-in page, simple accounts, simple passwords allowed, and no account lock."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def defaults(sandbox, monkeypatch):
    for v in ("CREDIT_DESK_REQUIRE_LOGIN", "CREDIT_DESK_LOCKOUT", "CREDIT_DESK_STRONG_PASSWORDS",
              "CREDIT_DESK_DEMO_USERS"):
        monkeypatch.delenv(v, raising=False)
    return sandbox


def test_defaults(defaults):
    from src import mode
    assert mode.login_required() and mode.simple_accounts()
    assert not mode.lockout_enabled() and not mode.strong_passwords() and not mode.single_operator()


def test_simple_accounts_are_created_and_work(defaults):
    from src import auth
    auth.ensure_bootstrap()
    for user, pw, role in (("admin", "admin123", "admin"), ("risk", "risk123", "risk"),
                           ("officer", "officer123", "officer")):
        r = auth.authenticate(user, pw)
        assert r.status == "ok" and r.user.role == role and not r.user.must_change


def test_wrong_passwords_never_lock_the_account(defaults):
    from src import audit, auth
    auth.ensure_bootstrap()
    for _ in range(auth.MAX_FAILURES * 3):
        assert auth.authenticate("admin", "wrong").status == "bad"
    assert auth.authenticate("admin", "admin123").status == "ok"      # still gets in
    assert audit.fetch_events(100)["action"].tolist().count("login_failed") == auth.MAX_FAILURES * 3


def test_an_old_lock_is_ignored(defaults):
    """An account locked by an earlier version (as in the screenshot) can sign in again."""
    import json
    from datetime import timedelta
    from src import auth
    auth.ensure_bootstrap()
    users = json.loads(auth.USERS_FILE.read_text())
    users["admin"]["locked_until"] = auth._iso(auth._now() + timedelta(minutes=15))
    auth.USERS_FILE.write_text(json.dumps(users))
    assert auth.authenticate("admin", "admin123").status == "ok"


def test_simple_passwords_are_accepted(defaults):
    from src import auth
    assert auth.validate_password("abc1") == []
    assert auth.validate_password("abc")            # 3 characters is too short


def test_login_page_is_shown_and_signing_in_works(defaults):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300).run()
    assert not at.exception
    assert any(t.label == "Username" for t in at.text_input)
    at.text_input(key=next(t.key for t in at.text_input if t.label == "Username")).set_value("admin")
    at.text_input(key=next(t.key for t in at.text_input if t.label == "Password")).set_value("admin123")
    next(b for b in at.button if b.label == "Sign in").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert "Portfolio overview" in " ".join(m.value for m in at.markdown)
