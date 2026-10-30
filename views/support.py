"""Customer support and staff inbox; both share the same private conversation."""
from __future__ import annotations
from src.customer_i18n import t
import streamlit as st
import pandas as pd
from src import audit, customer_portal as portal, customer_support as support, ui
from src.data_pipeline import to_local
from views._customer_feedback import show_error

def _loan_reference(value):
    # Pandas may return NaN for SQL NULL; NaN is truthy but is not a reference.
    return value.strip() if isinstance(value,str) and value.strip() else None


def _profile_avatar(identity):
    if identity.get('photo'):
        return identity['photo']
    import io
    from PIL import Image, ImageDraw, ImageFont
    initials = ''.join((word[0] for word in identity['name'].split()[:2])).upper() or 'U'
    image = Image.new('RGBA', (96, 96), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((3, 3, 92, 92), fill='#D3F4EC', outline='#87DACA', width=4)
    font = ImageFont.load_default(size=30)
    draw.text((48, 48), initials, font=font, fill='#07453F', anchor='mm')
    output = io.BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()

def _chat_styles():
    st.html("""<style>
      .st-key-support_shell{max-width:960px;margin:0 auto;}
      .cd-chat-header{display:flex;align-items:center;gap:12px;padding:16px 18px;background:#FFF;
        border:1px solid #E2E8F0;border-radius:14px 14px 0 0;}
      .cd-support-symbol{width:40px;height:40px;border-radius:50%;background:#D3F4EC;color:#07453F;
        display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px;flex-shrink:0;}
      .cd-chat-heading{flex:1;min-width:0;}.cd-chat-heading strong{display:block;color:#1E293B;font-size:15px;}
      .cd-chat-heading small{display:block;color:#64748B;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:70vw;}
      .cd-chat-state{background:#F1F5F9;color:#475569;border-radius:99px;padding:4px 10px;font-size:12px;}
      .cd-chat-scroll{display:flex;flex-direction:column-reverse;overflow-y:auto;overscroll-behavior:contain;
        height:420px;max-height:55dvh;min-height:260px;background:#F8FAFC;border:1px solid #E2E8F0;
        border-top:0;border-radius:0 0 14px 14px;scrollbar-width:thin;}
      .cd-chat-feed{display:flex;flex-direction:column;gap:14px;padding:20px 16px;}
      .cd-chat-day{align-self:center;font-size:11px;color:#64748B;background:#E2E8F080;border-radius:99px;padding:4px 10px;margin:4px 0;}
      .cd-chat-row{display:flex;gap:8px;align-items:flex-end;max-width:85%;align-self:flex-start;}
      .cd-chat-row.mine{align-self:flex-end;flex-direction:row-reverse;}
      .cd-chat-avatar{height:32px;width:32px;border-radius:50%;object-fit:cover;flex-shrink:0;}
      .cd-chat-bot{height:32px;width:32px;border-radius:50%;background:#E2E8F0;color:#475569;display:flex;
        align-items:center;justify-content:center;font-size:10px;font-weight:700;flex-shrink:0;}
      .cd-chat-bubble{background:#FFF;border:1px solid #E2E8F0;border-radius:14px 14px 14px 4px;padding:10px 13px;min-width:90px;}
      .mine .cd-chat-bubble{background:#E0F2ED;border-color:#C5E5DB;border-radius:14px 14px 4px 14px;}
      .cd-chat-sender{font-size:11px;font-weight:600;color:#64748B;margin-bottom:4px;}
      .cd-chat-body{color:#1E293B;font-size:14px;line-height:1.65;white-space:pre-wrap;overflow-wrap:anywhere;}
      .cd-chat-time{font-size:10px;color:#94A3B8;text-align:right;margin-top:5px;}
      .cd-chat-expiry{color:#94A3B8;font-size:11px;text-align:right;padding:5px 2px;}
      .st-key-support_shell [data-testid="stChatInput"]{border:1px solid #CBD5E1;border-radius:12px;}
      .cd-chat-welcome{min-height:240px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;
        border:1px solid #E2E8F0;border-radius:14px;background:white;padding:24px;color:#64748B;text-align:center;}
      .cd-chat-welcome strong{font-size:18px;color:#1E293B;}
      @media(max-width:640px){.cd-chat-feed{padding:14px 10px}.cd-chat-row{max-width:95%}.cd-chat-header{padding:12px;}
        .cd-chat-scroll{height:50dvh;max-height:50dvh}.cd-chat-body{font-size:14px}.cd-chat-avatar,.cd-chat-bot{width:28px;height:28px}}
    </style>""")


def _message_bubbles(messages,identities):
    import base64
    from html import escape
    from src import auth
    current=auth.current_user()
    parts=[]
    previous_day=None
    for message in messages.itertuples():
        day=to_local(message.sent_at,"%d/%m/%Y")
        if day!=previous_day:
            parts.append('<div class="cd-chat-day">'+escape(day)+'</div>')
            previous_day=day
        mine=message.sender==current.username and message.role!='bot'
        identity=identities.get(message.sender,{"name":"Support team","photo":None})
        if message.role=='bot':
            avatar='<div class="cd-chat-bot" aria-label="Support bot">CD</div>'
            name=t("Automatic reply")
            body=t(message.body)
        else:
            photo=_profile_avatar(identity)
            mime="jpeg" if photo.startswith(b"\xff\xd8") else "png"
            encoded=base64.b64encode(photo).decode("ascii")
            avatar=f'<img class="cd-chat-avatar" src="data:image/{mime};base64,{encoded}" alt="{escape(identity["name"],quote=True)}">'
            name=t("You") if mine else identity["name"]
            body=t(message.body) if message.body=="Message withdrawn" else message.body
        parts.append('<div class="cd-chat-row'+(' mine' if mine else '')+'">'+avatar+
            '<div class="cd-chat-bubble"><div class="cd-chat-sender">'+escape(name)+'</div>'+
            '<div class="cd-chat-body">'+escape(body)+'</div><div class="cd-chat-time">'+
            escape(to_local(message.sent_at,"%H:%M"))+(" · "+escape(t(message.delivery)) if mine and message.role=="customer" else "")+'</div></div></div>')
    st.html('<div class="cd-chat-scroll"><div class="cd-chat-feed">'+''.join(parts)+'</div></div>')


@st.fragment(run_every='5s')
def _conversation(ticket, staff=False):
    tid = ticket['ticket_id']
    _chat_styles()
    try:
        messages = support.messages(tid)
        identities = support.chat_profiles(tid)
    except PermissionError:
        st.info(t('This chat has expired. Start a new chat to contact support.'))
        if st.button(t('Back to conversations'), key=f'expired_chat_{tid}'):
            st.rerun()
        return
    from html import escape
    title=(ticket.get('full_name') or ticket['username']) if staff else t('Support team')
    st.html('<div class="cd-chat-header"><div class="cd-support-symbol">CD</div><div class="cd-chat-heading">'
        '<strong>'+escape(title)+'</strong><small title="'+escape(ticket['subject'],quote=True)+'">'+escape(ticket['subject'])+
        '</small></div><span class="cd-chat-state">'+escape(t(ticket['status']))+'</span></div>')
    loan_reference = _loan_reference(ticket.get("loan_id"))
    if loan_reference:
        st.caption(t("Loan reference") + ": " + loan_reference)
    _message_bubbles(messages,identities)
    if not messages.empty:
        expires=pd.to_datetime(messages['sent_at'],utc=True).max()+pd.Timedelta(hours=24)
        left=max(0,int((expires-pd.Timestamp.now(tz='UTC')).total_seconds()//60))
        st.html('<div class="cd-chat-expiry">'+escape(t('Chat expires in'))+f' {left//60}h {left%60}m</div>')
        support.mark_read(tid,int(messages['id'].max()))
    message = st.chat_input(t('Type your message…'), key=f'support_chat_{tid}', max_chars=5000)
    if message:
        try:
            support.reply(tid, message)
            st.rerun()
        except (ValueError, PermissionError, OSError, audit.AuditError) as exc:
            show_error(exc, 'send your message')
    if staff:
        status = 'Resolved' if ticket['status'] == 'Open' else 'Open'
        if st.button('Mark resolved' if status == 'Resolved' else 'Reopen conversation', key=f'support_status_{tid}'):
            support.set_status(tid, status)
            st.rerun()
    elif ticket['status'] == 'Resolved':
        st.caption(t('This conversation is resolved. Sending another reply reopens it.'))

def _notice():
    notice = st.session_state.pop('_support_notice', None)
    if notice:
        st.success(notice)
    if st.button(t('Refresh conversations'), key='i18n_views_support_py_80'):
        st.rerun()

def render_customer():
    portal.require_role('customer')
    _chat_styles()
    with st.container(key="support_shell"):
        ui.page_header(t('Messages'),'',eyebrow=t('Credit Desk · Customer'))
        _customer_chat()


def _customer_chat():
    tickets=support.tickets()
    rows={row['ticket_id']:row for row in tickets.to_dict('records')}
    selected=st.session_state.pop('_support_open_chat',None)
    action=st.session_state.pop('_customer_message_action',None)
    if selected in rows:
        st.session_state['_customer_active_chat']=selected
    if action:
        owned=portal.my_loans()
        if not owned.empty and action in owned['loan_id'].tolist():
            existing=next((rid for rid,row in rows.items() if row['loan_id']==action and row['status']=='Open'),None)
            st.session_state['_customer_active_chat']=existing or 'new'
            st.session_state['chat_related_loan']=action
    active=st.session_state.get('_customer_active_chat')
    if active not in rows and active!='new':
        active=None
        st.session_state['_customer_active_chat']=None
    if active:
        if st.button(t('Back to inbox'),key='back_message_inbox'):
            st.session_state['_customer_active_chat']=None
            st.rerun()
        if active in rows:
            _conversation(rows[active])
        else:
            _new_customer_message()
        return
    unread=int(tickets['unread'].sum())
    summary,new=st.columns([3,1],gap='small')
    summary.caption(t('Unread messages') + f': {unread}')
    if new.button(t('New message'),key='new_customer_message',**ui.STRETCH):
        st.session_state['_customer_active_chat']='new'
        st.rerun()
    view=st.radio(t('Show'),['All messages','Unread','Payment notices'],format_func=t,horizontal=True,key='customer_inbox_filter')
    if view=='Payment notices':
        notices=support.overdue_notices()
        if not notices:
            st.success(t('No overdue payments.'))
        for notice in notices:
            with st.container(border=True):
                st.caption(t('System payment notice'))
                st.error(t('Overdue amount') + f": ${notice['amount']:,.2f}")
                st.text(t('Loan reference') + ': ' + notice['loan_id'])
                st.text(t('Due date') + f": {notice['due_date']:%d/%m/%Y} · {notice['days_late']} " + t('days overdue'))
                if st.button(t('Discuss this payment'),key=f"discuss_payment_{notice['loan_id']}",**ui.STRETCH):
                    st.session_state['_customer_message_action']=notice['loan_id']
                    st.rerun()
        shown=tickets[tickets['loan_id'].notna()]
    elif view=='Unread':
        shown=tickets[tickets['unread']>0]
    else:
        shown=tickets
    if shown.empty:
        st.info(t('No messages here yet.'))
    for row in shown.to_dict('records'):
        with st.container(border=True):
            title=row['subject']
            if row['unread']:
                title+=f" · {row['unread']} "+t('unread')
            st.markdown('**'+t('Support team')+'**')
            st.text(title)
            st.caption(to_local(row['last_update']) + ' · ' + t(row['status']))
            st.text(str(row.get('preview') or '')[:140])
            loan_reference = _loan_reference(row.get('loan_id'))
            if loan_reference:
                st.caption(t('Loan reference')+': '+loan_reference)
            if row['waiting']:
                st.caption(t('Awaiting support reply'))
            if st.button(t('Open conversation'),key=f"customer_inbox_{row['ticket_id']}",**ui.STRETCH):
                st.session_state['_customer_active_chat']=row['ticket_id']
                st.rerun()


def _new_customer_message():
    loans=portal.my_loans()
    options=[None]+loans['loan_id'].tolist() if not loans.empty else [None]
    if st.session_state.get('chat_related_loan') not in options:
        st.session_state['chat_related_loan']=None
    loan=st.selectbox(t('Related loan (optional)'),options,
        format_func=lambda value:value or t('General question'),key='chat_related_loan')
    if loan:
        _,snap,schedule,_=portal.loan_details(loan)
        overdue=float(schedule.loc[schedule['payment_status']=='Overdue','amount_due'].sum())
        if snap['status']=='Active' and overdue>.005:
            st.error(t('Overdue amount')+f': ${overdue:,.2f}')
    from html import escape
    st.html('<div class="cd-chat-welcome"><div class="cd-support-symbol">CD</div><strong>'+
        escape(t('How can we help?'))+'</strong></div>')
    message=st.chat_input(t('Type your message…'),key='support_start_chat',max_chars=5000)
    if message:
        try:
            subject=('Payment question · '+loan) if loan else ' '.join(message.split())[:80]
            new_id=support.create_ticket(subject,message,loan)
            st.session_state['_support_open_chat']=new_id
            st.rerun()
        except (ValueError,PermissionError,OSError,audit.AuditError) as exc:
            show_error(exc,'send your message')


def render_staff():
    portal.require_role(*portal.STAFF)
    ui.page_header(t('Customer support'), t('Read customer questions, reply and resolve conversations.'), eyebrow=t('Loan team'))
    st.caption(t('Chats are deleted after 24 hours without a new message.'))
    _notice()
    tickets = support.tickets()
    waiting = int(tickets['waiting'].sum())
    inbox = st.columns(3)
    inbox[0].metric(t('Waiting for a reply'), waiting)
    inbox[1].metric(t('Unread customer messages'), int(tickets['unread'].sum()))
    inbox[2].metric(t('Open conversations'), int((tickets['status'] == 'Open').sum()))
    status = st.selectbox(t('Conversation status'), ['Waiting for reply', 'Open', 'Resolved', 'All'], format_func=t, key='i18n_views_support_py_135')
    if status == 'Waiting for reply':
        tickets = tickets[tickets['waiting']]
    elif status != 'All':
        tickets = tickets[tickets['status'] == status]
    if tickets.empty:
        st.info(t('No conversations with this status.'))
        return
    tickets = tickets.sort_values(['waiting', 'unread', 'last_update'], ascending=[False, False, True])
    rows = {r['ticket_id']: r for r in tickets.to_dict('records')}
    tid = st.selectbox(t('Conversation'), list(rows), format_func=lambda x: f'{rows[x].get('full_name') or rows[x]['username']} · {rows[x]['subject']}' + (' · Waiting for reply' if rows[x]['waiting'] else '') + (f' · {rows[x]['unread']} unread' if rows[x]['unread'] else ''), key='i18n_views_support_py_145')
    _conversation(rows[tid], staff=True)

def render_staff_profile():
    portal.require_role(*portal.STAFF)
    from views.customer import render_profile
    render_profile()
