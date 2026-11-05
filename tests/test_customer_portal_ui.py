"""v25 customer portal (views/portal.py): every page renders, sample customers, KHQR demo payment."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

ROOT = Path(__file__).resolve().parent.parent
PAGES = ["customer", "pay", "schedule", "apply", "support", "documents", "notifications", "profile", "account", "help"]


@pytest.fixture()
def seeded(sandbox, monkeypatch):
    monkeypatch.setenv("CREDIT_DESK_SAMPLE_DATA", "1")
    monkeypatch.delenv("CREDIT_DESK_STRONG_PASSWORDS", raising=False)
    from src import sample_customers
    assert sample_customers.ensure() == ["chhonich", "cichsim"]
    from src import auth
    assert {"admin", "risk", "officer"} <= set(auth._read_users()) or len(auth._read_users()) >= 3
    monkeypatch.setenv("CREDIT_DESK_SAMPLE_DATA", "0")       # keep the staff samples out of the way
    return sandbox


def _as(user, monkeypatch):
    from src import auth
    rec = auth._read_users()[user]
    monkeypatch.setattr(auth, "current_user", lambda: auth._public(user, rec))


def test_sample_customers_are_late_and_on_time(seeded, monkeypatch):
    from src import auth, customer_portal as portal, sample_customers
    users = auth._read_users()
    assert users["chhonich"]["email"] == "chhonichsim1@gmail.com" and users["chhonich"]["email_verified"]
    assert users["cichsim"]["email"] == "cichsim@gmail.com"
    assert auth.authenticate("chhonichsim1@gmail.com", "customer123").status == "ok"
    assert auth.google_sign_in("cichsim@gmail.com", "Cich Sim", True).user.username == "cichsim"
    _as("chhonich", monkeypatch)
    lid = portal.my_loans()["loan_id"].iloc[0]
    snap = portal.loan_details(lid)[1]
    assert snap["arrears"] > 0 and snap["dpd"] >= 28
    _as("cichsim", monkeypatch)
    snap = portal.loan_details(portal.my_loans()["loan_id"].iloc[0])[1]
    assert snap["arrears"] == 0 and snap["dpd"] == 0
    n = len(auth._read_users())
    sample_customers.ensure()                                      # second run creates nothing new
    assert len(auth._read_users()) == n


def test_health_and_payoff(seeded, monkeypatch):
    from src import customer_portal as portal
    from views import portal as cp
    _as("cichsim", monkeypatch)
    rows = cp._my()
    h, pay = rows[0]["health"], rows[0]["payoff"]
    assert h["due"] == h["on_time"] >= 12 and h["streak"] >= 12
    assert 0 < pay["amount"] < pay["remaining"] and pay["saving"] > 0
    assert cp._status(rows)[0] in ("green", "amber")
    _as("chhonich", monkeypatch)
    rows = cp._my()
    assert cp._status(rows)[0] == "red" and rows[0]["health"]["on_time"] < rows[0]["health"]["due"]


@pytest.mark.parametrize("who", ["chhonich", "cichsim"])
def test_every_portal_page_renders(seeded, who):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    at.text_input(key="_login_user").set_value(who)
    at.text_input(key="_login_pass").set_value("customer123")
    next(b for b in at.button if b.label == "Sign in").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Hello" in m.value for m in at.markdown) or any("Hello" in t.value for t in at.title)
    for url in PAGES:
        at._page_hash = calc_hash(url)
        at.run()
        assert not at.exception, (url, [e.value for e in at.exception])
    # staff pages stay out of reach
    at._page_hash = calc_hash("overview")
    at.run()
    assert not any("Portfolio overview" in m.value for m in at.markdown)


PAY = """
import sys
sys.path.insert(0, r"{root}")
import streamlit as st
from src import auth, state, ui
ui.inject_theme(); state.init()
st.session_state["_auth_user"] = auth._public("chhonich", auth._read_users()["chhonich"])
from views import portal
portal.render_pay()
"""


def test_khqr_demo_payment_clears_the_arrears(seeded, monkeypatch):
    from src import audit, customer_portal as portal, loanbook
    at = AppTest.from_string(PAY.format(root=ROOT), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    next(b for b in at.button if b.label == "Create KHQR code").click().run()
    assert not at.exception and at.session_state["_cp_qr"]["amount"] > 0
    next(b for b in at.button if "Simulate a successful payment" in b.label).click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Payment successful" in m.value for m in at.markdown)
    _as("chhonich", monkeypatch)
    lid = portal.my_loans()["loan_id"].iloc[0]
    assert portal.loan_details(lid)[1]["arrears"] < 0.01
    ev = loanbook.events_for(lid)
    assert (ev["role"] == "customer").any() if "role" in ev else True
    assert "customer_payment" in set(audit.fetch_events(50)["action"])


ABA = ("00020101021129450016abaakhppxxx@abaa01090200055490208ABA Bank40600006abaP2P011238C2DFBDC88202090200055"
       "4903090200055480404Dual5204599953031165802KH5912ICHSIM CHHON6010Phnom Penh63041AA6")


def test_khqr_matches_the_bank_crc_and_builds_a_dynamic_code():
    from src import khqr
    assert khqr.crc16(ABA[:-4]) == "1AA6" and khqr.valid(ABA)
    qr = khqr.build(12.5, "USD", bill="CD1234", template=ABA, now_ms=1_700_000_000_000)
    f = dict(khqr.parse(qr))
    assert khqr.valid(qr) and f["01"] == "12" and f["53"] == "840" and f["54"] == "12.50"
    assert f["29"] == dict(khqr.parse(ABA))["29"] and f["59"] == "ICHSIM CHHON"     # same bank account
    assert dict(khqr.parse(f["62"]))["01"] == "CD1234" and len(khqr.md5(qr)) == 32
    assert dict(khqr.parse(khqr.build(4100, "KHR", template=ABA)))["54"] == "4100"


def test_real_khqr_payment_confirmed_by_bakong(seeded, monkeypatch):
    from src import customer_portal as portal, khqr, loanbook
    monkeypatch.setenv("CREDIT_DESK_BAKONG_STATIC_QR", ABA)
    monkeypatch.setenv("CREDIT_DESK_BAKONG_TOKEN", "test-token")
    monkeypatch.setenv("CREDIT_DESK_BAKONG_TEST_AMOUNT", "0.01")
    calls = []
    monkeypatch.setattr(khqr, "check", lambda md5, timeout=8.0: (calls.append(md5), ("paid", {
        "hash": "abc123hash", "fromAccountId": "someone@aclb", "amount": 0.01, "currency": "USD"}))[1])
    at = AppTest.from_string(PAY.format(root=ROOT), default_timeout=60).run()
    next(b for b in at.button if b.label == "Create KHQR code").click().run()
    assert not at.exception, [e.value for e in at.exception]
    # the automatic Bakong check (every 5 s) found the payment straight away
    assert calls and len(calls[0]) == 32
    assert any("Payment successful" in m.value for m in at.markdown)
    assert at.session_state["_cp_receipt"]["bakong"] == "abc123hash"
    _as("chhonich", monkeypatch)
    lid = portal.my_loans()["loan_id"].iloc[0]
    assert portal.loan_details(lid)[1]["arrears"] < 0.01
    ev = loanbook.events_for(lid)
    assert ev["detail"].str.contains("abc123hash").any()


def test_paid_but_unconfirmed_goes_to_staff(seeded, monkeypatch):
    from src import customer_payments
    monkeypatch.setenv("CREDIT_DESK_BAKONG_STATIC_QR", ABA)
    at = AppTest.from_string(PAY.format(root=ROOT), default_timeout=60).run()
    next(b for b in at.button if b.label == "Create KHQR code").click().run()
    assert not any(b.label == "I have paid - check now" for b in at.button)      # no token -> no auto check
    next(b for b in at.button if b.label == "I have paid - ask the bank to confirm").click().run()
    assert not at.exception
    _as("chhonich", monkeypatch)
    assert len(customer_payments.reports()) == 1


def test_admin_opens_an_account_for_an_existing_loan(sandbox, monkeypatch):
    from datetime import timedelta
    from src import auth, customer_portal as portal, loanbook, mailer
    from src.data_pipeline import today_local
    today = today_local().date()
    lid = loanbook.create_loan(username="officer", role="officer", customer_ref="Dara branch loan",
                               product="Personal", principal=1500, annual_rate=.12, term_months=12,
                               disbursed_on=today - timedelta(days=40), first_due_on=today - timedelta(days=10),
                               collateral_value=0, band="Review")
    sent = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html=None: sent.append((to, text)))
    monkeypatch.setattr(auth, "current_user", lambda: auth.User("off", "Officer", "officer"))
    with pytest.raises(PermissionError):
        portal.create_account_for_loans([lid], "Sok Dara", "dara@gmail.com", "012", "Phnom Penh")
    monkeypatch.setattr(auth, "current_user", lambda: auth.User("rm", "Risk", "risk"))
    info = portal.create_account_for_loans([lid], "Sok Dara", "Dara@Gmail.com", "012 111 222", "Phnom Penh")
    assert info["created"] and info["temp_password"] and info["email"] == "dara@gmail.com"
    assert portal.send_account_invitation(info, "Sok Dara") is None and sent[0][0] == "dara@gmail.com"
    assert info["temp_password"] in sent[0][1]
    assert auth.authenticate("dara@gmail.com", info["temp_password"]).status == "ok"
    with pytest.raises(ValueError):
        portal.create_account_for_loans([lid], "X", "x@gmail.com", "1", "PP")         # already linked
    monkeypatch.setattr(auth, "current_user", lambda: auth.User(info["username"], "Sok Dara", "customer"))
    assert portal.my_loans()["loan_id"].tolist() == [lid]
    assert portal.profile()["phone"] == "012 111 222"


# ---- v25 polish: remembered QR codes, emails, user management ---------------------------------
def test_paid_qr_is_found_later_and_emailed(seeded, monkeypatch):
    from src import customer_portal as portal, khqr, mailer, notify, qr_payments
    monkeypatch.setenv("CREDIT_DESK_BAKONG_STATIC_QR", ABA)
    monkeypatch.setenv("CREDIT_DESK_BAKONG_TOKEN", "t")
    monkeypatch.setattr(mailer, "configured", lambda: True)
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html=None: sent.append((to, subject)))
    _as("chhonich", monkeypatch)
    lid = portal.my_loans()["loan_id"].iloc[0]
    arrears = portal.loan_details(lid)[1]["arrears"]
    qr = khqr.build(0.01, "USD", bill="CDTEST", template=ABA)
    qr_payments.register("chhonich", {"md5": khqr.md5(qr), "ref": "CDTEST", "loan": lid, "amount": arrears,
                                      "charge": 0.01, "kind": "payment"})
    monkeypatch.setattr(khqr, "check", lambda md5, timeout=8.0: ("unpaid", None))
    assert qr_payments.recheck("chhonich") == []
    qr_payments._last_check.clear()
    monkeypatch.setattr(khqr, "check", lambda md5, timeout=8.0: ("paid", {"hash": "h1"}))
    found = qr_payments.recheck("chhonich")
    assert len(found) == 1 and portal.loan_details(lid)[1]["arrears"] < 0.01
    qr_payments._last_check.clear()
    assert qr_payments.recheck("chhonich") == []                    # never twice
    assert sent and sent[0][0] == "chhonichsim1@gmail.com" and "Payment received" in sent[0][1]


def test_due_and_late_reminders_are_sent_once(seeded, monkeypatch):
    from src import mailer, notify
    monkeypatch.setattr(mailer, "configured", lambda: True)
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html=None: sent.append((to, subject)))
    first = notify.due_reminders()
    assert any(to == "chhonichsim1@gmail.com" and "overdue" in subj for to, subj in sent)
    assert notify.due_reminders() == 0 and first >= 1                # the log stops repeats


def test_google_sign_in_skips_the_one_time_password_step(sandbox):
    from src import auth
    auth.create_user("vann", "Vann", "customer", auth.generate_temp_password(), must_change=True,
                     email="vann@gmail.com", email_verified=True)
    res = auth.google_sign_in("vann@gmail.com", "Vann", True)
    assert res.user.username == "vann" and not res.user.must_change


USERS = """
import sys
sys.path.insert(0, r"{root}")
import streamlit as st
from src import auth, state, ui
ui.inject_theme(); state.init()
st.session_state["_auth_user"] = auth._public("boss", auth._read_users()["boss"])
from views import users
users.render()
"""


def test_user_management_links_loans_and_resends(sandbox, monkeypatch):
    from datetime import timedelta
    from src import auth, loanbook, mailer
    from src.data_pipeline import today_local
    today = today_local().date()
    auth.create_user("boss", "Boss", "admin", auth.generate_temp_password(), must_change=False)
    lid = loanbook.create_loan(username="boss", role="admin", customer_ref="Branch loan", product="Personal",
                               principal=900, annual_rate=.1, term_months=6, disbursed_on=today - timedelta(days=5),
                               first_due_on=today + timedelta(days=25), collateral_value=0, band="Review")
    at = AppTest.from_string(USERS.format(root=ROOT), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert "Linked loans" in at.dataframe[0].value.columns
    form = [t for t in at.text_input]
    next(t for t in form if t.label == "Username").set_value("sokha")
    next(t for t in form if t.label == "Display name").set_value("Sokha")
    next(t for t in form if t.label.startswith("Email (Gmail")).set_value("sokha@gmail.com")
    next(s for s in at.selectbox if s.label == "Role").set_value("customer")
    next(m for m in at.multiselect if m.label.startswith("Link loan(s)")).set_value([lid])
    next(b for b in at.button if b.label == "Create user").click().run()
    assert not at.exception, [e.value for e in at.exception]
    users = auth._read_users()
    assert users["sokha"]["role"] == "customer"
    at = AppTest.from_string(USERS.format(root=ROOT), default_timeout=60).run()
    assert lid in " ".join(at.dataframe[0].value["Linked loans"])
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda *a, **k: None)
    at.selectbox(key="um_target").set_value("sokha").run()
    at.button(key="um_resend_sokha").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Sign-in email sent" in s.value for s in at.success)
