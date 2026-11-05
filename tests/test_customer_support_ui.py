from streamlit.testing.v1 import AppTest

from src import audit, auth, customer_portal as portal


def test_support_question_staff_reply_and_cancellation_screens(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "DB_PATH", tmp_path / "ui.db")
    actor = auth.User("customer-ui", "Customer", "customer")
    with monkeypatch.context() as setup:
        setup.setattr(auth, "current_user", lambda: actor)
        portal.save_profile("Customer", "012345678", "", "Phnom Penh")
        portal.submit_request(500, 6, "Personal", "School supplies")
    customer_script = tmp_path / "support_customer.py"
    customer_script.write_text('''
import streamlit as st
from src import auth
from views import support
st.session_state['_auth_user'] = auth.User('customer-ui','Customer','customer')
support.render_customer()
''', encoding="utf-8")
    customer = AppTest.from_file(str(customer_script), default_timeout=30).run()
    assert not customer.exception
    next(t for t in customer.text_input if t.label == "Subject").set_value("Payment question")
    next(t for t in customer.text_area if t.label == "Your message").set_value("How do I obtain a statement?")
    next(b for b in customer.button if b.label == "Send question").click().run()
    assert not customer.exception
    assert any("Your question has been sent" in s.value for s in customer.success)
    staff_script = tmp_path / "support_staff.py"
    staff_script.write_text('''
import streamlit as st
from src import auth
from views import support
st.session_state['_auth_user'] = auth.User('staff-ui','Employee','officer')
support.render_staff()
''', encoding="utf-8")
    staff = AppTest.from_file(str(staff_script), default_timeout=30).run()
    assert not staff.exception
    next(t for t in staff.text_area if t.label == "Your reply").set_value("Use Download loan statement in My loans & payments.")
    next(b for b in staff.button if b.label == "Send reply").click().run()
    assert not staff.exception
    customer.run()
    assert not customer.exception
    assert any("Download loan statement" in t.value for t in customer.text)
    with monkeypatch.context() as check:
        check.setattr(auth, "current_user", lambda: actor)
        assert any(n["title"] == "Support replied" for n in portal.my_notifications())
    loan_script = tmp_path / "customer_requests.py"
    loan_script.write_text('''
import streamlit as st
from src import auth
from views import portal
st.session_state['_auth_user'] = auth.User('customer-ui','Customer','customer')
portal.render_apply()
''', encoding="utf-8")
    loan_app = AppTest.from_file(str(loan_script), default_timeout=30).run()
    assert not loan_app.exception
    next(b for b in loan_app.button if b.label == "Cancel request").click().run()
    assert not loan_app.exception
    assert any("has been cancelled" in s.value for s in loan_app.success)
    assert not any(b.label == "Cancel request" for b in loan_app.button)
