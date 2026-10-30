"""Owned loan details and an accessible monthly repayment calendar."""
from __future__ import annotations
from src.customer_i18n import t
import calendar
from html import escape
import pandas as pd
import streamlit as st
from src import customer_portal as portal, ui
from src.data_pipeline import today_local, to_local
from src.deps import MissingLibrary

def cash(value):
    return f'${float(value):,.2f}'

def payment_calendar(schedule, loan_id, key='loan_calendar'):
    st.subheader(t('Payment calendar'))
    if schedule.empty:
        st.info(t('No scheduled payments.'))
        return
    filters = st.columns(2)
    status_filter = filters[0].selectbox(t("Payment status"),["All","Paid","Overdue","Upcoming"],
        format_func=t,key=f"{key}_status_{loan_id}")
    query = filters[1].text_input(t("Search installments"),placeholder=t("Date, installment number or amount"),
                                key=f"{key}_search_{loan_id}").strip().casefold()
    matching = schedule.copy()
    if status_filter != "All":
        matching = matching[matching["payment_status"] == status_filter]
    if query and not matching.empty:
        def matches(row):
            values = [str(row["no"]),row["due_date"].strftime("%d/%m/%Y"),str(row["payment_status"]),t(row["payment_status"])]
            values += [cash(row[column]) for column in ("installment","paid","amount_due")]
            values += [f"{row[column]:.2f}" for column in ("installment","paid","amount_due")]
            return any(query in value.casefold() for value in values)
        matching = matching[matching.apply(matches,axis=1).astype(bool)]
    st.caption(t("Matching installments") + f": {len(matching)} / {len(schedule)}")
    if matching.empty:
        st.info(t("No installments match. Choose All statuses or clear the search."))
        return
    months = sorted({(day.year,day.month) for day in matching["due_date"]})
    current = (today_local().year,today_local().month)
    default = months.index(current) if current in months else 0
    month_key = f"{key}_{loan_id}"
    if month_key in st.session_state and st.session_state[month_key] not in months:
        del st.session_state[month_key]
    year,month = st.selectbox(t("Calendar month"),months,index=default,
        format_func=lambda value: f"{t(calendar.month_name[value[1]])} {value[0]}",key=month_key)
    selected = matching[matching["due_date"].map(lambda day: day.year == year and day.month == month)]
    by_day = {row.due_date.day:row for row in selected.itertuples()}
    colors = {'Paid': ('#DCFCE7', '#166534'), 'Overdue': ('#FEE2E2', '#991B1B'), 'Upcoming': ('#DBEAFE', '#1E40AF')}
    cells = ['<div class="cd-cal-label">' + t(day) + '</div>' for day in ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']]
    for week in calendar.Calendar(firstweekday=0).monthdayscalendar(year, month):
        for day in week:
            if not day:
                cells.append('<div class="cd-cal-day cd-cal-empty"></div>')
                continue
            item = by_day.get(day)
            style, extra, title = ('', '', str(day))
            if item is not None:
                background, foreground = colors[item.payment_status]
                style = f'background:{background};color:{foreground};border-color:{foreground};'
                label = f'{item.payment_status}: {cash(item.paid if item.payment_status == 'Paid' else item.amount_due)}'
                extra = '<span class="cd-cal-status">' + escape(t(item.payment_status)) + '</span>'
                title = f'{day}/{month}/{year} · {label}'
            if (year, month, day) == (today_local().year, today_local().month, today_local().day):
                extra += '<span class="cd-cal-today">Today</span>'
            cells.append(f'<div class="cd-cal-day" style="{style}" title="{escape(title, quote=True)}"><strong>{day}</strong>{extra}</div>')
    st.markdown('<style>\n      .cd-calendar {display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:5px;margin:12px 0;}\n      .cd-cal-label {text-align:center;font-size:.8rem;color:#64748B;}\n      .cd-cal-day {min-height:70px;padding:8px;border:1px solid #CBD5E1;border-radius:7px;background:white;}\n      .cd-cal-status,.cd-cal-today {display:block;font-size:.75rem;overflow-wrap:anywhere;}\n      .cd-cal-empty {background:transparent;border-color:transparent;}\n      @media(max-width:600px){.cd-cal-day{min-height:58px;padding:4px}.cd-cal-status{font-size:.6rem}}\n    </style><div class="cd-calendar">' + ''.join(cells) + '</div>', unsafe_allow_html=True)
    st.html("""<style>
      .cd-payment-summary {background:#FFFFFF;border:1px solid #E2E8F0;border-left:4px solid var(--payment-color);
        border-radius:12px;padding:20px;margin:12px 0;font-family:inherit;}
      .cd-payment-heading {display:flex;justify-content:space-between;align-items:flex-start;gap:16px;}
      .cd-payment-title {font-size:16px;font-weight:650;color:#1E293B;margin:0;}
      .cd-payment-date {font-size:13px;color:#64748B;margin-top:5px;}
      .cd-payment-badge {border-radius:999px;padding:5px 11px;background:var(--payment-tint);
        color:var(--payment-color);font-size:12px;font-weight:650;white-space:nowrap;}
      .cd-payment-amounts {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;
        border-top:1px solid #F1F5F9;padding-top:16px;margin-top:16px;}
      .cd-payment-amounts span {display:block;font-size:12px;color:#64748B;margin-bottom:5px;}
      .cd-payment-amounts strong {font-size:19px;font-weight:650;color:#334155;font-variant-numeric:tabular-nums;}
      .cd-payment-amounts .cd-payment-balance {color:var(--payment-color);}
      @media(max-width:640px){.cd-payment-summary{padding:16px}.cd-payment-amounts{grid-template-columns:1fr;gap:12px;}
        .cd-payment-amounts>div{display:flex;justify-content:space-between;align-items:center;gap:12px;}
        .cd-payment-amounts span{margin:0}.cd-payment-amounts strong{font-size:18px;}}
    </style>""")
    for row in selected.itertuples():
        tint, color = colors[row.payment_status]
        title = escape(t("Installment") + " " + str(row.no))
        due = escape(t("Due date") + ": " + row.due_date.strftime("%d/%m/%Y"))
        status = escape(t(row.payment_status))
        fields = [(t("Scheduled payment"), cash(row.installment), ""),
                  (t("Amount paid"), cash(row.paid), ""),
                  (t("Amount overdue") if row.payment_status == "Overdue" else t("Amount remaining"),
                   cash(row.amount_due), "cd-payment-balance")]
        amounts = "".join('<div><span>' + escape(label) + '</span><strong class="' + cls + '">'
                          + escape(value) + '</strong></div>' for label,value,cls in fields)
        st.html(f'<article class="cd-payment-summary" style="--payment-color:{color};--payment-tint:{tint}">'
                f'<div class="cd-payment-heading"><div><h3 class="cd-payment-title">{title}</h3>'
                f'<div class="cd-payment-date">{due}</div></div><span class="cd-payment-badge">{status}</span></div>'
                f'<div class="cd-payment-amounts">{amounts}</div></article>')


def render():
    portal.require_role('customer')
    ui.page_header(t('Loan details'), '', eyebrow=t('Credit Desk · Customer'))
    loans = portal.my_loans()
    if loans.empty:
        from views.customer_help import empty_state
        empty_state('loans')
        return
    choices = loans['loan_id'].tolist()
    preferred = st.session_state.pop('_customer_detail_loan', None)
    if preferred in choices:
        st.session_state['customer_details_choice'] = preferred
    lid = st.selectbox(t('Loan reference'), choices, key='customer_details_choice')
    loan, snap, schedule, payments = portal.loan_details(lid)
    flat = loan.get('interest_method') == 'flat_total'
    top = st.columns(3)
    top[0].metric(t('Amount borrowed'), cash(loan['principal']))
    top[1].metric(t('Total paid'), cash(snap['paid']))
    top[2].metric(t('Remaining principal'), cash(snap['principal_balance']))
    paid_count = int((schedule['payment_status'] == 'Paid').sum())
    st.progress(paid_count / len(schedule) if len(schedule) else 0, text=t(f'{paid_count} of {len(schedule)} installments paid'))
    with st.container(border=True):
        st.subheader(t('Terms and important dates'))
        facts = [('Loan reference', lid), ('Product', loan['product']), ('Status', snap['status']), ('Interest rate', f'{loan['annual_rate']:.2%} ' + ('total flat interest over the full term' if flat else 'annual interest on remaining principal')), ('Repayment term', f'{loan['term_months']} months'), ('Disbursed', to_local(loan['disbursed_on'], '%d/%m/%Y')), ('First installment due', to_local(loan['first_due_on'], '%d/%m/%Y')), ('Final installment due', schedule['due_date'].iloc[-1].strftime('%d/%m/%Y') if len(schedule) else 'Not available'), ('Regular installment', cash(schedule['installment'].iloc[0]) if len(schedule) else cash(0)), ('Final installment', cash(schedule['installment'].iloc[-1]) if len(schedule) else cash(0)), ('Total scheduled interest', cash(schedule['interest'].sum())), ('Total scheduled repayment', cash(schedule['installment'].sum())), ('Remaining scheduled repayment', cash(schedule['amount_due'].sum()))]
        for label, value in facts:
            st.text(f'{label}: {value}')
    if snap['next_due']:
        message = f'{cash(snap['next_amount'])} due {snap['next_due']:%d/%m/%Y}'
        if snap['next_due'] < today_local().date():
            st.error('Overdue installment: ' + message)
            if st.button(t("Discuss this payment"),key="loan_details_discuss_payment"):
                st.session_state["_customer_message_action"]=lid
                destination=st.session_state.get("_customer_support_page")
                if destination is not None:
                    st.switch_page(destination)
        else:
            st.info('Next installment: ' + message)
    try:
        st.download_button(t('Download loan statement (PDF)'), portal.loan_statement(lid), file_name=f'Loan_Statement_{lid}_{today_local():%Y%m%d}.pdf', mime='application/pdf', key='details_statement')
    except MissingLibrary:
        st.info(t('PDF statements require reportlab.'))
    try:
        st.download_button(t("Download repayment schedule (PDF)"),portal.repayment_schedule_pdf(lid),
            file_name=f"Repayment_Schedule_{lid}.pdf",mime="application/pdf",key="details_schedule_download")
    except MissingLibrary:
        st.info(t("PDF downloads require reportlab."))
    payment_calendar(schedule, lid, key='details_calendar')
