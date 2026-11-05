"""v25: email on every account, Sign in with Google, email codes (verify + forgot password)."""
import json
from datetime import timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent

GOOGLE_SECRETS = {"auth": {"redirect_uri": "http://localhost:8501/oauth2callback",
                           "cookie_secret": "x" * 40,
                           "google": {"client_id": "id.apps.googleusercontent.com", "client_secret": "s",
                                      "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration"}}}


@pytest.fixture()
def simple(sandbox, monkeypatch):
    monkeypatch.delenv("CREDIT_DESK_STRONG_PASSWORDS", raising=False)
    monkeypatch.delenv("CREDIT_DESK_LOCKOUT", raising=False)
    monkeypatch.delenv("CREDIT_DESK_ADMIN_EMAILS", raising=False)
    return sandbox


# ---- accounts and email ------------------------------------------------------------------
def test_email_is_stored_unique_and_signs_in(simple):
    from src import auth
    auth.create_user("dara", "Sok Dara", "customer", "pass1234", must_change=False, email=" Dara@Gmail.com ")
    rec = auth._read_users()["dara"]
    assert rec["email"] == "dara@gmail.com" and not rec["email_verified"]
    assert auth.authenticate("DARA@gmail.com", "pass1234").status == "ok"
    with pytest.raises(ValueError):
        auth.create_user("x1", "X", "customer", "pass1234", email="not-an-email")
    auth.set_email("dara", "dara@gmail.com", verified=True)
    with pytest.raises(ValueError, match="already used"):
        auth.create_user("other", "Other", "customer", "pass1234", email="dara@gmail.com")


def test_unverified_claim_is_released_to_the_real_owner(simple):
    from src import auth
    auth.create_user("squatter", "S", "customer", "pass1234", must_change=False, email="victim@gmail.com")
    res = auth.google_sign_in("victim@gmail.com", "Victim", True)
    assert res.status == "ok" and res.user.username != "squatter"      # never opens the squatter's account
    assert auth._read_users()["squatter"]["email"] == ""


def test_google_creates_customer_admin_and_reuses_account(simple, monkeypatch):
    from src import audit, auth
    monkeypatch.setenv("CREDIT_DESK_ADMIN_EMAILS", "boss@gmail.com")
    r1 = auth.google_sign_in("new.person@gmail.com", "New Person", True)
    assert r1.status == "ok" and r1.user.role == "customer" and r1.user.username == "new.person"
    r2 = auth.google_sign_in("NEW.PERSON@gmail.com", "New Person", True)
    assert r2.user.username == "new.person" and len(auth._read_users()) == 1
    assert auth.google_sign_in("boss@gmail.com", "Boss", True).user.role == "admin"
    assert auth.google_sign_in("x@gmail.com", "X", False).status == "bad"          # unverified by Google
    # Google-only accounts have no password
    assert auth.authenticate("new.person", "anything").status == "bad"
    assert auth.list_users()[1]["sign_in"] == "Google"
    assert "user_created" in set(audit.fetch_events(50)["action"])


def test_google_links_an_admin_entered_email_and_respects_disabled(simple):
    from src import auth
    auth.create_user("officer2", "Officer Two", "officer", "pass1234", must_change=False,
                     email="o2@gmail.com", email_verified=True)
    res = auth.google_sign_in("o2@gmail.com", "Officer Two", True)
    assert res.user.username == "officer2" and res.user.role == "officer"
    assert auth.list_users()[0]["sign_in"] == "Google + Password"
    auth.update_user("officer2", disabled=True)
    assert auth.google_sign_in("o2@gmail.com", "", True).status == "disabled"


def test_verify_with_google_link_window(simple):
    from src import auth
    auth.create_user("pwuser", "Pw User", "customer", "pass1234", must_change=False, email="pw@gmail.com")
    auth.start_google_link("pwuser")
    res = auth.google_sign_in("pw@gmail.com", "Pw User", True)
    assert res.user.username == "pwuser" and auth.account_email("pwuser") == {
        "email": "pw@gmail.com", "verified": True, "google": True, "password": True}


def test_admin_google_only_account(simple):
    from src import auth
    auth.create_user("gone", "G One", "risk", auth.generate_temp_password(), must_change=False,
                     email="g1@gmail.com", email_verified=True)
    auth.remove_password("gone", actor="system")
    assert not auth.has_password("gone")
    with pytest.raises(ValueError):
        auth.issue_recovery_code("gone", "")
    assert auth.google_sign_in("g1@gmail.com", "G One", True).user.role == "risk"
    auth.set_password("gone", "newpass1")                      # can add a password later
    assert auth.authenticate("g1@gmail.com", "newpass1").status == "ok"


# ---- email codes -------------------------------------------------------------------------
def test_verify_code_flow(simple):
    from src import auth
    auth.create_user("cone", "C One", "customer", "pass1234", must_change=False, email="c1@gmail.com")
    code = auth.issue_email_code("cone", "verify")
    assert len(code) == 6 and code not in json.dumps(auth._read_users())     # only the hash is stored
    with pytest.raises(ValueError, match="wait"):
        auth.issue_email_code("cone", "verify")                               # resend cooldown
    with pytest.raises(ValueError, match="tries left"):
        auth.verify_email_with_code("cone", "000000" if code != "000000" else "111111")
    auth.verify_email_with_code("cone", code)
    assert auth.account_email("cone")["verified"]
    with pytest.raises(ValueError):
        auth.verify_email_with_code("cone", code)                             # single use


def test_codes_expire_and_lock_after_five_tries(simple):
    from src import auth
    auth.create_user("ctwo", "C Two", "customer", "pass1234", must_change=False, email="c2@gmail.com")
    code = auth.issue_email_code("ctwo", "reset")
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(auth.EMAIL_CODE_TRIES - 1):
        with pytest.raises(ValueError, match="tries left"):
            auth.reset_password_with_email_code("c2@gmail.com", wrong, "newpass1")
    with pytest.raises(ValueError, match="Too many"):
        auth.reset_password_with_email_code("c2@gmail.com", wrong, "newpass1")
    with pytest.raises(ValueError):
        auth.reset_password_with_email_code("c2@gmail.com", code, "newpass1")   # the code is gone
    users = auth._read_users()
    users["ctwo"].pop("email_code", None)
    auth._write_users(users)
    code = auth.issue_email_code("ctwo", "reset")
    users = auth._read_users()
    users["ctwo"]["email_code"]["expires"] = auth._iso(auth._now() - timedelta(minutes=1))
    auth._write_users(users)
    with pytest.raises(ValueError, match="expired"):
        auth.reset_password_with_email_code("c2@gmail.com", code, "newpass1")


def test_reset_password_by_email_code(simple):
    from src import auth
    auth.create_user("cthree", "C Three", "customer", "pass1234", must_change=False, email="c3@gmail.com")
    code = auth.issue_email_code("cthree", "reset")
    assert auth.reset_password_with_email_code("C3@gmail.com", code, "brandnew1") == "cthree"
    assert auth.authenticate("cthree", "brandnew1").status == "ok"
    assert auth.account_email("cthree")["verified"]


def test_mailer_sends_a_branded_code_email(simple, monkeypatch):
    from src import mailer
    monkeypatch.setenv("CREDIT_DESK_SMTP_SENDER", "desk@gmail.com")
    monkeypatch.setenv("CREDIT_DESK_SMTP_PASSWORD", "abcd efgh ijkl mnop")
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, **kw):
            sent["server"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, pw):
            sent["login"] = (user, pw)

        def send_message(self, msg):
            sent["msg"] = msg

    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    assert mailer.configured()
    mailer.send_code("dara@gmail.com", "reset", "Sok Dara", "482913", 15)
    msg = sent["msg"]
    assert sent["server"] == ("smtp.gmail.com", 465) and sent["login"] == ("desk@gmail.com", "abcdefghijklmnop")
    assert msg["To"] == "dara@gmail.com" and "482913" in msg["Subject"]
    assert "482913" in msg.get_body(("plain",)).get_content()
    assert "Reset your password" in msg.get_body(("html",)).get_content()


def test_mailer_off_without_settings(simple, monkeypatch):
    from src import mailer
    monkeypatch.delenv("CREDIT_DESK_SMTP_SENDER", raising=False)
    monkeypatch.delenv("CREDIT_DESK_SMTP_PASSWORD", raising=False)
    assert not mailer.configured()
    with pytest.raises(RuntimeError):
        mailer.send("a@b.com", "s", "t")


# ---- screens -----------------------------------------------------------------------------
def _app():
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)


def test_sign_in_page_has_three_tabs_and_google_when_configured(simple):
    at = _app()
    at.run()
    assert not at.exception
    assert not at.tabs                                                # one card, no tabs
    labels = [b.label for b in at.button]
    assert {"Sign in", "Sign up", "Forgot password?"} <= set(labels)
    assert not any("Google" in b.label for b in at.button)            # no keys -> no Google button
    at = _app()
    for k, v in GOOGLE_SECRETS.items():
        at.secrets[k] = v
    at.run()
    assert not at.exception
    assert "Continue with Google" in [b.label for b in at.button]
    at.button(key="auth_signup_btn").click().run()
    assert "Sign up with Google" in [b.label for b in at.button]


def test_sign_up_with_email_then_sign_in_with_the_email(simple, monkeypatch):
    from src import auth
    monkeypatch.setenv("CREDIT_DESK_DEMO_USERS", "0")
    at = _app().run()
    at.button(key="auth_signup_btn").click().run()
    at.text_input(key="_signup_name").set_value("Sok Dara")
    at.text_input(key="_signup_email").set_value("sok.dara@gmail.com")
    at.text_input(key="_signup_user").set_value("sokdara")
    at.text_input(key="_signup_pw").set_value("pass1234")
    at.text_input(key="_signup_pw2").set_value("pass1234")
    next(b for b in at.button if b.label == "Create account").click().run()
    assert any("agree" in e.value for e in at.error)                  # checkbox required
    at.checkbox(key="_signup_agree").check()
    next(b for b in at.button if b.label == "Create account").click().run()
    assert not at.exception
    assert auth._read_users()["sokdara"]["email"] == "sok.dara@gmail.com"
    assert any("Your account is ready" in m.value for m in at.markdown)
    assert at.code[0].value                                            # recovery code shown once
    at.button(key="signup_back_done").click().run()
    at.text_input(key="_login_user").set_value("sok.dara@gmail.com")
    at.text_input(key="_login_pass").set_value("pass1234")
    next(b for b in at.button if b.label == "Sign in").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["_auth_user"].username == "sokdara"
    assert any("Hello" in m.value for m in at.markdown)


def test_sign_up_sends_a_code_when_email_is_configured(simple, monkeypatch):
    from src import auth, mailer
    monkeypatch.setenv("CREDIT_DESK_SMTP_SENDER", "desk@gmail.com")
    monkeypatch.setenv("CREDIT_DESK_SMTP_PASSWORD", "pw")
    box = []
    monkeypatch.setattr(mailer, "send_code", lambda to, purpose, name, code, minutes: box.append(code))
    at = _app().run()
    at.button(key="auth_signup_btn").click().run()
    for key, val in (("_signup_name", "Lina"), ("_signup_email", "lina@gmail.com"), ("_signup_user", "lina"),
                     ("_signup_pw", "pass1234"), ("_signup_pw2", "pass1234")):
        at.text_input(key=key).set_value(val)
    at.checkbox(key="_signup_agree").check()
    next(b for b in at.button if b.label == "Create account").click().run()
    assert not at.exception and len(box) == 1
    assert any("li•••@gmail.com" in m.value for m in at.markdown)
    next(t for t in at.text_input if t.label == "6-digit code").set_value(box[0])
    next(b for b in at.button if b.label == "Verify email").click().run()
    assert not at.exception
    assert auth.account_email("lina")["verified"]
    at.button(key="signup_enter").click().run()                        # straight into the app
    assert not at.exception and at.session_state["_auth_user"].username == "lina"


def test_forgot_password_by_email_on_screen(simple, monkeypatch):
    from src import auth, mailer
    monkeypatch.setenv("CREDIT_DESK_SMTP_SENDER", "desk@gmail.com")
    monkeypatch.setenv("CREDIT_DESK_SMTP_PASSWORD", "pw")
    box = []
    monkeypatch.setattr(mailer, "send_code", lambda to, purpose, name, code, minutes: box.append((to, code)))
    auth.create_user("vyvy", "Vy", "customer", "oldpass1", must_change=False, email="vy@gmail.com")
    at = _app().run()
    at.button(key="auth_forgot_link").click().run()
    at.text_input(key="reset_email_in").set_value("vy@gmail.com")
    next(b for b in at.button if b.label == "Send code").click().run()
    assert box and box[0][0] == "vy@gmail.com"
    next(t for t in at.text_input if t.label == "6-digit code").set_value(box[0][1])
    next(t for t in at.text_input if t.label == "New password").set_value("newpass9")
    next(t for t in at.text_input if t.label == "Confirm new password").set_value("newpass9")
    next(b for b in at.button if b.label == "Reset password and sign in").click().run()
    assert not at.exception
    assert at.session_state["_auth_user"].username == "vyvy"            # signed in straight away
    assert auth.authenticate("vyvy", "newpass9").status == "ok"
    # an unknown address gets the same screen and no email
    at = _app().run()
    at.button(key="auth_forgot_link").click().run()
    at.text_input(key="reset_email_in").set_value("nobody@gmail.com")
    next(b for b in at.button if b.label == "Send code").click().run()
    assert len(box) == 1 and any("no•••@gmail.com" in m.value for m in at.markdown)


ACCOUNT = """
import sys
sys.path.insert(0, r"{root}")
import streamlit as st
from src import auth, state, ui
ui.inject_theme(); state.init()
st.session_state["_auth_user"] = auth._public("{user}", auth._read_users()["{user}"])
from views import {page}
{page}.render()
"""


@pytest.mark.parametrize("google_only", [False, True])
def test_my_account_page(simple, google_only):
    from src import auth
    auth.create_user("acc", "Acc User", "customer", "pass1234", must_change=False, email="acc@gmail.com")
    if google_only:
        auth.set_email("acc", "acc@gmail.com", verified=True)
        auth.remove_password("acc", actor="system")
    at = AppTest.from_string(ACCOUNT.format(root=ROOT, user="acc", page="account"), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    labels = [b.label for b in at.button]
    assert "Save email" in labels
    assert ("Set a password" in labels) == google_only
    assert ("Change password" in labels) != google_only
    html = " ".join(m.value for m in at.markdown)
    assert "acc@gmail.com" in html and ("Verified" in html if google_only else "Not verified" in html)


def test_user_management_shows_and_sets_email(simple):
    from src import auth
    auth.create_user("boss", "Boss", "admin", "pass1234", must_change=False)
    auth.create_user("off1", "Officer One", "officer", "pass1234", must_change=False)
    at = AppTest.from_string(ACCOUNT.format(root=ROOT, user="boss", page="users"), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert "Email" in at.dataframe[0].value.columns and "Sign-in" in at.dataframe[0].value.columns
    at.selectbox(key="um_target").set_value("off1").run()
    at.text_input(key="um_email_off1").set_value("o1@gmail.com")
    at.button(key="um_save").click().run()
    assert not at.exception
    assert auth.account_email("off1") == {"email": "o1@gmail.com", "verified": True, "google": False, "password": True}


def test_trial_mode_shows_the_code_on_screen_without_email(simple, monkeypatch):
    from src import auth
    monkeypatch.setenv("CREDIT_DESK_DEMO_USERS", "1")
    monkeypatch.delenv("CREDIT_DESK_SMTP_SENDER", raising=False)
    auth.create_user("demo1", "Demo", "customer", "oldpass1", must_change=False, email="demo1@gmail.com")
    at = _app().run()
    at.button(key="auth_forgot_link").click().run()
    at.text_input(key="reset_email_in").set_value("demo1@gmail.com")
    next(b for b in at.button if b.label == "Send code").click().run()
    code = at.session_state["_demo_code"][1]
    assert any(code in m.value and "Trial mode" in m.value for m in at.markdown)
    next(t for t in at.text_input if t.label == "6-digit code").set_value(code)
    next(t for t in at.text_input if t.label == "New password").set_value("fresh123")
    next(t for t in at.text_input if t.label == "Confirm new password").set_value("fresh123")
    next(b for b in at.button if b.label == "Reset password and sign in").click().run()
    assert not at.exception and at.session_state["_auth_user"].username == "demo1"
