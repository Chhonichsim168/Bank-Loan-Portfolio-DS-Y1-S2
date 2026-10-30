"""Private customer home: profile, requests, loans and payment reminders."""
from __future__ import annotations
from src.customer_i18n import t
from views.customer_help import requirements, empty_state
from views.customer_feedback import confirm_action, show_confirmation, profile_completion
import inspect
import pandas as pd
import streamlit as st
from src import audit, customer_portal as portal, customer_search, loanbook, ui
from src.data_pipeline import today_local, to_local
from src.deps import MissingLibrary
from views import request_documents
from views._customer_feedback import show_error

def cash(value):
    return f'${float(value):,.2f}'

def _load_application():
    user = portal.require_role("customer")
    reset = st.session_state.pop("_application_reset",False)
    if st.session_state.get("_application_owner") == user.username and not reset:
        return
    saved = portal.application_draft()
    values = saved or dict(amount=10000.0,term=10,rate=10.0,product=loanbook.PRODUCTS[0],purpose="")
    for key,field in [("quote_amount","amount"),("quote_term","term"),("quote_rate","rate"),
                      ("application_product","product"),("application_purpose","purpose")]:
        st.session_state[key] = values[field]
    st.session_state["i18n_views_customer_py_137"] = False
    st.session_state["_application_owner"] = user.username
    st.session_state["_draft_saved_at"] = saved.get("updated_at") if saved else None
    if saved:
        st.session_state["_draft_restored"] = True


def _save_application():
    try:
        portal.save_application_draft(st.session_state.get("quote_amount",10000.0),
            st.session_state.get("quote_term",10),st.session_state.get("quote_rate",10.0),
            st.session_state.get("application_product",loanbook.PRODUCTS[0]),
            st.session_state.get("application_purpose",""))
        st.session_state["_draft_saved_at"] = audit._now()
        st.session_state.pop("_draft_save_error",None)
        return True
    except (ValueError,PermissionError,OSError,audit.AuditError):
        st.session_state["_draft_save_error"] = True
        return False


def _discard_application():
    try:
        portal.discard_application_draft()
        st.session_state["_application_reset"] = True
        st.session_state.pop("_customer_request_preview",None)
        confirm_action("Draft discarded")
    except (ValueError,PermissionError,OSError,audit.AuditError):
        st.session_state["_draft_save_error"] = True


@st.dialog('Review your loan request')
def _request_preview():
    draft = st.session_state.get('_customer_request_preview')
    user = portal.require_role('customer')
    if not draft or draft['username'] != user.username:
        st.info(t('Enter your request details first.'))
        return
    for label, value in [('Customer', draft['name']), ('Phone', draft['phone']), ('Email', draft['email'] or 'Not provided'), ('Location', draft['location']), ('Product', draft['product']), ('Amount', cash(draft['amount'])), ('Term', f'{draft['term']} months'), ('Purpose', draft['purpose'])]:
        st.text(f'{label}: {value}')
    st.info(t(f'Estimate: {draft.get("rate", 10.0):.2f}% total flat interest · {cash(draft['interest'])} interest · {cash(draft['total'])} total repayment · {cash(draft['monthly'])} monthly · {cash(draft['final'])} final payment.'))
    confirm, edit = st.columns(2)
    if edit.button(t('Back to edit'), key='edit_request_preview'):
        st.session_state.pop('_customer_request_preview', None)
        st.rerun()
    if confirm.button(t('Confirm and submit'), type='primary', key='confirm_request_preview'):
        try:
            rid = portal.submit_request(draft['amount'], draft['term'], draft['product'], draft['purpose'], estimated_rate=draft['rate'])
            st.session_state.pop('_customer_request_preview', None)
            st.session_state['_application_reset'] = True
            confirm_action('Loan request submitted',f'{rid} · ' + t('Your request is saved and awaiting review. Download its receipt from My request history.'))
            st.rerun()
        except (ValueError, PermissionError, OSError, audit.AuditError) as exc:
            show_error(exc, 'submit the loan request')

def render():
    user = portal.require_role('customer')
    ui.page_header(t('My customer portal'), '', eyebrow=t('Credit Desk · Customer'))
    if st.button(t('Refresh my records'), key='i18n_views_customer_py_53'):
        st.rerun()
    notice = st.session_state.pop('_customer_request_notice', None)
    if notice:
        confirm_action('Request updated',notice)
    show_confirmation()
    profile = portal.profile()
    requests = portal.requests()
    loans = portal.my_loans()
    summaries = [(lid, portal.loan_details(lid)) for lid in loans['loan_id']] if not loans.empty else []
    balance = sum((details[1]['principal_balance'] for _, details in summaries))
    overdue = sum((float(details[2].loc[details[2]['payment_status'] == 'Overdue', 'amount_due'].sum()) for _, details in summaries if details[1]['status'] == 'Active'))
    future = [(row.due_date, float(row.amount_due)) for _, details in summaries if details[1]['status'] == 'Active' for row in details[2].itertuples() if row.amount_due >= 0.005 and row.due_date >= today_local().date()]
    upcoming = min(future) if future else None
    st.subheader(t('Loan overview'))
    first, second = st.columns(2)
    first.metric(t('Remaining principal'), cash(balance))
    second.metric(t('Overdue amount'), cash(overdue))
    third, fourth = st.columns(2)
    third.metric(t('Next payment'), cash(upcoming[1]) if upcoming else '—')
    if upcoming:
        third.caption(upcoming[0].strftime('%d/%m/%Y'))
    latest = requests.iloc[0] if not requests.empty else None
    fourth.metric(t('Latest request'), t(latest['status']) if latest is not None else '—')
    if latest is not None:
        fourth.caption(latest['request_id'])
    if not all(profile.get(field) for field in ('full_name','phone','location')):
        profile_completion(profile,compact=True)
    if not profile:
        st.info(t('Complete your profile to apply.'))
    st.subheader(t('Quick access'))
    quick = st.columns(3)
    if quick[0].button(t('Next payment'), key='shortcut_payment', **ui.STRETCH):
        st.session_state['customer_home_section'] = 'My loans & payments'
    if quick[1].button(t('Statements & receipts'), key='shortcut_statements', **ui.STRETCH):
        st.session_state['customer_home_section'] = 'My loans & payments'
    if quick[2].button(t('Contact support'), key='shortcut_support', **ui.STRETCH):
        destination = st.session_state.get('_customer_support_page')
        if destination is not None:
            st.switch_page(destination)
        else:
            st.info(t('Open Customer support from the sidebar.'))
    if not loans.empty:
        next_payments = []
        for loan_id in loans['loan_id']:
            _, summary, _, _ = portal.loan_details(loan_id)
            if summary['next_due']:
                next_payments.append((summary['next_due'], summary['next_amount'], loan_id))
        if next_payments:
            due, amount, reference = min(next_payments)
            label = 'Overdue payment' if due < today_local().date() else 'Next payment'
            alert = st.error if due < today_local().date() else st.info
            alert(f'{label}: {cash(amount)} · {due:%d/%m/%Y} · {reference}')
            days_left = (due - today_local().date()).days
            if 0 <= days_left <= 7:
                st.warning('Payment reminder: ' + ('your payment is due today.' if days_left == 0 else f'your payment is due in {days_left} day(s).') + ' View My loans & payments for details.')
    section = st.radio(t('View'), ['Loan requests', 'My loans & payments'], horizontal=True, key='customer_home_section', label_visibility='collapsed', format_func=t)
    if section == 'Loan requests':
        _load_application()
        requirements(profile)
        if st.session_state.pop('_draft_restored',False):
            st.info(t('Your unfinished application has been restored.'))
        if st.session_state.get('_draft_save_error'):
            st.error(t('Draft could not be saved. Keep this page open and try Save draft again.'))
        st.subheader(t('Loan cost estimate'))
        quote_cols = st.columns(3)
        estimate_amount = quote_cols[0].number_input(t('Loan amount ($)'), min_value=1.0, max_value=1000000000.0, value=10000.0, step=100.0, format='%.2f', key='quote_amount', on_change=_save_application)
        estimate_term = quote_cols[1].number_input(t('Term (months)'), min_value=1, max_value=360, value=10, key='quote_term', on_change=_save_application)
        estimate_rate = quote_cols[2].number_input(t('Interest rate (%)'), min_value=0.0, max_value=100.0, value=10.0, step=0.5, format='%.2f', key='quote_rate', on_change=_save_application, help=t('Total flat interest for the entire loan term. This is an estimate; staff approve the final rate.'))
        from decimal import Decimal, ROUND_HALF_UP
        estimate_interest = (Decimal(str(estimate_amount)) * Decimal(str(estimate_rate)) / Decimal('100')).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        estimate_total = Decimal(str(estimate_amount)) + estimate_interest
        estimate_monthly = (estimate_total / int(estimate_term)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        estimate_final = estimate_total - estimate_monthly * (int(estimate_term) - 1)
        quote = st.columns(3)
        quote[0].metric(t('Total interest') + f' · {estimate_rate:.2f}%', cash(estimate_interest))
        quote[1].metric(t('Monthly payment'), cash(estimate_monthly))
        quote[2].metric(t('Total repayment'), cash(estimate_total))
        if estimate_final != estimate_monthly:
            st.caption(t("Final payment") + f": {cash(estimate_final)}")
        st.subheader(t('Request a loan'))
        with st.container(border=True):
            amount, term = (float(estimate_amount), int(estimate_term))
            st.write(f'Requested amount: {cash(amount)} · Repayment term: {term} months')
            product = st.selectbox(t('Loan product'), loanbook.PRODUCTS, key='application_product', format_func=t, on_change=_save_application)
            purpose = st.text_area(t('What will you use the loan for?'), max_chars=2000, key='application_purpose', on_change=_save_application)
            acknowledge_terms = st.checkbox(t('I understand this is an estimate.'), key='i18n_views_customer_py_137')
            go = st.button(t('Preview loan request'), type='primary', disabled=not profile, key='i18n_views_customer_py_138')
        draft_actions = st.columns(2)
        if draft_actions[0].button(t("Save draft"),key="save_application_draft"):
            if _save_application():
                confirm_action("Draft saved","Your unfinished application is saved to your account.")
                st.rerun()
        draft_actions[1].button(t("Discard draft"),key="discard_application_draft",on_click=_discard_application)
        if st.session_state.get("_draft_saved_at"):
            st.caption(t("Draft saved") + " · " + to_local(st.session_state["_draft_saved_at"]))
        if go:
            try:
                if not acknowledge_terms:
                    raise ValueError('Review and acknowledge the loan cost estimate before submitting.')
                if not purpose.strip():
                    raise ValueError('Enter what you will use the loan for.')
                st.session_state['_customer_request_preview'] = dict(username=user.username, name=profile.get('full_name', user.display_name), phone=profile.get('phone', ''), email=profile.get('email', ''), location=profile.get('location', ''), amount=amount, term=term, product=product, purpose=purpose.strip(), rate=float(estimate_rate), interest=float(estimate_interest), total=float(estimate_total), monthly=float(estimate_monthly), final=float(estimate_final))
                _request_preview()
            except (ValueError, PermissionError, OSError, audit.AuditError) as exc:
                show_error(exc, 'submit the loan request')
        st.subheader(t('Loan request tracker'))
        tracker = st.columns(3)
        for column, status in zip(tracker, ['Pending review', 'Approved', 'Declined']):
            column.metric(status, int((requests['status'] == status).sum()))
        st.subheader(t('My request history'))
        request_query = st.text_input(t('Search requests'), placeholder=t('Reference, purpose or product'), key='customer_request_search')
        request_status = st.selectbox(t('Request status'), ['All', 'Pending review', 'Approved', 'Declined', 'Cancelled'], format_func=t, key='i18n_views_customer_py_160')
        shown_requests = customer_search.filter_records(requests, request_query, ('request_id', 'purpose', 'product'), request_status)
        if requests.empty:
            empty_state('requests')
        elif shown_requests.empty:
            st.info(t('No requests match these filters. Clear the search or choose All statuses.'))
        for r in shown_requests.itertuples():
            with st.expander(t(f'{r.request_id} · {cash(r.amount)} · {r.status}')):
                st.write(f'Requested: {to_local(r.submitted_at)} · {r.product} · {r.term_months} months')
                st.write(f'Purpose: {r.purpose}')
                destination = st.session_state.get('_customer_request_details_page')
                if destination is not None and st.button(t('View full request details'), key=f'open_request_{r.request_id}'):
                    st.session_state['_customer_detail_request'] = r.request_id
                    st.switch_page(destination)
                if r.status == 'Approved':
                    st.success('Approved · ' + ('Loan issued' if r.loan_id else 'Awaiting disbursement'))
                elif r.status == 'Declined':
                    st.error(t('Declined · Review the decision notes below.'))
                elif r.status == 'Cancelled':
                    st.info(t('Cancelled · This request will not be reviewed.'))
                else:
                    st.info(t('Pending review · Your request is waiting for the loan team.'))
                if r.status == 'Pending review':
                    if st.button(t('Cancel request'), key=f'cancel_request_{r.request_id}'):
                        try:
                            portal.cancel_request(r.request_id)
                            st.session_state['_customer_request_notice'] = 'Your loan request has been cancelled.'
                            st.rerun()
                        except (ValueError, PermissionError, OSError, audit.AuditError) as exc:
                            show_error(exc, 'cancel this request')
                elif r.status == 'Cancelled':
                    st.write(f'Cancelled: {to_local(r.cancelled_at)}')
                else:
                    st.write(f'Decision date: {to_local(r.decision_at)}')
                    st.write(f'Decision notes: {r.explanation}')
                if r.status == 'Approved':
                    st.write(f'Approved: {cash(r.approved_amount)} · {r.approved_term:.0f} months · {r.approved_rate:.2%} interest')
                    st.write(f'Loan reference: {r.loan_id}' if r.loan_id else 'Approved. Awaiting disbursement.')
                try:
                    st.download_button(t('Download request receipt (PDF)'), portal.request_receipt(r.request_id), file_name=f'Loan_Request_{r.request_id}.pdf', mime='application/pdf', key=f'request_receipt_{r.request_id}')
                except MissingLibrary:
                    st.info(t('PDF request receipts require reportlab.'))
                from views.request_terms import render as render_terms
                render_terms(r._asdict())
                request_documents.render(r.request_id, r.status)
    if section == 'My loans & payments':
        st.subheader(t('My loans'))
        if loans.empty:
            empty_state('loans')
        else:
            loan_query = st.text_input(t('Search loans'), placeholder=t('Loan reference or product'), key='customer_loan_search')
            loan_status = st.selectbox(t('Loan status'), ['All', 'Active', 'Closed', 'Written off'], format_func=t, key='i18n_views_customer_py_213')
            searchable_loans = loans.copy()
            searchable_loans['status'] = [portal.loan_details(lid)[1]['status'] for lid in loans['loan_id']]
            shown_loans = customer_search.filter_records(searchable_loans, loan_query, ('loan_id', 'product'), loan_status)
            if shown_loans.empty:
                st.info(t('No loans match these filters. Clear the search or choose All statuses.'))
                return
            lid = st.selectbox(t('Choose my loan'), shown_loans['loan_id'].tolist(), key='i18n_views_customer_py_220')
            loan, snap, schedule, payments = portal.loan_details(lid)
            destination = st.session_state.get('_customer_loan_details_page')
            if destination is not None and st.button(t('View full loan details'), key='open_loan_details'):
                st.session_state['_customer_detail_loan'] = lid
                st.switch_page(destination)
            c = st.columns(3)
            c[0].metric(t('Amount borrowed'), cash(loan['principal']))
            c[1].metric(t('Total paid'), cash(snap['paid']))
            c[2].metric(t('Remaining principal'), cash(snap['principal_balance']))
            paid_count = int((schedule['payment_status'] == 'Paid').sum())
            total_count = len(schedule)
            st.subheader(t('Loan cost summary'))
            cost = st.columns(3)
            flat = loan.get('interest_method') == 'flat_total'
            cost[0].metric('Total interest rate' if flat else 'Annual interest rate', f'{loan['annual_rate']:.2%}')
            cost[1].metric(t('Total scheduled interest'), cash(schedule['interest'].sum()))
            cost[2].metric(t('Total scheduled repayment'), cash(schedule['installment'].sum()))
            if total_count:
                st.caption(t("Final installment") + f": {cash(schedule["installment"].iloc[-1])}")
            status_cols = st.columns(3)
            for column, status in zip(status_cols, ['Paid', 'Upcoming', 'Overdue']):
                count = int((schedule['payment_status'] == status).sum())
                if status == 'Overdue' and count:
                    column.error(t(f'Overdue installments: {count}'))
                else:
                    column.metric(t(f'{status} installments'), count)
            st.subheader(t('Loan progress'))
            st.progress(paid_count / total_count if total_count else 0, text=t(f'{paid_count} of {total_count} installments paid'))
            st.caption(f'{total_count - paid_count} installments remaining · {paid_count / total_count:.0%} complete' if total_count else 'No scheduled installments.')
            principal_col, interest_col = st.columns(2)
            principal_col.metric(t('Principal repaid'), cash(snap['principal_paid']))
            interest_col.metric(t('Interest paid'), cash(snap['interest_paid']))
            if snap['unallocated_paid'] > 0.01:
                st.info(t(f'Unapplied payment credit: {cash(snap['unallocated_paid'])}. Contact the loan team for allocation.'))
            rate_label = 'total interest over the loan term' if flat else 'annual interest'
            st.write(f'Status: {snap['status']} · {loan['product']} · {loan['annual_rate']:.2%} {rate_label}')
            st.write(f'Disbursed: {to_local(loan['disbursed_on'], '%d/%m/%Y')} · First payment: {to_local(loan['first_due_on'], '%d/%m/%Y')} · Original term: {loan['term_months']} months')
            if snap['next_due']:
                overdue = snap['next_due'] < today_local().date()
                alert = st.error if overdue else st.info
                label = 'Overdue payment' if overdue else 'Next payment'
                alert(f'{label}: {cash(snap['next_amount'])} · due {snap['next_due']:%d/%m/%Y}')
            if snap['arrears'] > 0.01 and snap['status'] == 'Active':
                overdue_amount = float(schedule.loc[schedule['payment_status'] == 'Overdue', 'amount_due'].sum())
                if overdue_amount > 0.005:
                    st.error(t(f'Overdue amount: {cash(overdue_amount)}. Please contact the loan team.'))
                else:
                    st.info(t(f'Amount due today: {cash(snap['arrears'])}'))
            try:
                statement = portal.loan_statement(lid)
                st.download_button(t('Download loan statement (PDF)'), statement, file_name=f'Loan_Statement_{lid}_{today_local():%Y%m%d}.pdf', mime='application/pdf', key=f'statement_{lid}')
            except MissingLibrary:
                st.info(t('PDF statements require reportlab. Restart using START Credit Desk to install it.'))
            from views import customer_payments
            customer_payments.render_customer(lid, loan, snap)
            st.subheader(t('Payment history'))
            if payments.empty:
                empty_state('payments')
            else:
                _payment_history(lid, payments)
            from views.loan_details import payment_calendar
            payment_calendar(schedule, lid, key='portal_calendar')
            st.subheader(t('Repayment schedule'))
            try:
                st.download_button(t("Download repayment schedule (PDF)"),portal.repayment_schedule_pdf(lid),
                    file_name=f"Repayment_Schedule_{lid}.pdf",mime="application/pdf",key=f"schedule_download_{lid}")
            except MissingLibrary:
                st.info(t("PDF downloads require reportlab."))
            displayed_schedule = schedule[['no', 'due_date', 'installment', 'paid', 'amount_due', 'payment_status']].copy()
            displayed_schedule['due_date'] = displayed_schedule['due_date'].map(lambda d: d.strftime('%d/%m/%Y'))
            phone_schedule = pd.DataFrame({'Payment #': schedule['no'], 'Due date': displayed_schedule['due_date'], 'Scheduled ($)': schedule['installment'].map(cash), 'Paid ($)': schedule['paid'].map(cash), 'Remaining ($)': schedule['amount_due'].map(cash), 'Status': schedule['payment_status']})
            _phone_cards(phone_schedule)
            st.dataframe(displayed_schedule.rename(columns={'no': 'Payment #', 'due_date': 'Due date', 'installment': 'Scheduled ($)', 'paid': 'Paid ($)', 'amount_due': 'Remaining ($)', 'payment_status': 'Status'}).style.apply(lambda row: ['background-color: #FEE2E2; color: #991B1B; font-weight: 600;' if row['Status'] == 'Overdue' else '' for _ in row], axis=1), column_config={col: st.column_config.NumberColumn(format='$%.2f') for col in ['Scheduled ($)', 'Paid ($)', 'Remaining ($)']}, hide_index=True, **ui.STRETCH)

def _phone_cards(frame):
    from html import escape
    cards = []
    for _, row in frame.iterrows():
        entries = ''.join((f'<div><span>{escape(t(str(label)))}</span><strong>{escape(t(str(value)))}</strong></div>' for label, value in row.items()))
        cards.append('<article class="cd-phone-card">' + entries + '</article>')
    st.markdown('<div class="cd-phone-cards">' + ''.join(cards) + '</div>', unsafe_allow_html=True)

def _payment_history(lid, payments):
    query = st.text_input(t('Search payments'), placeholder=t('Receipt reference, date or amount'), key=f'payment_search_{lid}')
    days = pd.to_datetime(payments['event_date']).dt.date
    date_filter = st.radio(t('Payment dates'), ['All dates', 'Choose dates'], horizontal=True, key=f'payment_date_mode_{lid}', format_func=t)
    dates = None
    if date_filter == 'Choose dates':
        start_col, end_col = st.columns(2)
        start = start_col.date_input(t('From'), value=days.min(), key=f'payment_from_{lid}', format='DD/MM/YYYY')
        end = end_col.date_input(t('To'), value=days.max(), key=f'payment_to_{lid}', format='DD/MM/YYYY')
        if start > end:
            st.error(t('The From date must be on or before the To date.'))
            return
        dates = (start, end)
    searchable = payments.copy()
    searchable['receipt'] = [f'PAY-{int(i):08d}' for i in payments['id']]
    searchable['display_date'] = searchable['event_date'].map(lambda d: to_local(d, '%d/%m/%Y'))
    shown = customer_search.filter_records(searchable, query, ('receipt', 'event_date', 'display_date', 'amount'), date_column='event_date', dates=dates)
    st.caption(f"{len(shown)} / {len(payments)} " + t("payments"))
    if shown.empty:
        st.info(t('No payments match these filters. Clear the search or widen the date range.'))
        return
    history = shown.drop(columns=['id', 'receipt', 'display_date']).rename(columns={'event_date': 'Payment date', 'amount': 'Amount ($)', 'principal_paid': 'Principal ($)', 'interest_paid': 'Interest ($)', 'unallocated': 'Unapplied ($)'})
    history['Payment date'] = history['Payment date'].map(lambda d: to_local(d, '%d/%m/%Y'))
    if not (shown['unallocated'] > 0.01).any():
        history = history.drop(columns='Unapplied ($)')
    phone_history = history.copy()
    for column in phone_history.columns:
        if column != 'Payment date':
            phone_history[column] = phone_history[column].map(cash)
    _phone_cards(phone_history)
    st.dataframe(history, column_config={col: st.column_config.NumberColumn(format='$%.2f') for col in history.columns if col != 'Payment date'}, hide_index=True, **ui.STRETCH)
    st.subheader(t('Payment receipts'))
    options = {int(p.id): f'{to_local(p.event_date, '%d/%m/%Y')} · {cash(p.amount)} · PAY-{int(p.id):08d}' for p in shown.itertuples()}
    payment_id = st.selectbox(t('Choose a payment receipt'), list(options), format_func=options.get, key=f'receipt_payment_{lid}')
    try:
        receipt = portal.payment_receipt(lid, payment_id)
        st.download_button(t('Download receipt (PDF)'), receipt, file_name=f'Receipt_{lid}_PAY-{payment_id:08d}.pdf', mime='application/pdf', key=f'receipt_download_{lid}_{payment_id}')
    except MissingLibrary:
        st.info(t('PDF receipts require reportlab. Restart using START Credit Desk to install it.'))

@st.dialog('Profile photo')
def _view_profile_photo(image):
    st.image(image, **ui.STRETCH)

def render_profile():
    user = portal.require_role('customer', *portal.STAFF)
    profile = portal.profile()
    ui.page_header(t('My profile'), '', eyebrow='Credit Desk · ' + user.role_label)
    if st.session_state.pop('_customer_profile_saved', False):
        confirm_action('Profile saved','Your name, contact details and selected photo have been saved.')
    show_confirmation()
    profile_completion(profile)
    if not st.session_state.get('_customer_unified_profile_form'):
        previous_upload = st.session_state.get('_customer_photo_upload')
        if previous_upload is not None:
            st.session_state['_customer_photo_draft'] = previous_upload.getvalue()
        st.session_state['_customer_unified_profile_form'] = True
    current_photo = portal.profile_photo()
    st.markdown('<style>\n        .st-key-customer_photo_preview { position: relative; width: 180px; max-width: 100%; }\n        .st-key-customer_photo_preview [data-testid="stElementContainer"]:has(button) {\n            position: absolute; inset: 0; z-index: 2; width: 100%; height: 100%;\n        }\n        .st-key-customer_photo_preview button {\n            width: 100% !important; height: 100% !important; position: absolute; inset: 0;\n            border: none !important; background: transparent !important;\n            color: transparent !important; box-shadow: none !important; cursor: zoom-in;\n        }\n        .st-key-customer_photo_preview button * { color: transparent !important; }\n        .st-key-customer_photo_preview button:focus-visible {\n            outline: 3px solid #0B6B62; outline-offset: 3px;\n        }\n        [data-testid="stFileUploader"] [data-testid="stWidgetLabel"],\n        [data-testid="stFileUploader"] [data-testid="stFileChip"],\n        [data-testid="stFileUploader"] [data-testid="stFileUploaderFile"],\n        [data-testid="stFileUploaderDropzoneInstructions"],\n        [data-testid="stFileUploaderDropzone"] small { display: none !important; }\n        [data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"] {\n            border: none !important; background: transparent !important;\n            padding: 0 !important; min-height: 0 !important;\n        }\n        [data-testid="stFileUploaderDropzone"] button {\n            width: auto !important; height: auto !important; min-height: 38px;\n            padding: .45rem .8rem !important; border: 1px solid #CBD5E1 !important;\n            border-radius: 6px !important; background: white !important; color: #07453F !important;\n        }\n        [data-testid="stFileUploaderDropzone"] button > * { display: none !important; }\n        [data-testid="stFileUploaderDropzone"] button::after {\n            content: \'Change photo\'; font-size: .85rem; font-weight: 500;\n        }\n    </style>', unsafe_allow_html=True)
    draft_photo = st.session_state.get('_customer_photo_draft')
    if draft_photo:
        try:
            current_photo = portal.prepare_photo(draft_photo)
        except ValueError:
            st.session_state.pop('_customer_photo_draft', None)
            draft_photo = None
    view_photo = False
    with st.form('customer_profile'):
        photo, details = st.columns([1, 3])
        with photo:
            if current_photo:
                with st.container(key='customer_photo_preview'):
                    st.image(current_photo, width=180)
                    view_photo = st.form_submit_button(t('View profile photo'), help=t('Click to view photo'), key='i18n_views_customer_py_441')
            else:
                st.markdown('<div style="border:2px dashed #94a3b8;border-radius:50%;width:160px;height:160px;display:flex;align-items:center;justify-content:center;color:#64748b">No photo yet</div>', unsafe_allow_html=True)
            upload_options = {'max_upload_size': 5} if 'max_upload_size' in inspect.signature(st.file_uploader).parameters else {}
            uploaded = st.file_uploader(t('Profile photo'), type=['jpg', 'jpeg', 'png', 'webp'], key='_customer_photo_upload', label_visibility='collapsed', **upload_options)
        with details:
            name = st.text_input(t('Full name'), value=profile.get('full_name', user.display_name), max_chars=120, key='i18n_views_customer_py_450')
            phone = st.text_input(t('Phone number'), value=profile.get('phone', ''), max_chars=60, key='i18n_views_customer_py_451')
            email = st.text_input(t('Email (optional)'), value=profile.get('email', ''), max_chars=200, key='i18n_views_customer_py_452')
            location = st.text_area(t('Location / address'), value=profile.get('location', ''), max_chars=300, help=t('Province or city, district and address.'), key='i18n_views_customer_py_453')
        save = st.form_submit_button(t('Save my profile'), type='primary', key='i18n_views_customer_py_455')
    if view_photo and current_photo:
        _view_profile_photo(current_photo)
    if save:
        try:
            portal.save_profile(name, phone, email, location, photo=uploaded.getvalue() if uploaded is not None else draft_photo)
            st.session_state.pop('_customer_photo_draft', None)
            st.session_state['_customer_profile_saved'] = True
            st.rerun()
        except (ValueError, PermissionError, OSError, audit.AuditError) as exc:
            show_error(exc, 'save your profile')
    if profile:
        st.caption(t(f'Profile updated: {to_local(profile['updated_at'])}'))

def notification_bell(notices, destination):
    unread = sum((n['unread'] for n in notices))
    badge = str(unread) if unread < 100 else '99+'
    st.markdown('<style>\n        .st-key-customer_notification_bell {\n            position: fixed; top: 22px; right: 30px; width: 46px; z-index: 2147483000;\n        }\n        .st-key-customer_notification_bell button {\n            width: 46px !important; height: 46px !important; min-height: 46px;\n            border-radius: 50% !important; padding: 0 !important; border: 1px solid #CBD5E1;\n            background: #FFFFFF; color: #07453F; box-shadow: 0 2px 8px #0F172A12;\n            display: flex; align-items: center; justify-content: center; position: relative;\n        }\n        .st-key-customer_notification_bell button p { font-size: 0; }\n        .st-key-customer_notification_bell button [data-testid="stIconMaterial"] { display: none !important; }\n        .st-key-customer_notification_bell button::before {\n            content: \'\'; width: 25px; height: 25px; flex: 0 0 25px;\n            position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);\n            background: center / contain no-repeat url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 24 24\' fill=\'none\' stroke=\'%2307453F\' stroke-width=\'1.8\' stroke-linecap=\'round\' stroke-linejoin=\'round\'%3E%3Cpath d=\'M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4M12 2V1\'/%3E%3C/svg%3E");\n        }\n        .st-key-customer_notification_bell button:focus-visible {\n            outline: 3px solid #0D9488; outline-offset: 3px;\n        }\n        .st-key-customer_notification_bell::after {\n            position: absolute; top: -6px; right: -6px; pointer-events: none;\n            background: #DC2626; color: white; border: 2px solid white;\n            border-radius: 99px; min-width: 22px; height: 22px; padding: 0 4px;\n            display: flex; align-items: center; justify-content: center;\n            font: 700 12px/1 sans-serif;\n        }\n        @media(max-width: 600px) {\n            .st-key-customer_notification_bell { top: 14px; right: 18px; }\n        }\n    </style>' + f"<style>.st-key-customer_notification_bell::after {{content: '{badge}'; display: {('flex' if unread else 'none')}; }}</style>", unsafe_allow_html=True)
    if st.button(t(f'Notifications ({unread} unread)'), icon=':material/notifications:', key='customer_notification_bell', help=t(f'Notifications · {unread} unread')):
        st.switch_page(destination)

def render_notifications():
    user = portal.require_role('customer')
    ui.page_header(t('Notifications'), '', eyebrow=t('Credit Desk · Customer'))
    snapshot = st.session_state.get("_customer_notifications_snapshot",{})
    notices = snapshot["items"] if snapshot.get("username") == user.username else portal.my_notifications()
    if st.button(t('Refresh notifications'), key='i18n_views_customer_py_517'):
        st.rerun()
    if not notices:
        empty_state('notifications')
    for n in notices:
        with st.container(border=True):
            st.subheader(t(n['title']))
            getattr(st, n['tone'])(n['body'])
            st.caption(to_local(n['ts']))
            if n['id'].startswith('draft:'):
                if st.button(t('Resume application'),key=f"notification_resume_{n['id']}"):
                    st.session_state['customer_home_section']='Loan requests'
                    st.session_state['_application_reset']=True
                    destination=st.session_state.get('_customer_home_page')
                    if destination is not None:
                        st.switch_page(destination)
            elif n['id'].startswith('support:'):
                if st.button(t('Open messages'),key=f"notification_open_{n['id']}"):
                    destination=st.session_state.get('_customer_support_page')
                    if destination is not None:
                        st.switch_page(destination)
            elif n['id'].startswith('due:') and n['tone']=='error':
                if st.button(t('Discuss this payment'),key=f"notification_discuss_{n['id']}"):
                    st.session_state['_customer_message_action']=n['id'].split(':')[1]
                    destination=st.session_state.get('_customer_support_page')
                    if destination is not None:
                        st.switch_page(destination)
