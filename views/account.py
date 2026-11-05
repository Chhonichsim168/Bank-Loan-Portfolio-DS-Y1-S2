"""My account - email address, sign-in methods (Google / password), password, MFA, recovery code."""
from __future__ import annotations

import hmac

import streamlit as st

from src import auth, mailer, ui
from src.customer_i18n import t
from src.security import esc


def _chip(text: str, tone: str) -> str:
    colours = {"ok": ("#E7F6EC", "#166534"), "warn": ("#FFF4E0", "#8A4B05"), "off": ("#EEF1F4", "#5B6676"),
               "info": ("#E6F2F0", "#0B6B62")}
    bg, fg = colours[tone]
    return (f'<span style="display:inline-block;background:{bg};color:{fg};border-radius:999px;'
            f'padding:2px 10px;font-size:.78rem;font-weight:600;margin:0 6px 4px 0">{esc(text)}</span>')


def _summary(user, info: dict) -> None:
    initials = "".join(w[0] for w in user.display_name.split()[:2]).upper() or "U"
    if info["email"]:
        badge = _chip(t("Verified") if info["verified"] else t("Not verified"), "ok" if info["verified"] else "warn")
        email = f'{esc(info["email"])} {badge}'
    else:
        email = f'<span style="color:#8A96A6">{esc(t("No email address yet"))}</span>'
    methods = ((_chip("Google ✓", "info") if info["google"] else "")
               + (_chip(t("Password") + " ✓", "info") if info["password"] else ""))
    st.markdown(f"""
    <div style="display:flex;gap:16px;align-items:center;background:#fff;border:1px solid #E1E6EC;
         border-radius:14px;padding:16px 18px;margin:.2rem 0 1rem 0">
      <div style="width:54px;height:54px;border-radius:50%;background:#D3F4EC;color:#07453F;font-weight:700;
           font-size:1.15rem;display:flex;align-items:center;justify-content:center;border:2px solid #87DACA;
           flex:none">{esc(initials)}</div>
      <div style="min-width:0">
        <div style="font-size:1.08rem;font-weight:700;color:#1B2430">{esc(user.display_name)}
          <span style="font-weight:500;color:#5B6676;font-size:.88rem"> · {esc(t(user.role_label))} ·
          <code>{esc(user.username)}</code></span></div>
        <div style="margin-top:4px;color:#1B2430;font-size:.92rem;word-break:break-all">&#9993;&#65039; {email}</div>
        <div style="margin-top:6px">{esc(t("Sign-in methods"))}: {methods}</div>
      </div>
    </div>""", unsafe_allow_html=True)


def _email_section(user, info: dict) -> None:
    ui.section(t("Email address"),
               t("Used to sign in with Google and to receive password reset codes."))
    with st.form("acct_email", clear_on_submit=True, border=True):
        new_email = st.text_input(t("New email address") if info["email"] else t("Email"),
                                  placeholder="you@gmail.com", key="acct_email_new")
        confirm = (st.text_input(t("Confirm current password"), type="password", key="acct_email_pw")
                   if info["password"] else None)
        save = st.form_submit_button(t("Save email"), type="primary")
    if save:
        if info["password"]:
            rec = auth._read_users().get(user.username, {})
            ok, _ = auth.hash_password(confirm or "", rec.get("salt", "00"),
                                       int(rec.get("iterations", auth.LEGACY_ITERATIONS)))
            if not hmac.compare_digest(ok, rec.get("hash", "")):
                st.error(t("Current password is incorrect."))
                return
        try:
            auth.set_email(user.username, new_email)
            st.session_state.pop("_acct_code_sent", None)
            st.success(t("Email saved. Verify it below."))
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    if not info["email"] or info["verified"]:
        if info["verified"]:
            st.caption(t("Your email is verified.") + (" " + t("Google sign-in is linked.") if info["google"] else ""))
        return

    st.markdown(f'**{esc(t("Verify your email"))}** - {esc(t("choose one way"))}:', unsafe_allow_html=True)
    ways = st.columns(2, gap="small")
    if auth.google_configured():
        with ways[0]:
            st.caption(t("Sign in with the Google account of this address. It also links Google to this account."))
            if st.button(t("Verify with Google"), key="acct_verify_google", **ui.STRETCH):
                auth.start_google_link(user.username)
                st.login("google")      # comes back signed in, with the email verified
    if mailer.configured():
        with ways[1]:
            st.caption(t("We email you a 6-digit code."))
            if st.button(t("Email me a code"), key="acct_send_code", **ui.STRETCH):
                try:
                    code = auth.issue_email_code(user.username, "verify")
                    mailer.send_code(info["email"], "verify", user.display_name, code, auth.EMAIL_CODE_MINUTES)
                    st.session_state["_acct_code_sent"] = True
                except (ValueError, RuntimeError) as exc:
                    st.error(str(exc))
        if st.session_state.get("_acct_code_sent"):
            st.info(t("Code sent to") + f" {auth.mask_email(info['email'])}")
            with st.form("acct_verify_code", clear_on_submit=True):
                code = st.text_input(t("6-digit code"), max_chars=7, placeholder="123456")
                go = st.form_submit_button(t("Verify email"), type="primary")
            if go:
                try:
                    auth.verify_email_with_code(user.username, code)
                    st.session_state.pop("_acct_code_sent", None)
                    st.success(t("Your email is verified."))
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    if not auth.google_configured() and not mailer.configured():
        st.caption(t("Email verification is not switched on for this installation. An Administrator can "
                     "confirm your address in User management."))


def _password_section(user, info: dict) -> None:
    if info["password"]:
        ui.section(t("Change password"))
        with st.form("chg_pw", clear_on_submit=True, border=True):
            cur = st.text_input(t("Current password"), type="password", key="i18n_views_account_py_21")
            pw1 = st.text_input(t("New password"), type="password", key="i18n_views_account_py_22")
            pw2 = st.text_input(t("Repeat new password"), type="password", key="i18n_views_account_py_23")
            go = st.form_submit_button(t("Change password"), type="primary", key="i18n_views_account_py_24")
        if go:
            record = auth._read_users().get(user.username, {})
            ok, _ = auth.hash_password(cur, record.get("salt", "00"),
                                       int(record.get("iterations", auth.LEGACY_ITERATIONS)))
            if not hmac.compare_digest(ok, record.get("hash", "")):
                st.error(t("Current password is incorrect."))
            elif pw1 != pw2:
                st.error(t("The two new passwords do not match."))
            else:
                try:
                    auth.set_password(user.username, pw1)
                    st.success(t("Password changed."))
                except ValueError as exc:
                    st.error(str(exc))
    else:
        ui.section(t("Password"), t("You sign in with Google, so a password is optional."))
        with st.form("set_pw", clear_on_submit=True, border=True):
            pw1 = st.text_input(t("New password"), type="password", key="acct_setpw_1")
            pw2 = st.text_input(t("Repeat new password"), type="password", key="acct_setpw_2")
            go = st.form_submit_button(t("Set a password"), type="primary")
        if go:
            if pw1 != pw2:
                st.error(t("The two new passwords do not match."))
            else:
                try:
                    auth.set_password(user.username, pw1)
                    st.success(t("Password set. You can now also sign in with your username or email and this "
                                 "password."))
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))


def render() -> None:
    user = auth.current_user()
    ui.page_header(t("My account"), t("Your email, sign-in methods and security."), eyebrow=t("Account"))
    info = auth.account_email(user.username)
    _summary(user, info)
    left, right = st.columns(2, gap="large")
    with left:
        _email_section(user, info)
    with right:
        _password_section(user, info)
    left, right = st.columns(2, gap="large")
    with left:
        ui.section(t("Multi-factor sign-in"))
        if user.mfa_enabled:
            st.success(t("Enabled. You will be asked for a 6-digit code at every sign-in. To remove it, ask an "
                         "Administrator."))
        else:
            auth.render_mfa_enrol(user)
    with right:
        ui.section(t("Account recovery"))
        if not info["password"]:
            st.caption(t("You sign in with Google, so you do not need a recovery code."))
            return
        st.caption(t("Generate a private, single-use recovery code for Forgot password. A new code replaces the "
                     "previous one."))
        with st.form("create_recovery_code", clear_on_submit=True):
            recovery_password = st.text_input(t("Confirm current password"), type="password",
                                              key="i18n_views_account_py_49")
            generate = st.form_submit_button(t("Generate recovery code"), key="i18n_views_account_py_50")
        if generate:
            try:
                recovery_code = auth.issue_recovery_code(user.username, recovery_password)
                st.code(recovery_code)
                st.warning(t("Save this code privately now. It will not be shown again."))
            except ValueError as exc:
                st.error(str(exc))
