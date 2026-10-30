"""Render real Streamlit screens using disposable accounts and data."""
from pathlib import Path

from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

from src import audit, auth, loanbook
from src.data_pipeline import today_local

ROOT = Path(__file__).resolve().parents[1]


def test_login_customer_and_employee_screens(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "DB_PATH", tmp_path / "audit.db")
    monkeypatch.setattr(auth, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setenv("CREDIT_DESK_SAMPLE_DATA", "0")
    monkeypatch.setenv("CREDIT_DESK_REQUIRE_LOGIN", "1")
    auth._write_users({"customer-test": auth._new_record("Demo Customer", "customer", "demo-password", False)})
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert any(e.label == "New customer? Create an account" for e in app.expander)
    next(t for t in app.text_input if t.label == "Full name").set_value("Second Customer")
    next(t for t in app.text_input if t.label == "Choose a username").set_value("second-customer")
    next(t for t in app.text_input if t.label == "Choose a password").set_value("new-password")
    next(t for t in app.text_input if t.label == "Confirm password").set_value("new-password")
    next(b for b in app.button if b.label == "Create customer account").click().run()
    assert not app.exception
    assert auth._read_users()["second-customer"]["role"] == "customer"
    assert any(b.label == "Sign in" for b in app.button)
    app.text_input(key="_login_user").set_value("customer-test")
    app.text_input(key="_login_pass").set_value("demo-password")
    next(b for b in app.button if b.label == "Sign in").click().run()
    assert not app.exception
    assert any(t.value == "My customer portal" for t in app.title) or any(
        "My customer portal" in m.value for m in app.markdown)
    assert not any(b.label == "Refresh customer requests" for b in app.button)
    assert not any(t.label == "Phone number" for t in app.text_input)
    assert not any(t.label == "My profile" for t in app.tabs)
    app.button(key="customer_profile_avatar").click().run()
    assert not app.exception
    assert len(app.get("file_uploader")) == 1
    assert not any(b.label == "Save photo" for b in app.button)
    assert sum(b.label == "Save my profile" for b in app.button) == 1
    assert not any(b.label == "Submit loan request" for b in app.button)
    # Complete the customer profile and submit a request through the real widgets.
    next(t for t in app.text_input if t.label == "Phone number").set_value("012345678")
    next(t for t in app.text_area if t.label == "Location / address").set_value("Phnom Penh")
    next(b for b in app.button if b.label == "Save my profile").click().run()
    assert not app.exception
    assert any(s.value == "Your profile has been saved." for s in app.success)
    app._page_hash = calc_hash("customer")
    app.run()
    assert not app.exception
    assert not any(t.label == "Phone number" for t in app.text_input)
    next(t for t in app.text_area if t.label == "What will you use the loan for?").set_value("Study materials")
    next(b for b in app.button if b.label == "Submit loan request").click().run()
    assert not app.exception
    assert app.button(key="customer_notification_bell").label == "Notifications (1 unread)"
    app.button(key="customer_notification_bell").click().run()
    assert not app.exception
    assert any("was received" in n.value for n in app.info)
    assert app.button(key="customer_notification_bell").label == "Notifications (0 unread)"
    next(b for b in app.button if b.label == "Sign out").click().run()
    assert not app.exception
    assert any(b.label == "Sign in" for b in app.button)
    # Render employee review independently of model training and sample seeding.
    staff_script = tmp_path / "employee_screen.py"
    staff_script.write_text('''
import streamlit as st
from src import auth
from views import customer_requests
st.session_state['_auth_user'] = auth.User('employee', 'Employee', 'officer')
customer_requests.render()
''', encoding="utf-8")
    staff = AppTest.from_file(str(staff_script), default_timeout=30).run()
    assert not staff.exception
    next(t for t in staff.text_area if t.label == "Explanation for the customer").set_value("Reviewed for demo")
    next(b for b in staff.button if b.label == "Save employee decision").click().run()
    assert not staff.exception
    next(s for s in staff.selectbox if s.label == "Show requests").select("Approved").run()
    assert not staff.exception
    next(c for c in staff.checkbox if c.label == "I confirm the money has been issued to this customer.").check()
    next(b for b in staff.button if b.label == "Record issued loan").click().run()
    assert not staff.exception
    assert any("Loan issued:" in s.value for s in staff.success)
    lid = loanbook.list_loans().iloc[0]["loan_id"]
    loanbook.add_event(lid, username="employee", role="officer", kind="payment",
                       event_date=today_local().date(), amount=50)
    app.text_input(key="_login_user").set_value("customer-test")
    app.text_input(key="_login_pass").set_value("demo-password")
    next(b for b in app.button if b.label == "Sign in").click().run()
    assert not app.exception
    assert any(m.label == "My issued loans" and m.value == "1" for m in app.metric)
    assert any(m.label == "Principal repaid" and m.value == "$40.00" for m in app.metric)
    assert any(m.label == "Interest paid" and m.value == "$10.00" for m in app.metric)
    assert len(app.dataframe) == 2  # payment history and schedule
    assert len(app.get("download_button")) == 2  # statement and individual receipt
    assert any(s.label == "Choose a payment receipt" for s in app.selectbox)
    assert app.button(key="customer_notification_bell").label == "Notifications (2 unread)"
    app.button(key="customer_notification_bell").click().run()
    assert not app.exception
    assert any(h.value == "Loan request approved" for h in app.subheader)
    assert app.button(key="customer_notification_bell").label == "Notifications (0 unread)"


def test_click_profile_photo_opens_larger_view_without_saving(tmp_path, monkeypatch):
    import io
    from PIL import Image
    from src import customer_portal as portal
    monkeypatch.setattr(audit, "DB_PATH", tmp_path / "photo.db")
    customer = auth.User("photo-test", "Customer", "customer")
    image = io.BytesIO()
    Image.new("RGB", (300, 300), "teal").save(image, format="PNG")
    with monkeypatch.context() as setup:
        setup.setattr(auth, "current_user", lambda: customer)
        portal.save_profile("Customer", "012345678", "", "Phnom Penh", photo=image.getvalue())
        updated = portal.profile()["updated_at"]
    script = tmp_path / "photo_screen.py"
    script.write_text('''
import streamlit as st
from src import auth
from views import customer
st.session_state['_auth_user'] = auth.User('photo-test', 'Customer', 'customer')
customer.render_profile()
''', encoding="utf-8")
    app = AppTest.from_file(str(script), default_timeout=30).run()
    assert not app.exception
    next(b for b in app.button if b.label == "View profile photo").click().run()
    assert not app.exception
    assert len(app.get("dialog")) == 1
    assert sum(b.label == "Save my profile" for b in app.button) == 1
    with monkeypatch.context() as check:
        check.setattr(auth, "current_user", lambda: customer)
        assert portal.profile()["updated_at"] == updated
