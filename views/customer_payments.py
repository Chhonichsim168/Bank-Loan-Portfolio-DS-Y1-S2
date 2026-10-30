"""Payment instructions, customer reporting and employee verification."""
from src.customer_i18n import t
import os
import streamlit as st
from src import customer_payments as payments, audit
from src.data_pipeline import today_local, to_local
from views._customer_feedback import show_error

def render_customer(lid, loan, snap):
    st.subheader(t('How to make a payment'))
    instructions = os.environ.get('CREDIT_DESK_PAYMENT_INSTRUCTIONS', '').strip()
    if instructions:
        st.text(instructions)
    else:
        st.info(t('Contact the support team for the verified payment destination before transferring money.'))
    with st.expander(t('Report a payment')):
        with st.form(f'payment_report_{lid}', clear_on_submit=True):
            amount = st.number_input(t('Amount paid ($)'), min_value=0.01, max_value=1000000000.0, value=max(0.01, float(snap['next_amount'])), format='%.2f', step=1.0, key='i18n_views_customer_payments_py_20')
            paid_on = st.date_input(t('Date paid'), value=today_local().date(), max_value=today_local().date(), key='i18n_views_customer_payments_py_22')
            reference = st.text_input(t('Transfer / receipt reference'), max_chars=120, key='i18n_views_customer_payments_py_23')
            confirm = st.checkbox(t('I have already made this payment.'), key='i18n_views_customer_payments_py_24')
            send = st.form_submit_button(t('Submit for verification'), disabled=snap['status'] != 'Active', key='i18n_views_customer_payments_py_25')
        if send:
            try:
                if not confirm:
                    raise ValueError('Confirm that you have already made the payment.')
                payments.submit(lid, amount, paid_on, reference)
                st.success(t('Payment reported. Staff must verify it before it appears in your payment history.'))
            except (ValueError, PermissionError, OSError, audit.AuditError) as exc:
                show_error(exc, 'report the payment')
    reports = payments.reports()
    for report in reports[reports['loan_id'] == lid].itertuples():
        with st.expander(t(f'{report.report_id} · ${report.amount:,.2f} · {report.status}')):
            st.write(f'Paid on {to_local(report.payment_date, '%d/%m/%Y')} · Reference: {report.reference}')
            if report.review_note:
                st.write(report.review_note)

def render_staff():
    st.subheader(t('Payment verification'))
    reports = payments.reports()
    pending = reports[reports['status'] == 'Pending']
    st.caption(t(f'{len(pending)} payment(s) awaiting verification. Confirm only after checking that funds were received.'))
    for report in pending.itertuples():
        with st.expander(t(f'{report.username} · ${report.amount:,.2f} · {report.loan_id}')):
            st.write(f'{report.report_id} · Paid {to_local(report.payment_date, '%d/%m/%Y')} · Reference: {report.reference}')
            with st.form(f'verify_{report.report_id}'):
                decision = st.radio(t('Decision'), ['Confirm received', 'Reject'], key=f'decision_{report.report_id}', format_func=t)
                note = st.text_area(t('Verification / rejection notes'), max_chars=1000, key='i18n_views_customer_payments_py_52')
                checked = st.checkbox(t('I checked this payment against the payment records.'), key='i18n_views_customer_payments_py_53')
                save = st.form_submit_button(t('Save decision'), key='i18n_views_customer_payments_py_54')
            if save:
                try:
                    if not checked:
                        raise ValueError('Check the payment records before saving a decision.')
                    payments.review(report.report_id, decision == 'Confirm received', note)
                    st.rerun()
                except (ValueError, PermissionError, OSError, audit.AuditError) as exc:
                    show_error(exc, 'review the payment')
