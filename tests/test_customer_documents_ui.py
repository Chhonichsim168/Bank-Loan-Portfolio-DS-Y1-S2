import io

from PIL import Image
from streamlit.testing.v1 import AppTest

from src import audit, auth, customer_documents as docs, customer_portal as portal


def screen(tmp_path, name, body):
    path = tmp_path / (name + '.py')
    path.write_text(body, encoding='utf-8')
    return AppTest.from_file(str(path), default_timeout=30)


def test_employee_document_review_is_visible_to_customer(sandbox, monkeypatch):
    customer = auth.User('documents-customer','Customer','customer')
    image = io.BytesIO()
    Image.new('RGB', (120,120), 'teal').save(image, format='PNG')
    with monkeypatch.context() as setup:
        setup.setattr(auth, 'current_user', lambda: customer)
        portal.save_profile('Customer','012345678','','Phnom Penh')
        rid = portal.submit_request(500, 6, 'Personal', 'School supplies')
        docs.attach(rid, image.getvalue(), 'income.png', 'Income proof')
    employee = screen(sandbox, 'employee_documents', '''
import streamlit as st
from src import auth
from views import customer_requests
st.session_state['_auth_user'] = auth.User('employee','Employee','officer')
customer_requests.render()
''').run()
    assert not employee.exception
    next(s for s in employee.selectbox if s.label == 'Document review').select('Needs replacement')
    next(t for t in employee.text_area if t.label == 'Notes for the customer').set_value('Please upload a clearer scan.')
    next(b for b in employee.button if b.label == 'Save document review').click().run()
    assert not employee.exception
    customer_screen = screen(sandbox, 'customer_documents', '''
import streamlit as st
from src import auth
from views import customer
st.session_state['_auth_user'] = auth.User('documents-customer','Customer','customer')
customer.render()
''').run()
    assert not customer_screen.exception
    assert any('Please upload a clearer scan.' in m.value for m in customer_screen.info)
    assert len(customer_screen.get('download_button')) == 1
    assert len(customer_screen.get('file_uploader')) == 1


def test_admin_backup_page_has_clear_passphrase_validation(sandbox, monkeypatch):
    auth._write_users({'admin': auth._new_record('Administrator','admin','ExampleAdmin!2026',False)})
    audit.log_event('admin','admin','test_setup','Temporary backup UI test')
    app = screen(sandbox, 'backup_screen', '''
import streamlit as st
from src import auth
from views import backup_admin
st.session_state['_auth_user'] = auth.User('admin','Administrator','admin')
backup_admin.render()
''').run()
    assert not app.exception
    app.text_input(key='bak_pw').set_value('ExampleBackup!2026')
    app.text_input(key='bak_pw_confirm').set_value('DifferentExample!2026')
    app.button(key='bak_go').click().run()
    assert not app.exception
    assert any('do not match' in e.value for e in app.error)
    app.text_input(key='bak_pw_confirm').set_value('ExampleBackup!2026')
    app.button(key='bak_go').click().run()
    assert not app.exception
    assert any('Backup created' in s.value for s in app.success)
    assert len(app.get('download_button')) == 1
