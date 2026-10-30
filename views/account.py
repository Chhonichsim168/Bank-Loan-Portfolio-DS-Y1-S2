"""My account - change password, enrol multi-factor sign-in."""
from __future__ import annotations
from src.customer_i18n import t
import hmac
import streamlit as st
from src import auth, ui

def render() -> None:
    user = auth.current_user()
    ui.page_header(t('My account'), t('Your password and sign-in security.'), eyebrow=t('Account'))
    st.markdown(f'**{user.display_name}** - {user.role_label} - `{user.username}`')
    left, right = st.columns(2, gap='large')
    with left:
        ui.section(t('Change password'))
        with st.form('chg_pw', clear_on_submit=True, border=True):
            cur = st.text_input(t('Current password'), type='password', key='i18n_views_account_py_21')
            pw1 = st.text_input(t('New password'), type='password', key='i18n_views_account_py_22')
            pw2 = st.text_input(t('Repeat new password'), type='password', key='i18n_views_account_py_23')
            go = st.form_submit_button(t('Change password'), type='primary', key='i18n_views_account_py_24')
        if go:
            record = auth._read_users().get(user.username, {})
            ok, _ = auth.hash_password(cur, record.get('salt', '00'), int(record.get('iterations', auth.LEGACY_ITERATIONS)))
            if not hmac.compare_digest(ok, record.get('hash', '')):
                st.error(t('Current password is incorrect.'))
            elif pw1 != pw2:
                st.error(t('The two new passwords do not match.'))
            else:
                try:
                    auth.set_password(user.username, pw1)
                    st.success(t('Password changed.'))
                except ValueError as exc:
                    st.error(str(exc))
    with right:
        ui.section(t('Multi-factor sign-in'))
        if user.mfa_enabled:
            st.success(t('Enabled. You will be asked for a 6-digit code at every sign-in. To remove it, ask an Administrator.'))
        else:
            auth.render_mfa_enrol(user)
    ui.section(t('Account recovery'))
    st.caption(t('Generate a private, single-use recovery code for Forgot password. A new code replaces the previous one.'))
    with st.form('create_recovery_code', clear_on_submit=True):
        recovery_password = st.text_input(t('Confirm current password'), type='password', key='i18n_views_account_py_49')
        generate = st.form_submit_button(t('Generate recovery code'), key='i18n_views_account_py_50')
    if generate:
        try:
            recovery_code = auth.issue_recovery_code(user.username, recovery_password)
            st.code(recovery_code)
            st.warning(t('Save this code privately now. It will not be shown again.'))
        except ValueError as exc:
            st.error(str(exc))
